import http.client
import json
import os
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import dashboard as D


class TestAuthOk(unittest.TestCase):
    TOKEN = "s3cret-token"

    def test_no_token_configured_allows_all(self):
        self.assertTrue(D.auth_ok(None, {}, None))
        self.assertTrue(D.auth_ok("", {}, "anything=1"))

    def test_query_token_matches(self):
        self.assertTrue(D.auth_ok(self.TOKEN, {}, None, query_token=self.TOKEN))

    def test_header_token_matches(self):
        self.assertTrue(D.auth_ok(self.TOKEN, {}, None, header_token=self.TOKEN))

    def test_cookie_digest_matches(self):
        cookie = f"other=1; {D.AUTH_COOKIE}={D._token_digest(self.TOKEN)}"
        self.assertTrue(D.auth_ok(self.TOKEN, {}, cookie))

    def test_wrong_credentials_rejected(self):
        self.assertFalse(D.auth_ok(self.TOKEN, {}, None))
        self.assertFalse(D.auth_ok(self.TOKEN, {}, None, query_token="wrong"))
        self.assertFalse(D.auth_ok(self.TOKEN, {}, f"{D.AUTH_COOKIE}=deadbeef"))
        # cookie 里放原始令牌不行——cookie 存的是摘要
        self.assertFalse(D.auth_ok(self.TOKEN, {}, f"{D.AUTH_COOKIE}={self.TOKEN}"))

    def test_only_scoped_tokens_configured_is_not_open(self):
        """只配了项目令牌、没配管理员令牌时，匿名请求必须被拒。

        这条是「未设 token 就全放行」那条捷径的边界：判空判的是所有令牌，
        不是只看管理员那一个。"""
        self.assertFalse(D.auth_ok(None, {"tok": {"a"}}, None))
        self.assertTrue(D.auth_ok(None, {"tok": {"a"}}, None, query_token="tok"))


class TestRenameCompatibility(unittest.TestCase):
    """改名不该让已经部署好的实例升级后起不来。

    `.env` 里写的是旧名，service.sh 导出的也是旧名，浏览器里还留着旧 cookie。
    这些都得继续认——过渡期结束后再删。"""

    def test_legacy_env_name_still_read(self):
        with mock.patch.dict(os.environ, {"GEOLOOK_TOKEN": "old"}, clear=True):
            self.assertEqual(D._env("XGEO_TOKEN"), "old")

    def test_new_env_name_wins(self):
        with mock.patch.dict(os.environ, {"XGEO_TOKEN": "new", "GEOLOOK_TOKEN": "old"},
                             clear=True):
            self.assertEqual(D._env("XGEO_TOKEN"), "new")

    def test_non_prefixed_name_has_no_fallback(self):
        with mock.patch.dict(os.environ, {"GEOLOOK_PATH": "old"}, clear=True):
            self.assertIsNone(D._env("SOMETHING_ELSE"))

    def test_both_header_names_accepted(self):
        self.assertEqual(D._header_token({"X-Xgeo-Token": "new"}), "new")
        self.assertEqual(D._header_token({"X-Geolook-Token": "old"}), "old")
        self.assertIsNone(D._header_token({}))

    def test_legacy_cookie_name_still_authenticates(self):
        new = f"{D.AUTH_COOKIE}={D._token_digest('tok')}"
        old = f"{D.LEGACY_COOKIE}={D._token_digest('tok')}"
        self.assertTrue(D.auth_ok("tok", {}, new))
        self.assertTrue(D.auth_ok("tok", {}, old), "旧 cookie 名不再认了，用户会被登出")

    def test_login_page_shows_the_new_brand(self):
        self.assertIn("GEO", D._LOGIN_HTML)
        self.assertNotIn("Look", D._LOGIN_HTML)


class TestScopedTokens(unittest.TestCase):
    def test_parse_scoped_tokens(self):
        self.assertEqual(D.parse_scoped_tokens("t1:a,b;t2:c"),
                         {"t1": {"a", "b"}, "t2": {"c"}})
        # 缺令牌或缺项目的段整条丢弃，不产生半截授权
        self.assertEqual(D.parse_scoped_tokens("t1:;:a;t2:c"), {"t2": {"c"}})
        self.assertEqual(D.parse_scoped_tokens(None), {})
        self.assertEqual(D.parse_scoped_tokens(""), {})

    def test_scope_of_admin_is_unrestricted(self):
        self.assertIsNone(D.scope_of("admin", {"t1": {"a"}}, None, header_token="admin"))

    def test_scope_of_scoped_token(self):
        got = D.scope_of("admin", {"t1": {"a"}}, None, header_token="t1")
        self.assertEqual(got, {"a"})

    def test_scope_of_unknown_credential_is_empty_not_none(self):
        """未命中必须是空集合。返回 None 会被当成管理员放行——这里判的是类型。"""
        self.assertEqual(D.scope_of("admin", {"t1": {"a"}}, None, header_token="bad"),
                         set())
        self.assertEqual(D.scope_of("admin", {"t1": {"a"}}, None), set())

    def test_scope_of_cookie_carries_scope(self):
        cookie = f"{D.AUTH_COOKIE}={D._token_digest('t1')}"
        self.assertEqual(D.scope_of("admin", {"t1": {"a"}}, cookie), {"a"})

    def test_path_slug(self):
        self.assertEqual(D.path_slug("/api/p/alpha"), "alpha")
        self.assertEqual(D.path_slug("/files/alpha/assets/llms.txt"), "alpha")
        self.assertEqual(D.path_slug("/api/collect/queue/alpha"), "alpha")
        # 前端构建产物也走 /assets/，但不在 /api/ 下，不能被当成项目路由
        self.assertIsNone(D.path_slug("/assets/app.js"))
        self.assertIsNone(D.path_slug("/api/projects"))
        self.assertIsNone(D.path_slug("/api/job/abc123"))


class TestAuthorization(unittest.TestCase):
    """授权必须真被执行，不只是有一个 auth_ok 函数。

    这一层专测「请求打进来会不会被挡住」——只测 auth_ok 的话，
    do_GET/do_POST 里那一行删掉，测试照样全绿。"""

    ADMIN = "admin-token"
    TENANT = "tenant-token"

    def setUp(self):
        self.tmp = TemporaryDirectory()
        work = Path(self.tmp.name) / "work"
        for slug in ("alpha", "beta"):
            d = work / slug
            d.mkdir(parents=True)
            (d / "geo.json").write_text(
                json.dumps({"brand": {"name": slug}, "questions": []}), "utf-8")
        self.workdir = work
        self.work = mock.patch.object(D.G, "WORK", work)
        self.work.start()
        self.tok = mock.patch.object(D.Handler, "TOKEN", self.ADMIN)
        self.tok.start()
        self.scopes = mock.patch.object(D.Handler, "SCOPES", {self.TENANT: {"alpha"}})
        self.scopes.start()
        self.log = mock.patch.object(D.Handler, "log_message", lambda *a, **k: None)
        self.log.start()
        self.addCleanup(self._teardown)
        self.srv = D.ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.srv.shutdown()
        self.srv.server_close()

    def _teardown(self):
        self.log.stop()
        self.scopes.stop()
        self.tok.stop()
        self.work.stop()
        self.tmp.cleanup()

    def _req(self, method, path, token=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            headers = {"X-Xgeo-Token": token} if token else {}
            payload = None
            if body is not None:
                payload = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=payload, headers=headers)
            r = conn.getresponse()
            return r.status, r.read(), (r.getheader("Content-Type") or "")
        finally:
            conn.close()

    def test_api_without_credentials_is_401(self):
        """写接口也一样要挡。POST 上的那行 check 是最容易被漏掉的一处。"""
        self.assertEqual(self._req("GET", "/api/projects")[0], 401)
        self.assertEqual(self._req("POST", "/api/config/alpha", body={"x": 1})[0], 401)
        self.assertEqual(self._req("POST", "/api/asset/alpha",
                                   body={"path": "llms.txt", "text": "x"})[0], 401)

    def test_tenant_cannot_read_another_project(self):
        status, _, _ = self._req("GET", "/api/p/beta", self.TENANT)
        self.assertEqual(status, 403)
        self.assertEqual(self._req("GET", "/api/files/beta", self.TENANT)[0], 403)
        self.assertEqual(self._req("GET", "/api/config/beta", self.TENANT)[0], 403)

    def test_tenant_can_read_own_project(self):
        self.assertEqual(self._req("GET", "/api/p/alpha", self.TENANT)[0], 200)

    def test_tenant_cannot_write_another_project(self):
        status, _, _ = self._req("POST", "/api/config/beta", self.TENANT, {"brand": {"name": "pwned"}})
        self.assertEqual(status, 403)
        saved = json.loads((self.workdir / "beta" / "geo.json").read_text("utf-8"))
        self.assertEqual(saved["brand"]["name"], "beta", "越权写入竟然落盘了")

    def test_tenant_project_list_is_filtered(self):
        status, body, _ = self._req("GET", "/api/projects", self.TENANT)
        self.assertEqual(status, 200)
        self.assertEqual([p["slug"] for p in json.loads(body)], ["alpha"])

    def test_tenant_cannot_use_admin_endpoints(self):
        self.assertEqual(self._req("GET", "/api/keys", self.TENANT)[0], 403)
        self.assertEqual(self._req("POST", "/api/init", self.TENANT,
                                   {"url": "https://x.com"})[0], 403)

    def test_admin_reaches_everything(self):
        self.assertEqual(self._req("GET", "/api/p/beta", self.ADMIN)[0], 200)
        self.assertEqual(len(json.loads(self._req("GET", "/api/projects", self.ADMIN)[1])), 2)

    def test_query_token_still_works_for_scoped(self):
        """/?token= 换 cookie 那条路对分项目令牌同样成立。"""
        status, _, _ = self._req("GET", "/api/p/alpha?token=" + self.TENANT)
        self.assertEqual(status, 302)

    def test_non_ascii_token_does_not_break_the_request(self):
        """hmac.compare_digest 收到含非 ASCII 的 str 会抛 TypeError，而 token
        来自 URL/请求头，谁都能塞中文进来。_auth 在 try 之外，抛出来就是连接
        被直接掐断，连 401 都回不去。"""
        # GET 拒绝时回的是登录页（不是 JSON），这里只认状态码
        self.assertEqual(self._req("GET", "/api/projects?token=%E4%B8%AD%E6%96%87")[0], 401)
        status, body, _ = self._req("POST", "/api/precheck", "%E4%B8%AD%E6%96%87",
                                    {"text": "x"})
        self.assertEqual(status, 401)
        self.assertIn("error", json.loads(body))

    def test_oversized_body_is_rejected(self):
        """请求体不设上限，一个声明超大 Content-Length 的请求就能把内存吃满。

        这里只声明不真发 8MB：服务端在读完请求体之前就回包，真发会让连接状态
        跟着变复杂，测的就成了协议而不是上限本身。"""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("POST", "/api/precheck", body=None, headers={
                "X-Xgeo-Token": self.ADMIN,
                "Content-Type": "application/json",
                "Content-Length": str(D.Handler.MAX_BODY + 1),
            })
            r = conn.getresponse()
            status, body = r.status, r.read()
        finally:
            conn.close()
        self.assertEqual(status, 400)
        self.assertIn("过大", json.loads(body)["error"])

    def test_sample_import_rejects_path_traversal(self):
        """file 字段直接拼进路径，必须挡住分隔符和 ..。

        挡不住的话，一条 POST 就能往 work/ 之外写文件。"""
        for bad in ("../../../evil.md", "sub/evil.md", r"sub\evil.md", ".hidden.md", "x.txt"):
            status, body, _ = self._req("POST", "/api/sample-import", self.ADMIN,
                                        {"slug": "alpha", "file": bad, "text": "x"})
            self.assertEqual(status, 400, f"{bad} 竟然被接受了")
        self.assertFalse((self.workdir.parent / "evil.md").exists())

    def test_sample_import_requires_both_fields(self):
        self.assertEqual(
            self._req("POST", "/api/sample-import", self.ADMIN, {"slug": "alpha"})[0], 400)
        self.assertEqual(
            self._req("POST", "/api/sample-import", self.ADMIN, {"file": "a.md"})[0], 400)


class TestAssetsAreNotExecutable(unittest.TestCase):
    """assets/ 是可写目录：写进去的 html 若按 text/html 发回来，
    写接口就等于拿到了同源脚本执行权（存储型 XSS）。"""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        work = Path(self.tmp.name) / "work"
        (work / "alpha" / "assets").mkdir(parents=True)
        (work / "alpha" / "deliverables").mkdir(parents=True)
        (work / "alpha" / "assets" / "snippet.html").write_text(
            "<script>alert(1)</script>", "utf-8")
        (work / "alpha" / "assets" / "llms.txt").write_text("hello", "utf-8")
        (work / "alpha" / "deliverables" / "report.html").write_text(
            "<b>报告</b>", "utf-8")
        self.work = mock.patch.object(D.G, "WORK", work)
        self.work.start()
        self.tok = mock.patch.object(D.Handler, "TOKEN", None)
        self.tok.start()
        self.log = mock.patch.object(D.Handler, "log_message", lambda *a, **k: None)
        self.log.start()
        self.addCleanup(self._teardown)
        self.srv = D.ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.srv.shutdown()
        self.srv.server_close()

    def _teardown(self):
        self.log.stop()
        self.tok.stop()
        self.work.stop()
        self.tmp.cleanup()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path)
            r = conn.getresponse()
            return r.status, (r.getheader("Content-Type") or ""), r.read()
        finally:
            conn.close()

    def test_asset_html_is_downgraded_to_text(self):
        status, ctype, body = self._get("/files/alpha/assets/snippet.html")
        self.assertEqual(status, 200)
        self.assertTrue(ctype.startswith("text/plain"), f"assets 下的 html 按 {ctype} 发出去了")
        self.assertEqual(body, b"<script>alert(1)</script>")

    def test_asset_txt_still_plain(self):
        status, ctype, _ = self._get("/files/alpha/assets/llms.txt")
        self.assertEqual(status, 200)
        self.assertTrue(ctype.startswith("text/plain"))

    def test_deliverable_html_still_renders(self):
        """交付物是要给人打开的页面，不能一起降级。"""
        status, ctype, _ = self._get("/files/alpha/deliverables/report.html")
        self.assertEqual(status, 200)
        self.assertTrue(ctype.startswith("text/html"), ctype)

    def test_nosniff_is_sent(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", "/files/alpha/assets/snippet.html")
            r = conn.getresponse()
            self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
            r.read()
        finally:
            conn.close()


class TestVerifyHistoryKeys(unittest.TestCase):
    """同一天验收两次：验收报告按 yyyy-mm-dd-HHMMSS 存，date 只截到天。

    前端把 date 当 each 的键，两条同一天的报告撞键，整个验收视图直接崩。
    所以载荷里必须另有一个逐文件唯一的键。"""

    def test_same_day_reports_get_distinct_keys(self):
        tmp = TemporaryDirectory()
        try:
            work = Path(tmp.name) / "work"
            (work / "alpha" / "verify").mkdir(parents=True)
            (work / "alpha" / "geo.json").write_text(
                json.dumps({"brand": {"name": "alpha"}}), "utf-8")
            for stamp in ("2026-09-21-100000", "2026-09-21-110000"):
                (work / "alpha" / "verify" / f"{stamp}.json").write_text(
                    json.dumps({"verified_at": "2026-09-21T10:00:00+08:00", "results": []}),
                    "utf-8")
            with mock.patch.object(D.G, "WORK", work):
                hist = D.project("alpha")["verify_history"]
        finally:
            tmp.cleanup()
        self.assertEqual(len(hist), 2)
        self.assertEqual([h["date"] for h in hist], ["2026-09-21", "2026-09-21"])
        self.assertEqual(len({h["key"] for h in hist}), 2, "同一天两份报告的项目键撞了")


class TestPublicBindGuard(unittest.TestCase):
    def test_public_host_without_token_dies(self):
        with mock.patch.dict(D.os.environ, {}, clear=True), \
             self.assertRaises(SystemExit):
            D.run(port=0, open_browser=False, host="0.0.0.0", token=None)


class TestStaticServing(unittest.TestCase):
    """前端构建产物的托管：scripts/ui_dist/ 优先，缺失时回退旧 ui.html。"""

    SHELL = "<html><body>NEW SHELL MARKER</body></html>"

    def setUp(self):
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "index.html").write_text(self.SHELL, "utf-8")
        (root / "assets").mkdir()
        (root / "assets" / "app.js").write_text("console.log(1)", "utf-8")

        # UI_DIST 尚未在 dashboard 里定义；create=True 让测试先跑到断言层，
        # 失败信息是「路由不存在」而不是 AttributeError。
        self.dist = mock.patch.object(D, "UI_DIST", root, create=True)
        self.dist.start()
        self.token = mock.patch.object(D.Handler, "TOKEN", None)
        self.token.start()
        self.log = mock.patch.object(D.Handler, "log_message", lambda *a, **k: None)
        self.log.start()
        self.addCleanup(self._teardown)

        self.srv = D.ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self._stop_server)

    def _stop_server(self):
        self.srv.shutdown()
        self.srv.server_close()

    def _teardown(self):
        self.log.stop()
        self.token.stop()
        self.dist.stop()
        self.tmp.cleanup()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path)
            r = conn.getresponse()
            return r.status, (r.getheader("Content-Type") or ""), r.read()
        finally:
            conn.close()

    def test_root_serves_built_shell(self):
        status, ctype, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        # 用 assertTrue 而非 assertIn：后者失败时会打印整个 body，
        # 回退路径下那是 232K 的旧看板，输出会炸。
        self.assertTrue(b"NEW SHELL MARKER" in body, "根路径没返回构建产物")

    def test_asset_served_with_right_type(self):
        status, ctype, body = self._get("/assets/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", ctype)
        self.assertEqual(body, b"console.log(1)")

    def test_asset_traversal_blocked(self):
        status, _, _ = self._get("/assets/../../etc/passwd")
        self.assertEqual(status, 403)

    def test_missing_dist_is_a_plain_404(self):
        """迁移收尾后没有回退：产物不在就是 404，不再悄悄退回旧单文件看板。

        这个「悄悄回退」正是旧行为的隐患——页面看着能开，跑的是另一套前端。
        """
        (Path(self.tmp.name) / "index.html").unlink()
        status, _, _ = self._get("/")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
