import http.client
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib.parse import parse_qs, urlparse

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
        page = D._login_html()
        self.assertIn("GEO", page)
        self.assertNotIn("Look", page)

    def test_login_page_keeps_the_token_route(self):
        """账号登录是**新增档**，老的令牌路要在界面上仍然可达（三份 README 都写着）。"""
        self.assertIn("?token=", D._login_html())

    def test_login_page_escapes_the_error_text(self):
        """错误回显是插进 HTML 的，虽然来路都是我们自己那几句固定文案 —— 也转它。"""
        page = D._login_html('<img src=x onerror="alert(1)">')
        self.assertNotIn("<img", page)
        self.assertIn("&lt;img", page)


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


class TestHostGuard(unittest.TestCase):
    """默认档（不设令牌）下只接受本机 Host。

    挡的是 DNS rebinding：浏览器里任何一个网页都能用 evil.com（解析到
    127.0.0.1）发起同源请求读写全部接口，包括 /api/keys 和发布接口。
    只测 _host_ok() 内部逻辑不够 —— 它在 do_GET/do_POST 里那一行被删掉，
    单测照样全绿，所以这里打真 HTTP。
    """

    @classmethod
    def setUpClass(cls):
        # 类级共享一个 server：四个用例各起一个的话，套件里会多出四次
        # bind/listen/close，Windows 上更容易撞到连接层偶发。
        cls.tmp = TemporaryDirectory()
        work = Path(cls.tmp.name) / "work"
        (work / "alpha").mkdir(parents=True)
        (work / "alpha" / "geo.json").write_text(
            json.dumps({"brand": {"name": "alpha"}, "questions": []}), "utf-8")
        cls.workdir = work
        cls.patches = [mock.patch.object(D.G, "WORK", work),
                       mock.patch.object(D.Handler, "TOKEN", None),
                       mock.patch.object(D.Handler, "SCOPES", {}),
                       mock.patch.object(D.Handler, "log_message", lambda *a, **k: None)]
        for p in cls.patches:
            p.start()
        cls.srv = D.ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        # 先 shutdown 再 close。顺序反过来的话，serve_forever 线程会去 select
        # 一个已经关掉的套接字，冒出 OSError(WinError 10038) 的噪音刷进测试输出。
        cls.srv.shutdown()
        cls.srv.server_close()
        for p in cls.patches:
            p.stop()
        cls.tmp.cleanup()

    def _req(self, method, path, host=None, origin=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            headers = {}
            if host is not None:
                headers["Host"] = host
            if origin is not None:
                headers["Origin"] = origin
            payload = None
            if body is not None:
                payload = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=payload, headers=headers)
            r = conn.getresponse()
            return r.status, r.read()
        finally:
            conn.close()

    def test_local_host_allowed(self):
        self.assertEqual(self._req("GET", "/api/projects")[0], 200)

    def test_foreign_host_rejected(self):
        # 默认 Host 是 127.0.0.1:port，显式改掉就是 DNS rebinding 的形态
        for h in ("evil.com", "evil.com:8765", "attacker.local"):
            self.assertEqual(self._req("GET", "/api/projects", host=h)[0], 403, h)

    def test_foreign_origin_rejected(self):
        # Host 是本机、但带外站 Origin —— 那是从别的页面打过来的 CSRF
        status, _ = self._req("POST", "/api/config/alpha", origin="https://evil.com",
                              body={"brand": {"name": "x"}})
        self.assertEqual(status, 403)

    def test_token_mode_skips_host_check(self):
        """配了令牌就不限 Host：鉴权已经挡住未认证请求，而且这时用户可能
        故意绑 0.0.0.0 从别的机器访问。这里应落到 401（鉴权拦），不是 403。"""
        with mock.patch.object(D.Handler, "TOKEN", "secret"):
            self.assertEqual(self._req("GET", "/api/projects", host="evil.com")[0], 401)


class TestConfigShapeGuard(unittest.TestCase):
    """geo.json 的结构校验。

    save_config 只备份不校验，一次畸形写就能把看板打崩：list_projects()
    走 cfg.get("brand", {}).get("name", ...)，brand 被写成字符串就抛
    AttributeError，/api/projects 整体 500 —— 所有项目的列表都打不开。
    """

    def test_rejects_malformed_shapes(self):
        for body, why in (
            ({"brand": "x"}, "brand 被写成字符串"),
            ({"brand": {"name": 123}}, "brand.name 不是字符串"),
            ({"questions": "q"}, "questions 不是数组"),
            ({"competitors": {}}, "competitors 不是数组"),
            ({"market": []}, "market 不是字符串"),
            ({}, "空对象"),
        ):
            self.assertIsNotNone(D.config_shape_error(body), why)

    def test_accepts_valid_shapes(self):
        for body in ({"brand": {"name": "x"}}, {"market": "cn"},
                     {"questions": [], "competitors": []},
                     {"brand": {"name": "x", "aliases": []}, "market": "both"}):
            self.assertIsNone(D.config_shape_error(body), body)


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


class TestAccountLogin(unittest.TestCase):
    """账号档：FreeModel API Key → /me → 允许名单 → 本地会话。

    这一档最容易出的是**组合漏洞**而不是单点漏洞：
      · `auth_ok` 在「两个令牌变量都没配」时恒返回 True，而只配 XGEO_ACCOUNTS 的
        实例正好落在那个分支上 —— 少一对括号，允许名单就形同虚设、所有人放行。
      · 会话与令牌共用同一个 cookie 名，靠「摘要在不在 SESSIONS 里」区分；
        写成「有 cookie 就放行」是另一个同向的坑。
    所以这里既有纯函数测试，也有真起服务的「打进来会不会被挡住」。
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        work = Path(self.tmp.name) / "work"
        for slug in ("alpha", "beta"):
            d = work / slug
            d.mkdir(parents=True)
            (d / "geo.json").write_text(
                json.dumps({"brand": {"name": slug}, "questions": []}), "utf-8")
        self.work = mock.patch.object(D.G, "WORK", work)
        self.work.start()
        # 关键：**不配任何令牌，只配账号档** —— 正是那个组合漏洞的形态
        self.tok = mock.patch.object(D.Handler, "TOKEN", None)
        self.tok.start()
        self.scopes = mock.patch.object(D.Handler, "SCOPES", {})
        self.scopes.start()
        self.env = mock.patch.dict(os.environ, {
            "XGEO_ACCOUNTS": "boss@example.com:*;guest@example.com:beta",
            "XGEO_AUTH_BASE": "http://127.0.0.1:9/api/auth",   # 不可达，登录一定 503
        }, clear=False)
        self.env.start()
        D.SESSIONS.clear()
        D.LOGIN_HITS.clear()
        self.addCleanup(self._teardown)
        self.srv = D.ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.srv.shutdown(), self.srv.server_close()))

    def _teardown(self):
        self.env.stop()
        self.scopes.stop()
        self.tok.stop()
        self.work.stop()
        self.tmp.cleanup()

    def _req(self, method, path, cookie=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            headers = {}
            if cookie:
                headers["Cookie"] = cookie
            payload = None
            if body is not None:
                payload = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=payload, headers=headers)
            r = conn.getresponse()
            # 第三个返回整个响应头（dict 语义）：测试里既要看 Content-Type 也要看
            # Set-Cookie，只固定回一个的话另一个断言就会拿到 None 而误判。
            return r.status, r.read(), dict(r.headers)
        finally:
            conn.close()

    # --- 纯函数 ---

    def test_parse_accounts_admin_and_tenant(self):
        acc = D.parse_accounts("a@x.com:*;b@x.com:proj-a,proj-b")
        self.assertTrue(acc["a@x.com"]["admin"])
        self.assertEqual(acc["b@x.com"]["projects"], {"proj-a", "proj-b"})
        self.assertFalse(acc["b@x.com"]["admin"])

    def test_bare_email_is_dropped(self):
        """允许名单是安全边界：少一个冒号宁可当没写，也不能默认给管理员。"""
        self.assertEqual(D.parse_accounts("a@x.com"), {})
        self.assertEqual(D.parse_accounts("a@x.com:;b@x.com:*")["b@x.com"]["admin"], True)

    def test_session_cookie_hides_the_id_and_carries_max_age(self):
        sid = D.session_new("boss@example.com", {"admin": True, "projects": set()})
        c = D.session_cookie(sid, secure=True)
        self.assertNotIn(sid, c, "cookie 里不该出现会话 id 原文")
        self.assertIn(D._token_digest(sid), c)
        self.assertIn("Max-Age=", c, "没有过期时间 = 关浏览器就掉线")
        self.assertIn("HttpOnly", c)
        self.assertIn("Secure", c)
        self.assertNotIn("Secure", D.session_cookie(sid, secure=False), "本机 http 不能带 Secure")

    def test_session_expires(self):
        sid = D.session_new("boss@example.com", {"admin": True, "projects": set()})
        cookie = f"{D.AUTH_COOKIE}={D._token_digest(sid)}"
        self.assertIsNotNone(D.session_get(cookie))
        D.SESSIONS[D._token_digest(sid)]["exp"] = 1        # 过期
        self.assertIsNone(D.session_get(cookie))
        self.assertTrue(D.session_drop(cookie) is False, "过期条目应已被清掉")

    def test_login_rate_limited(self):
        for _ in range(10):
            self.assertTrue(D.login_allowed("9.9.9.9"))
            D.login_note("9.9.9.9")
        self.assertFalse(D.login_allowed("9.9.9.9"))
        self.assertTrue(D.login_allowed("8.8.8.8"), "限流是按 IP 的，别连坐")

    # --- 打进来会不会被挡住 ---

    def test_accounts_configured_without_token_is_not_open(self):
        """★ 这条锁的是那个组合漏洞。

        只配 XGEO_ACCOUNTS、不配任何令牌时，`auth_ok(None, {}, …)` 返回 True ——
        少一对括号，未认证请求就全部放行、允许名单白配。
        """
        self.assertEqual(self._req("GET", "/api/projects")[0], 401)
        self.assertEqual(self._req("POST", "/api/config/alpha", body={"x": 1})[0], 401)

    def test_login_page_still_served_when_unauthorized(self):
        status, _body, headers = self._req("GET", "/api/projects")
        self.assertEqual(status, 401, "探活脚本按 200/401 判活，别改成 302")
        self.assertIn("text/html", headers.get("Content-Type") or "")

    def test_login_with_unreachable_auth_service_is_503_not_open(self):
        """认证服务挂了要报错，**不能放行** —— 那是永久后门。"""
        status, body, _ = self._req("POST", "/api/auth/login",
                                    body={"credential": "sk-fm-x"})
        self.assertEqual(status, 503)
        self.assertNotIn(b'"ok": true', body)

    def test_login_rejected_when_no_allowlist_configured(self):
        with mock.patch.dict(os.environ, {"XGEO_ACCOUNTS": ""}, clear=False):
            status, _, _ = self._req("POST", "/api/auth/login",
                                     body={"credential": "sk-fm-x"})
        self.assertEqual(status, 403)

    def test_session_from_allowlisted_account_gets_in(self):
        sid = D.session_new("boss@example.com", {"admin": True, "projects": set()})
        cookie = f"{D.AUTH_COOKIE}={D._token_digest(sid)}"
        self.assertEqual(self._req("GET", "/api/projects", cookie=cookie)[0], 200)
        status, body, _ = self._req("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["mode"], "account")
        self.assertEqual(json.loads(body)["email"], "boss@example.com")

    def test_tenant_session_keeps_project_isolation(self):
        """会话用户照样受 _deny 管：租户只能碰自己名下的项目。"""
        sid = D.session_new("guest@example.com", {"admin": False, "projects": {"beta"}})
        cookie = f"{D.AUTH_COOKIE}={D._token_digest(sid)}"
        self.assertEqual(self._req("GET", "/api/p/beta", cookie=cookie)[0], 200)
        self.assertEqual(self._req("GET", "/api/p/alpha", cookie=cookie)[0], 403)
        self.assertEqual(self._req("GET", "/api/keys", cookie=cookie)[0], 403,
                         "管理员接口对租户会话也要挡住")

    def test_logout_drops_the_session(self):
        sid = D.session_new("boss@example.com", {"admin": True, "projects": set()})
        cookie = f"{D.AUTH_COOKIE}={D._token_digest(sid)}"
        status, _, headers = self._req("POST", "/api/auth/logout", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn("Max-Age=0", headers.get("Set-Cookie") or "")
        self.assertEqual(self._req("GET", "/api/projects", cookie=cookie)[0], 401,
                         "登出要立刻失效（会话在进程内就是为了这个）")

    def test_random_cookie_is_not_a_session(self):
        """cookie 名与会话共用，靠「摘要在不在 SESSIONS 里」区分 —— 别写成有 cookie 就放行。"""
        self.assertEqual(self._req("GET", "/api/projects",
                                   cookie=f"{D.AUTH_COOKIE}=deadbeef")[0], 401)


class _FakeMe(BaseHTTPRequestHandler):
    """假的 fm-auth `/me`。真服务在线上，单测不能依赖外网。

    返回结构对齐线上的真实调用点（公开的 console/js/auth.js：
    `data.code === 200 && data.data.api_key`），只认一个 key。
    """

    seen: list = []
    payload: dict = {}

    def do_GET(self):
        token = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
        type(self).seen.append(token)
        if token == "sk-fm-good":
            body = json.dumps({"code": 200, "data": dict(type(self).payload)}).encode()
            self.send_response(200)
        else:
            body = json.dumps({"code": 400, "msg": "Invalid token"}).encode()
            self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class TestAccountLoginEndToEnd(unittest.TestCase):
    """登录的**正路**：key → /me → 允许名单 → 下发 cookie → 真的进得去。

    上一套（TestAccountLogin）只验「挡得住」——**一个全挡住的实现也能全绿**。
    这条补正路，并钉住那条硬约束：账号档开着时，老令牌那三条路一条都不能断。
    """

    EMAIL = "boss@example.com"
    TOKEN = "s3cret-admin-token"

    def setUp(self):
        _FakeMe.seen = []
        _FakeMe.payload = {"email": self.EMAIL, "api_key": "sk-fm-fresh"}
        self.auth = D.ThreadingHTTPServer(("127.0.0.1", 0), _FakeMe)
        threading.Thread(target=self.auth.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.auth.shutdown(), self.auth.server_close()))

        self.tmp = TemporaryDirectory()
        work = Path(self.tmp.name) / "work"
        for slug in ("alpha", "beta"):
            d = work / slug
            d.mkdir(parents=True)
            (d / "geo.json").write_text(
                json.dumps({"brand": {"name": slug}, "questions": []}), "utf-8")
        self.work = mock.patch.object(D.G, "WORK", work)
        self.work.start()
        # 管理员令牌也在：这才是「账号档 + 令牌档并存」的形态，也是老用户的升级路径
        self.tok = mock.patch.object(D.Handler, "TOKEN", self.TOKEN)
        self.tok.start()
        self.scopes = mock.patch.object(D.Handler, "SCOPES", {})
        self.scopes.start()
        self.env = mock.patch.dict(os.environ, {
            "XGEO_ACCOUNTS": "boss@example.com:*;guest@example.com:beta",
            "XGEO_AUTH_BASE": f"http://127.0.0.1:{self.auth.server_address[1]}/api/auth",
        }, clear=False)
        self.env.start()
        D.SESSIONS.clear()
        D.LOGIN_HITS.clear()
        self.addCleanup(self._teardown)
        self.srv = D.ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.srv.shutdown(), self.srv.server_close()))

    def _teardown(self):
        self.env.stop()
        self.scopes.stop()
        self.tok.stop()
        self.work.stop()
        self.tmp.cleanup()

    def _req(self, method, path, cookie=None, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            h = dict(headers or {})
            if cookie:
                h["Cookie"] = cookie
            payload = None
            if body is not None:
                payload = json.dumps(body).encode("utf-8")
                h["Content-Type"] = "application/json"
            conn.request(method, path, body=payload, headers=h)
            r = conn.getresponse()
            return r.status, r.read(), dict(r.headers)
        finally:
            conn.close()

    def _login(self, cred="sk-fm-good", **kw):
        return self._req("POST", "/api/auth/login", body={"credential": cred}, **kw)

    @staticmethod
    def _cookie_of(headers):
        """从 Set-Cookie 里取 `名=值` 那一段（后面还挂着属性）。"""
        return (headers.get("Set-Cookie") or "").split(";")[0]

    # --- 正路 ---

    def test_allowlisted_key_gets_a_working_session(self):
        status, body, headers = self._login()
        self.assertEqual(status, 200, body)
        info = json.loads(body)
        self.assertEqual(info["email"], self.EMAIL)
        self.assertTrue(info["admin"])
        cookie = self._cookie_of(headers)
        self.assertTrue(cookie.startswith(f"{D.AUTH_COOKIE}="), headers.get("Set-Cookie"))
        # 拿到 cookie 才算真进得去 —— 只验 200 的话，不下发 cookie 也能过。
        self.assertEqual(self._req("GET", "/api/projects", cookie=cookie)[0], 200)
        status, body, _ = self._req("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["mode"], "account")

    def test_credential_reaches_the_auth_service_and_is_not_echoed(self):
        _status, body, headers = self._login()
        self.assertEqual(_FakeMe.seen, ["sk-fm-good"], "凭据没按 ?token= 传出去")
        self.assertNotIn("sk-fm-good", body.decode("utf-8"))
        self.assertNotIn("sk-fm-good", headers.get("Set-Cookie") or "")

    def test_session_cookie_gets_secure_only_behind_https(self):
        """本机 http 加 Secure，浏览器会直接丢掉 cookie —— 表现是「登录成功却没进去」。"""
        _s, _b, plain = self._login()
        self.assertNotIn("Secure", plain.get("Set-Cookie") or "")
        _s2, _b2, proxied = self._login(headers={"X-Forwarded-Proto": "https"})
        self.assertIn("Secure", proxied.get("Set-Cookie") or "")

    def test_bad_key_is_401_and_sets_no_cookie(self):
        status, _body, headers = self._login("sk-fm-wrong")
        self.assertEqual(status, 401)
        self.assertIsNone(headers.get("Set-Cookie"))

    def test_key_of_an_account_outside_the_allowlist_is_403(self):
        _FakeMe.payload = {"email": "stranger@example.com"}
        status, body, headers = self._login()
        self.assertEqual(status, 403)
        self.assertIn("允许名单", json.loads(body)["error"])
        self.assertIsNone(headers.get("Set-Cookie"))

    def test_missing_email_blames_the_shape_not_the_allowlist(self):
        """字段名一变，含糊的报错会把人引去翻允许名单 —— 这里必须指出是响应的问题。"""
        _FakeMe.payload = {"api_key": "sk-fm-fresh"}
        status, body, _ = self._login()
        self.assertEqual(status, 502)
        self.assertIn("邮箱", json.loads(body)["error"])

    # --- 那三条老路 ---

    def test_query_token_route_still_works(self):
        status, _body, headers = self._req("GET", f"/?token={self.TOKEN}")
        self.assertEqual(status, 302, "老令牌换 cookie 那条路断了")
        self.assertIn(D._token_digest(self.TOKEN), headers.get("Set-Cookie") or "")

    def test_header_token_route_still_works(self):
        status, _, _ = self._req("GET", "/api/projects",
                                 headers={"X-Xgeo-Token": self.TOKEN})
        self.assertEqual(status, 200, "X-Xgeo-Token 那条路断了")

    def test_token_cookie_route_still_works(self):
        cookie = f"{D.AUTH_COOKIE}={D._token_digest(self.TOKEN)}"
        self.assertEqual(self._req("GET", "/api/projects", cookie=cookie)[0], 200)

    def test_account_session_cannot_reach_admin_routes_when_tenant(self):
        """会话是「另一个身份来源」，不是「另一个权限层」——照样受 _deny 管。"""
        sid = D.session_new("guest@example.com", {"admin": False, "projects": {"beta"}})
        cookie = f"{D.AUTH_COOKIE}={D._token_digest(sid)}"
        self.assertEqual(self._req("GET", "/api/p/beta", cookie=cookie)[0], 200)
        self.assertEqual(self._req("GET", "/api/p/alpha", cookie=cookie)[0], 403)
