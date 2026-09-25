import http.client
import io
import json
import os
import re
import threading
import time
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
        """账号登录是**新增档**，老的令牌路要在界面上仍然可达（三份 README 都写着）。

        查三样而不是查子串：只断言 `?token=` 存在的话，把输入框删掉、按钮留着
        （`getElementById('t')` 会变成空引用）依然是绿的。
        """
        page = D._login_html()
        self.assertIn('id="t"', page, "令牌输入框没了")
        self.assertIn("getElementById('t')", page, "按钮没接上输入框")
        self.assertIn("?token=", page)

    def test_login_page_shows_the_admin_form_when_accounts_are_off(self):
        """账号档没开时**别把 FreeModel API Key 摆成主入口** —— 那个框点下去只会回
        「这个实例没有配账号登录」，用户第一眼看到的就是个死框。这时主入口换成
        管理员账号，令牌那条老路照旧留在折叠里。"""
        page = D._login_html(accounts_on=False)
        self.assertIn('id="au"', page)
        self.assertIn('id="ap"', page)
        self.assertIn('id="t"', page)
        self.assertNotIn('id="k"', page, "没开的档位不该出现主输入框")
        # 开了的那份照旧
        self.assertIn('id="k"', D._login_html(accounts_on=True))

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


class _DrainStub:
    """只喂 _drain/_drain_chunked 需要的三个属性 —— 不起 socket，确定性地验分帧。"""

    def __init__(self, raw: bytes, headers: dict):
        self.rfile = io.BytesIO(raw)
        self.headers = headers
        self.close_connection = False

    _drain = D.Handler._drain
    _drain_chunked = D.Handler._drain_chunked
    _body = D.Handler._body

    @property
    def left(self) -> int:
        return len(self.rfile.getvalue()) - self.rfile.tell()


class TestProxyTrust(unittest.TestCase):
    """反代信任的判据。`_proxied()` 为假的那一支在别的用例里从不执行，
    而那正是安全上更关键的一支（两个头都不可信时才生效的保护）。"""

    class _H:
        """_proxied/_client_ip/_https 只用到 client_address 与 headers。"""

        def __init__(self, peer, headers=None):
            self.client_address = (peer, 12345)
            self.headers = headers or {}

        _proxied = D.Handler._proxied
        _client_ip = D.Handler._client_ip
        _https = D.Handler._https

    def test_loopback_helpers(self):
        # 127.0.0.2/127.0.1.1 是 Debian 系 /etc/hosts 把主机名指过去的地方，也是
        # 整段 127/8；::ffff:127.0.0.1 是绑 :: 时同机反代从 IPv4 回来的形状。
        # 字符串元组认不出它们，于是「本机」被当成外站 → 假 403 / 限流共桶。
        for host in ("127.0.0.1", "127.0.0.2", "127.0.1.1", "::1", "localhost",
                     "::ffff:127.0.0.1"):
            self.assertTrue(D.is_loopback(host), host)
        for host in ("192.168.1.29", "10.0.0.1", "", None, "evil.example", "1.2.3.4 "):
            self.assertFalse(D.is_loopback(host), host)

    def test_headers_are_ignored_from_a_non_loopback_peer(self):
        h = self._H("192.168.1.29", {"X-Real-IP": "1.2.3.4",
                                     "X-Forwarded-Proto": "https"})
        self.assertFalse(h._proxied(), "异机反代默认不该被信任")
        self.assertEqual(h._client_ip(), "192.168.1.29", "限流键取了不可信的头部")
        self.assertFalse(h._https(), "Secure 由不可信的头部决定")

    def test_headers_are_honoured_from_a_loopback_peer(self):
        """仓库自带的 deploy.sh 就是这一形态（nginx 同机，覆写 X-Real-IP）。"""
        h = self._H("127.0.0.1", {"X-Real-IP": "1.2.3.4", "X-Forwarded-Proto": "https"})
        self.assertTrue(h._proxied())
        self.assertEqual(h._client_ip(), "1.2.3.4")
        self.assertTrue(h._https())

    def test_the_switch_is_a_whitelist(self):
        """`XGEO_TRUST_PROXY=off` 是最顺手的关闭写法。用黑名单解析它会被判成「开」，
        于是任何客户端自填的 X-Real-IP 都能决定自己落在哪个限流桶、并决定会话 cookie
        带不带 Secure。"""
        for on in ("1", "true", "YES", "On", " true "):
            with mock.patch.dict(os.environ, {"XGEO_TRUST_PROXY": on}, clear=False):
                self.assertTrue(D.trust_proxy(), on)
        for off in ("", "0", "false", "no", "off", "disable", "2"):
            with mock.patch.dict(os.environ, {"XGEO_TRUST_PROXY": off}, clear=False):
                self.assertFalse(D.trust_proxy(), off)

    def test_explicit_switch_covers_remote_proxies(self):
        """反代在别的机器上（K8s / CF Tunnel）时要显式打开，否则退化成
        「全站共用一个限流桶 + cookie 不带 Secure」。"""
        with mock.patch.dict(os.environ, {"XGEO_TRUST_PROXY": "1"}, clear=False):
            h = self._H("192.168.1.29", {"X-Real-IP": "1.2.3.4",
                                         "X-Forwarded-Proto": "https"})
            self.assertTrue(h._proxied())
            self.assertEqual(h._client_ip(), "1.2.3.4")
            self.assertTrue(h._https())

    def test_junk_x_real_ip_falls_back_to_the_socket(self):
        """桶键是任意头部时，对端就能决定这个进程级字典的键长与键数。"""
        h = self._H("127.0.0.1", {"X-Real-IP": "x" * 5000})
        self.assertEqual(h._client_ip(), "127.0.0.1")

    def test_drain_reads_the_declared_body(self):
        st = _DrainStub(b"hello", {"Content-Length": "5"})
        st._drain()
        self.assertEqual(st.left, 0)
        self.assertFalse(st.close_connection)

    def test_drain_walks_the_chunked_framing(self):
        """分块体是正常客户端发得出的形状：整串等值判断会让它落到「没读」。"""
        for headers in ({"Transfer-Encoding": "chunked"},
                        {"Transfer-Encoding": "chunked, gzip"}):
            st = _DrainStub(b"5\r\nhello\r\n0\r\n\r\n", headers)
            st._drain()
            self.assertEqual(st.left, 0, headers)
            self.assertFalse(st.close_connection, headers)

    def test_drain_gives_up_past_the_ceiling(self):
        """两个边界仍然只能断连接（那时响应可能被吞，是写明的取舍）。"""
        big = _DrainStub(b"x" * 10, {"Content-Length": str(D.Handler.MAX_BODY + 1)})
        big._drain()
        self.assertTrue(big.close_connection)
        self.assertEqual(big.left, 10, "声明超限时不该真的去读它")

        chunked = _DrainStub(b"ff0000\r\n" + b"x" * 4, {"Transfer-Encoding": "chunked"})
        chunked._drain()          # 单块就超 MAX_BODY
        self.assertTrue(chunked.close_connection)

    def test_drain_rejects_non_canonical_chunk_sizes(self):
        """`int(x, 16)` 连 `-1` 都收，而 `read(-1)` 等于读到 EOF：上限形同虚设、
        内存由对端决定（实测未认证请求能把服务端 RSS 从 45MB 喂到 250MB）。
        块长度只认规范的十六进制，认不出的一律当畸形。"""
        for bad in (b"-1", b"-ffff", b"0x10", b"zz", b"", b"+1"):   # `1 ` 会被 strip 成合法值，不算畸形
            st = _DrainStub(bad + b"\r\n" + b"x" * 32, {"Transfer-Encoding": "chunked"})
            st._drain()
            self.assertTrue(st.close_connection, bad)
            self.assertGreater(st.left, 0, f"{bad!r} 被读了")
        # 合法的照旧走通
        st = _DrainStub(b"20\r\n" + b"x" * 32 + b"\r\n0\r\n\r\n",
                        {"Transfer-Encoding": "chunked"})
        st._drain()
        self.assertFalse(st.close_connection)
        self.assertEqual(st.left, 0)

    def test_body_rejects_multi_value_transfer_encoding(self):
        """整串等值判断会让 `chunked, gzip` 落空 → 被当成「没有体」→ 余下字节被当成
        下一个请求行（反代池化上游时是跨用户走私面）。"""
        st = _DrainStub(b"5\r\nhello\r\n0\r\n\r\n", {"Transfer-Encoding": "chunked, gzip"})
        with self.assertRaises(ValueError):
            st._body()
        self.assertTrue(st.close_connection)

    def test_login_hits_is_capped(self):
        """桶键是来源，直连或透传 X-Real-IP 时来源可以很多 —— 只删空桶不够，
        每个新来源都会留下一个非空桶。"""
        D.LOGIN_HITS.clear()
        for i in range(1200):
            ip = "10.%d.%d.%d" % (i // 65536 % 256, i // 256 % 256, i % 256)
            D.login_note(ip)
            D.login_allowed(ip)
        self.assertLessEqual(len(D.LOGIN_HITS), 1024, "封顶没生效")

    def test_request_read_has_a_timeout(self):
        """没有超时就能用「声明一个 Content-Length 却不发体」占住线程 ——
        一连接一线程，占满即拒绝服务。"""
        self.assertIsNotNone(D.Handler.timeout)
        self.assertLessEqual(D.Handler.timeout, 60)

    def test_drain_survives_a_dead_peer(self):
        class Dead(io.BytesIO):
            def read(self, *a):
                raise ConnectionResetError("对端 RST")

        st = _DrainStub(b"", {"Content-Length": "5"})
        st.rfile = Dead()
        st._drain()               # 不抛：那时已经回不了任何东西了
        self.assertTrue(st.close_connection)


class TestBindPublicDerivation(unittest.TestCase):
    """`BIND_PUBLIC` 必须按**绑定后的地址**推，不能按 XGEO_HOST 那个字符串。

    按字符串推的后果是一条真洞：`XGEO_HOST=127.0.1.1`（Debian 系 /etc/hosts 把
    主机名指过去）仍然只绑回环，却被判成「对外」→ 账号档的 Host 门整体失效 →
    DNS rebinding 能拿到一个管理员会话（复审实测：200 + 会话 cookie）。
    这一条走真 `run()`（socket 起在 127.0.1.1，服务立刻关掉），因为它要钉的是
    「值来自 `srv.server_address`」这层接线，而不是某个纯函数。
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.work = mock.patch.object(D.G, "WORK", Path(self.tmp.name))
        self.work.start()
        self.addCleanup(self.work.stop)
        self.tmp.cleanup and self.addCleanup(self.tmp.cleanup)
        for name, val in (("reap_orphans", lambda *a, **k: None),
                          ("prune_jobs", lambda *a, **k: None)):
            m = mock.patch.object(D.J, name, val)
            m.start()
            self.addCleanup(m.stop)
        m = mock.patch.object(D, "_monitor_loop", lambda: None)
        m.start()
        self.addCleanup(m.stop)
        m = mock.patch.object(D, "open_browser", False, create=True)
        m.start()
        self.addCleanup(m.stop)

    def _bind(self, host):
        """在指定地址上真起一次，返回 run() 之后落下的 BIND_PUBLIC。"""
        made = []

        class Rec(D.ThreadingHTTPServer):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                made.append(self)

        # 初值给 None：False 是**合法结果**（回环），拿它当初值就分不清
        # 「还没注入」和「注入成 False」。run() 跑过那一行之后它一定是个 bool。
        # 带个令牌：绑 0.0.0.0 又没有任何凭据时 run() 会按设计 die（绑公网必须配
        # 凭据），那就走不到注入那一行 —— 这里要测的是注入，不是守卫。
        with mock.patch.object(D, "ThreadingHTTPServer", Rec),              mock.patch.object(D.Handler, "BIND_PUBLIC", None),              mock.patch.object(D.Handler, "TOKEN", "tok-bind-test"):
            t = threading.Thread(target=lambda: D.run(port=0, host=host, token="tok-bind-test"),
                                 daemon=True)
            t.start()
            for _ in range(200):
                if made and D.Handler.BIND_PUBLIC is not None:
                    break
                time.sleep(0.05)
            got = D.Handler.BIND_PUBLIC
            if made:
                made[0].shutdown()
                made[0].server_close()
            t.join(timeout=5)
        return got

    def test_loopback_bind_is_not_public(self):
        for host in ("127.0.0.1", "127.0.1.1"):
            with self.subTest(host=host):
                self.assertFalse(self._bind(host), f"{host} 只绑回环，却被判成对外")

    def test_non_loopback_bind_is_public(self):
        self.assertTrue(self._bind("0.0.0.0"))


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

    def _req(self, method, path, cookie=None, body=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            headers = dict(headers or {})
            if cookie:
                headers["Cookie"] = cookie
            payload = None
            if raw is not None:
                payload = raw                      # 原样发，用来造畸形/超大的体
            elif body is not None:
                payload = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=payload, headers=headers)
            r = conn.getresponse()
            # 第三个返回整个响应头（dict 语义）：测试里既要看 Content-Type 也要看
            # Set-Cookie，只固定回一个的话另一个断言就会拿到 None 而误判。
            return r.status, r.read(), dict(r.headers)
        finally:
            conn.close()

    @staticmethod
    def _cookie_of(headers):
        """从 Set-Cookie 里取 `名=值` 那一段（后面还挂着属性）。"""
        return (headers.get("Set-Cookie") or "").split(";")[0]

    # --- 纯函数 ---

    def test_parse_accounts_admin_and_tenant(self):
        acc = D.parse_accounts("a@x.com:*;b@x.com:proj-a,proj-b")
        self.assertTrue(acc["a@x.com"]["admin"])
        self.assertEqual(acc["b@x.com"]["projects"], {"proj-a", "proj-b"})
        self.assertFalse(acc["b@x.com"]["admin"])

    def test_project_names_are_lowercased(self):
        """项目标识就是目录名，而 SLUG_OK 只允许小写：写成 Proj-A 今天等于
        「登进来了但什么都看不到」，没有任何报错。"""
        acc = D.parse_accounts("a@x.com:Proj-A,proj-b")
        self.assertEqual(acc["a@x.com"]["projects"], {"proj-a", "proj-b"})

    def test_bare_email_is_dropped(self):
        """允许名单是安全边界：少一个冒号宁可当没写，也不能默认给管理员。"""
        self.assertEqual(D.parse_accounts("a@x.com"), {})
        self.assertEqual(D.parse_accounts("a@x.com:;b@x.com:*")["b@x.com"]["admin"], True)

    def test_session_cookie_hides_the_id_and_carries_max_age(self):
        sid = D.session_new("boss@example.com", {"admin": True, "projects": set()})
        c = D.session_cookie(sid, secure=True)
        self.assertNotIn(sid, c, "cookie 里不该出现会话 id 原文")
        self.assertIn(D._token_digest(sid), c)
        age = int(re.search(r"Max-Age=(\d+)", c).group(1))
        self.assertEqual(age, D._session_ttl(), "Max-Age 与配置的有效期对不上")
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

    def test_session_ttl_has_a_floor(self):
        """0 或负数会让「登录成功」和「立刻掉线」同时发生，界面上没有任何提示。"""
        for bad in ("0", "-1", "abc"):
            with mock.patch.dict(os.environ, {"XGEO_SESSION_TTL": bad}, clear=False):
                self.assertGreaterEqual(D._session_ttl(), 60, bad)

    def test_login_hits_do_not_keep_empty_buckets(self):
        """这份字典是进程级全局：只增不删的话，直连暴露的实例能被它撑大。"""
        D.LOGIN_HITS.clear()
        self.assertTrue(D.login_allowed("203.0.113.7"))
        self.assertNotIn("203.0.113.7", D.LOGIN_HITS, "查询不该顺手建键")

    # --------------------------------------------- 打进来：Origin / IPv6 / cookie
    def test_login_from_another_origin_is_rejected(self):
        """跨站登录 CSRF：第三方页面能把受害者登进攻击者的账号，之后他上传的
        东西全落在攻击者名下。Origin 与 Host 不同源必须拒。"""
        status, body, _ = self._req("POST", "/api/auth/login",
                                    body={"credential": "sk-fm-x"},
                                    headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertIn("跨站", json.loads(body)["error"])

    def test_other_loopback_hosts_are_accepted(self):
        """`127.0.0.2` / `127.0.1.1` 是整段 127/8 与本机 hostname（Debian 系
        /etc/hosts 指过去）的形状；用字符串元组比会被判成外站 → 假 403。"""
        for host in ("127.0.0.2", "127.0.1.1"):
            status, body, _ = self._req("GET", "/api/projects", headers={"Host": host})
            self.assertEqual(status, 401, f"{host}: {body}")

    def test_proxied_deploy_shape_is_not_refused(self):
        """★ 本轮引入的回归：仓库自带的 deploy.sh 把看板绑 127.0.0.1，nginx 同机反代
        并传 `Host: <域名>` —— 那时 Host 不是回环地址，一刀切的本机白名单会把**登录页
        本身**403 掉（公网 + 反代正是账号登录要解决的形态）。所以对外主机名要能显式配上。

        判据不能换成「对端是不是回环」：DNS rebinding 的攻击者浏览器也跑在本机。
        """
        host = "xgeo.example.com"
        status, body, _ = self._req("POST", "/api/auth/login",
                                    body={"credential": "sk-fm-x"},
                                    headers={"Host": host, "Origin": f"https://{host}"})
        self.assertEqual(status, 403)
        self.assertIn("XGEO_PUBLIC_HOST", json.loads(body)["error"], "报错要能指路")

        with mock.patch.dict(os.environ, {"XGEO_PUBLIC_HOST": host}, clear=False):
            status, _body, _ = self._req("POST", "/api/auth/login",
                                         body={"credential": "sk-fm-x"},
                                         headers={"Host": host, "Origin": f"https://{host}"})
            self.assertNotEqual(status, 403, "配了对外主机名还是被 Host 校验挡住")
            status, _body, _ = self._req("GET", "/api/projects", headers={"Host": host})
            self.assertEqual(status, 401, "登录页要能打开（401 才是对的）")

    def test_foreign_host_is_refused_when_accounts_only_and_bound_local(self):
        """账号档**不能**无条件跳过 Host 校验：DNS rebinding 能让浏览器同时伪造
        Host 与 Origin，而账号档下攻击者自带合法凭据（令牌档下他拿不到令牌，
        所以跳过 Host 无所谓）。绑了公网地址时另说 —— 那时用户就是从别的机器来的。"""
        status, _body, _ = self._req("POST", "/api/auth/login",
                                     body={"credential": "sk-fm-x"},
                                     headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        with mock.patch.object(D.Handler, "BIND_PUBLIC", True):
            status, _body, _ = self._req("POST", "/api/auth/login",
                                         body={"credential": "sk-fm-x"},
                                         headers={"Host": "evil.example"})
        self.assertNotEqual(status, 403, "绑了公网地址时不该再拿 Host 卡人")

    def test_email_from_me_accepts_the_likely_field_names(self):
        """/me 的响应形状是从线上公开静态文件反推的，没有「里面有 email」的直接
        证据 —— 所以几种可能的字段名都试一遍，全都落空才报「没拿到邮箱」。"""
        for payload in ({"data": {"email": "A@x.com"}},
                        {"data": {"user_email": "a@x.com"}},
                        {"data": {"mail": "a@x.com"}},
                        {"data": {"user_name": "a@x.com"}},
                        {"email": "a@x.com"}):
            self.assertEqual(D.email_from_me(payload), "a@x.com", payload)
        self.assertEqual(D.email_from_me({"data": {"user_name": "阿猫"}}), "",
                         "没有 @ 的值不能当邮箱")
        self.assertEqual(D.email_from_me({"data": {"nickname": "a@x.com"}}), "",
                         "只认约定的字段名，别乱猜")

    def test_ipv6_literal_host_is_same_origin(self):
        """`[::1]:8765` 用 split(":")[0] 会切出 "["，于是同源判定恒不相等 ——
        走 IPv6 访问的实例登录永远 403，报的还是「跨站请求被拒绝」。"""
        status, body, _ = self._req("POST", "/api/auth/login",
                                    body={"credential": "sk-fm-x"},
                                    headers={"Host": f"[::1]:{self.port}",
                                             "Origin": f"http://[::1]:{self.port}"})
        self.assertNotEqual(status, 403, body)
        self.assertNotIn("跨站", json.loads(body).get("error", ""))

    def test_malformed_bodies_are_400_not_dropped_connections(self):
        """未认证可达的两个分支曾把异常抛出 do_POST：socketserver 只打 traceback
        再掐连接，一个字节的响应都不发（登录页的 fetch 直接 reject）。"""
        cases = {
            "非 JSON": {"raw": b"{bad", "headers": {"Content-Type": "application/json"}},
            "JSON 但不是对象": {"raw": b"[1,2]", "headers": {"Content-Type": "application/json"}},
            "Content-Length 不是数字": {"raw": b"", "headers": {"Content-Length": "abc"}},
        }
        for name, kw in cases.items():
            status, body, _ = self._req("POST", "/api/auth/login", **kw)
            self.assertEqual(status, 400, f"{name}: {body}")

    def test_oversized_login_body_is_rejected_without_a_dropped_connection(self):
        """未认证可达的接口不能被推 8MB 的体：一连接一线程，读满再限流等于没限。
        注意 4KB 是**拒绝阈值**而不是读取上限 —— 超限时体仍然被读走（读走是为了
        别让 RST 吞掉这个 400），只是读完就拒。"""
        status, _body, _ = self._req("POST", "/api/auth/login", raw=b"x" * 9000,
                                     headers={"Content-Type": "application/json"})
        self.assertEqual(status, 400)

    def test_legacy_cookie_does_not_shadow_the_session(self):
        """浏览器同 path 下按创建时间升序发：从 geolook 改名过来的浏览器里，
        旧的 glk_auth 排在 xgeo_auth 前面。只取第一个命中的名字会导致
        「登录 200 但之后每个请求都 401」——登录死循环。"""
        sid = D.session_new("boss@example.com", {"admin": True, "projects": set()})
        good = f"{D.AUTH_COOKIE}={D._token_digest(sid)}"
        self.assertEqual(self._req("GET", "/api/projects", cookie=good)[0], 200)
        shadowed = f"{D.LEGACY_COOKIE}=deadbeef; {good}"
        self.assertEqual(self._req("GET", "/api/projects", cookie=shadowed)[0], 200,
                         "旧 cookie 把新会话遮住了")

    def test_local_admin_logs_in_and_survives_the_allowlist_recheck(self):
        """★ 断链兜底：不依赖任何外部服务（fm-auth 挂了、名单配错时它是最后一条路）。
        它的会话不在允许名单里，所以 `_auth` 的每请求回查必须放过它 —— 否则登录
        成功之后第一个请求就 401，表现成「登进去又被弹回登录页」。"""
        with mock.patch.dict(os.environ, {"XGEO_ADMIN_USER": "admin",
                                          "XGEO_ADMIN_PASSWORD": "pw-123"}, clear=False):
            status, body, headers = self._req("POST", "/api/auth/login",
                                              body={"user": "admin", "password": "pw-123"})
            self.assertEqual(status, 200, body)
            self.assertTrue(json.loads(body)["admin"])
            cookie = self._cookie_of(headers)
            self.assertEqual(self._req("GET", "/api/projects", cookie=cookie)[0], 200,
                             "兜底会话被允许名单回查踢掉了")
            me = json.loads(self._req("GET", "/api/auth/me", cookie=cookie)[1])
            self.assertEqual(me["mode"], "account")
            self.assertEqual(me["email"], "admin")
            self.assertTrue(me["admin"])
            # 管理员能看到 /api/keys（兜底账号是管理员，不是租户）
            self.assertEqual(self._req("GET", "/api/keys", cookie=cookie)[0], 200)

    def test_local_admin_works_without_the_accounts_tier(self):
        """兜底账号的存在理由就是账号档那条路不通的时候 —— 所以它必须能不依赖
        XGEO_ACCOUNTS（全新自托管实例、或名单写坏了只留兜底）。"""
        with mock.patch.dict(os.environ, {"XGEO_ACCOUNTS": "", "XGEO_ADMIN_USER": "admin",
                                          "XGEO_ADMIN_PASSWORD": "pw-123"}, clear=False):
            status, body, headers = self._req("POST", "/api/auth/login",
                                              body={"user": "admin", "password": "pw-123"})
            self.assertEqual(status, 200, body)
            self.assertEqual(self._req("GET", "/api/projects",
                                       cookie=self._cookie_of(headers))[0], 200)

    def test_local_admin_can_log_out_without_the_accounts_tier(self):
        """★ 真浏览器在线上逮到的：登出那条路由原来在「没配 XGEO_ACCOUNTS」时直接
        404 —— 而兜底账号恰恰常出现在没有账号档的实例上，于是登出弹错误、页面不刷新
        （用户以为自己登出了，其实没有）。"""
        with mock.patch.dict(os.environ, {"XGEO_ACCOUNTS": "", "XGEO_ADMIN_USER": "admin",
                                          "XGEO_ADMIN_PASSWORD": "pw-123"}, clear=False):
            _s, _b, headers = self._req("POST", "/api/auth/login",
                                       body={"user": "admin", "password": "pw-123"})
            cookie = self._cookie_of(headers)
            self.assertEqual(self._req("GET", "/api/projects", cookie=cookie)[0], 200)
            status, _body, out = self._req("POST", "/api/auth/logout", cookie=cookie)
            self.assertEqual(status, 200, "兜底账号登不出去")
            self.assertIn("Max-Age=0", out.get("Set-Cookie") or "")
            self.assertEqual(self._req("GET", "/api/projects", cookie=cookie)[0], 401)

    def test_local_admin_alone_is_not_an_open_instance(self):
        """★ 只配兜底账号（没令牌、没账号档）时，`_auth` 的「什么都没配 → 放行」早退
        会把实例当成**开放**的 —— 那比不配更糟：人以为配了凭据。测试逮到的第二个洞。"""
        with mock.patch.dict(os.environ, {"XGEO_ACCOUNTS": "", "XGEO_ADMIN_USER": "admin",
                                          "XGEO_ADMIN_PASSWORD": "pw-123"}, clear=False):
            # 四个入参都给全，模拟「令牌/分项目令牌都没配」的形态
            self.assertEqual(self._req("GET", "/api/projects")[0], 401,
                             "只配兜底账号却对所有人敞开")

    def test_local_admin_wrong_password_is_401(self):
        with mock.patch.dict(os.environ, {"XGEO_ADMIN_USER": "admin",
                                          "XGEO_ADMIN_PASSWORD": "pw-123"}, clear=False):
            for wrong in ({"user": "admin", "password": "nope"},
                          {"user": "root", "password": "pw-123"},
                          {"user": "", "password": ""}):
                status, _body, headers = self._req("POST", "/api/auth/login", body=wrong)
                self.assertEqual(status, 401, wrong)
                self.assertIsNone(headers.get("Set-Cookie"), wrong)

    def test_local_admin_is_off_unless_fully_configured(self):
        """两个变量缺一个就等于没配（fail closed）—— 代码里不带任何默认值。"""
        for env in ({"XGEO_ADMIN_USER": "admin", "XGEO_ADMIN_PASSWORD": ""},
                    {"XGEO_ADMIN_USER": "", "XGEO_ADMIN_PASSWORD": "pw"},
                    {"XGEO_ADMIN_USER": "admin", "XGEO_ADMIN_PASSWORD": "  "}):
            with self.subTest(env=env):
                with mock.patch.dict(os.environ, {"XGEO_ACCOUNTS": ""}, clear=False):
                    with mock.patch.dict(os.environ, env, clear=False):
                        self.assertIsNone(D.local_admin(), env)
                        status, _b, _h = self._req("POST", "/api/auth/login",
                                                   body={"user": "admin", "password": "pw"})
                        self.assertNotEqual(status, 200, "没配全却放行了")

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
    code = 200          # 想让它返别的状态码（500/302…）时改这个

    def do_GET(self):
        token = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
        type(self).seen.append(token)
        if type(self).code != 200:
            body = json.dumps({"code": type(self).code}).encode()
            self.send_response(type(self).code)
        elif token == "sk-fm-good":
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
        _FakeMe.code = 200
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

    def _req2(self, first, second):
        """同一条 keep-alive 连接上连发两个请求：(方法, 路径, 头) 各一个。"""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        out = []
        try:
            for method, path, headers in (first, second):
                conn.request(method, path, headers=headers)
                r = conn.getresponse()
                out.append((r.status, r.read(), dict(r.headers)))
            return out
        finally:
            conn.close()

    @staticmethod
    def _cookie_of(headers):
        """从 Set-Cookie 里取 `名=值` 那一段（后面还挂着属性）。"""
        return (headers.get("Set-Cookie") or "").split(";")[0]

    # --- 正路 ---

    def test_session_is_revoked_when_the_account_leaves_the_allowlist(self):
        """会话在建的时候存了一份 admin/projects 快照，但权限要以**当前名单**为准：
        名单的改动不走重启也能发生（`write_env` 会把变量写进 os.environ），
        靠快照等于一次静默的降权失效。"""
        sid = D.session_new("guest@example.com", {"admin": True, "projects": set()})
        cookie = f"{D.AUTH_COOKIE}={D._token_digest(sid)}"
        self.assertEqual(self._req("GET", "/api/projects", cookie=cookie)[0], 200)
        with mock.patch.dict(os.environ, {"XGEO_ACCOUNTS": "boss@example.com:*"}, clear=False):
            self.assertEqual(self._req("GET", "/api/projects", cookie=cookie)[0], 401,
                             "被踢出名单后旧会话还能用")
        self.assertEqual(D.SESSIONS, {}, "回查时该把失效会话删掉，别留着占内存")

    def test_logout_does_not_touch_the_token_tier_cookie(self):
        """两种档共用一个 cookie 名：无条件下发清除会按 name+path 把令牌档的凭据
        一起删掉，等于给双档实例留一个「一发就把别人登出」的入口。"""
        _status, _body, headers = self._req(
            "POST", "/api/auth/logout",
            cookie=f"{D.AUTH_COOKIE}={D._token_digest(self.TOKEN)}")
        self.assertIsNone(headers.get("Set-Cookie"), "没有会话可删却下发了清除 cookie")

    def test_mixed_tier_login_is_not_reachable_through_rebinding(self):
        """★ 混合档（账号 + 令牌）是最常见的形态 —— 扩展的 README 就教人
        「本机要用助手，就同时也配上 XGEO_TOKEN」。而令牌档会短路 Host 校验，
        落在这条路上的登录 CSRF：攻击者页面部署在 evil.example，rebinding 之下
        浏览器发出的 Host 与 Origin **都是** evil.example，同源判定帮不上忙，
        `/api/auth/login` 一成功就下发一个属于攻击者账号的会话 cookie。"""
        status, body, headers = self._req(
            "POST", "/api/auth/login", body={"credential": "sk-fm-good"},
            headers={"Host": "evil.example", "Origin": "https://evil.example"})
        self.assertEqual(status, 403, body)
        self.assertIsNone(headers.get("Set-Cookie"), "rebinding 拿到了会话 cookie")

    def test_login_origin_check_holds_when_bound_public(self):
        """绑了公网地址时 Host 那一层是放开的（运维自己决定的暴露），登录自己的
        同源校验就是唯一防线：不同源的 Origin 必须拒，别下发会话。"""
        with mock.patch.object(D.Handler, "BIND_PUBLIC", True):
            status, _body, headers = self._req(
                "POST", "/api/auth/login", body={"credential": "sk-fm-good"},
                headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertIsNone(headers.get("Set-Cookie"))

    def test_accounts_tier_does_not_break_the_token_tier(self):
        """账号门只在「没有令牌」那一档生效。放在令牌短路之前的话，反代形态
        （仓库自带的 deploy.sh：绑 127.0.0.1 + `Host: <域名>`）下没设 XGEO_PUBLIC_HOST
        会把**整个实例**（含令牌 API）一起 403 掉 —— 从一个形态的问题升级成全站不可用。
        登录那条路由自己守（见 rebinding 那条），防护不缺口。"""
        status, _body, _ = self._req("GET", "/api/projects",
                                     headers={"Host": "xgeo.asia", "X-Xgeo-Token": self.TOKEN})
        self.assertEqual(status, 200, "令牌档被账号档的 Host 门连坐了")

    def test_request_body_is_drained_exactly_once(self):
        """**数调用次数**，而不是看同连接的后续请求 —— 401 那条路本来就会关连接
        （do_POST 的 close_connection），两种实现下「同连接再发」都是断的，
        那样写测不出区别。

        真正要钉的是：读体只能发生一次。读第二次时读到的是**下一个请求**的字节
        （keep-alive 上客户端会照常复用这条连接），而那个请求就此消失。
        """
        calls = []
        orig = D.Handler._drain

        def counting(self):
            calls.append(1)
            return orig(self)

        with mock.patch.object(D.Handler, "_drain", counting):
            status, _body, _ = self._req("POST", "/api/projects", body={"x": 1})
        self.assertEqual(status, 401)
        self.assertEqual(len(calls), 1, "请求体被 drain 了 %d 次" % len(calls))

    def test_auth_service_error_is_503_with_its_code(self):
        """上游非 200/401/403（500、502、302…）都归到「稍后再试」，**不变成放行**。"""
        for code in (500, 302):
            _FakeMe.code = code
            status, body, _ = self._login()
            self.assertEqual(status, 503, f"上游 {code}：{body}")
            self.assertIn(str(code), json.loads(body)["error"])
        _FakeMe.code = 200

    def test_me_reports_admin_and_not_the_project_list(self):
        """admin 有人用了（侧栏按它隐藏管理员入口），projects 没有 —— 要在意的
        项目清单走 /api/projects，那条已经按 _scope 过滤过。"""
        sid = D.session_new(self.EMAIL, {"admin": True, "projects": set()})
        cookie = f"{D.AUTH_COOKIE}={D._token_digest(sid)}"
        me = json.loads(self._req("GET", "/api/auth/me", cookie=cookie)[1])
        self.assertTrue(me["admin"])
        self.assertNotIn("projects", me)

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

    def test_tenant_logs_in_through_the_allowlist_mapping(self):
        """名单 → 权限的映射是这套东西的安全边界，而原来两个类都是直接
        `session_new()` 造会话，**从没走过 /login 的租户路**：把「登录一律给管理员」
        这种改动钉不住。这里从登录开始，一路验到项目隔离。"""
        _FakeMe.payload = {"email": "guest@example.com"}     # 名单里是 beta 的租户
        status, body, headers = self._login()
        self.assertEqual(status, 200, body)
        self.assertFalse(json.loads(body)["admin"], "租户被当成管理员了")
        cookie = self._cookie_of(headers)
        me = json.loads(self._req("GET", "/api/auth/me", cookie=cookie)[1])
        self.assertFalse(me["admin"])
        self.assertEqual(me["mode"], "account")
        self.assertEqual(self._req("GET", "/api/p/beta", cookie=cookie)[0], 200)
        self.assertEqual(self._req("GET", "/api/p/alpha", cookie=cookie)[0], 403)
        self.assertEqual(self._req("GET", "/api/keys", cookie=cookie)[0], 403)
        # 侧栏据此隐藏管理员入口（lib/nav.js 的 ADMIN_ONLY）
        listing = json.loads(self._req("GET", "/api/projects", cookie=cookie)[1])
        self.assertEqual([r["slug"] for r in listing], ["beta"])

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

    def test_rate_limit_bucket_follows_x_real_ip_behind_a_proxy(self):
        """反代下所有用户的对端地址都是 127.0.0.1：按对端分桶会让全站共用
        一个桶，任何人连错 10 次就把所有人（含管理员）挡在登录之外。"""
        for _ in range(10):
            self._login("sk-fm-wrong", headers={"X-Real-IP": "203.0.113.9"})
        hit, body, _ = self._login("sk-fm-good", headers={"X-Real-IP": "203.0.113.9"})
        self.assertEqual(hit, 429, body)
        free, body2, _ = self._login("sk-fm-good", headers={"X-Real-IP": "198.51.100.4"})
        self.assertNotEqual(free, 429, f"另一个来源被连坐了：{body2}")

    def test_keep_alive_does_not_carry_the_previous_identity(self):
        """Handler 实例在 keep-alive 上是复用的：_email 只在账号分支赋值，
        不重置就会把上一个请求的邮箱带进 /api/auth/me。"""
        sid = D.session_new(self.EMAIL, {"admin": True, "projects": set()})
        cookie = f"{D.AUTH_COOKIE}={D._token_digest(sid)}"
        (s1, b1, _), (s2, b2, _) = self._req2(
            ("GET", "/api/auth/me", {"Cookie": cookie}),
            ("GET", "/api/auth/me", {"X-Xgeo-Token": self.TOKEN}))
        self.assertEqual(json.loads(b1)["mode"], "account")
        self.assertEqual(json.loads(b1)["email"], self.EMAIL)
        self.assertEqual(json.loads(b2)["mode"], "token")
        self.assertEqual(json.loads(b2)["email"], "", "上一个请求的身份漏过来了")

    def test_logout_is_not_available_without_the_accounts_tier(self):
        """它清的是 AUTH_COOKIE，而令牌档的凭据正是同一个 cookie 名 ——
        无条件下发清除就等于给令牌档加了个「任何人一发就把别人登出」的入口。"""
        with mock.patch.dict(os.environ, {"XGEO_ACCOUNTS": ""}, clear=False):
            status, _body, headers = self._req("POST", "/api/auth/logout")
        self.assertEqual(status, 404)
        self.assertIsNone(headers.get("Set-Cookie"))

    def test_logout_from_another_origin_is_rejected(self):
        status, _body, _ = self._req("POST", "/api/auth/logout",
                                     headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)

    def test_account_session_cannot_reach_admin_routes_when_tenant(self):
        """会话是「另一个身份来源」，不是「另一个权限层」——照样受 _deny 管。"""
        sid = D.session_new("guest@example.com", {"admin": False, "projects": {"beta"}})
        cookie = f"{D.AUTH_COOKIE}={D._token_digest(sid)}"
        self.assertEqual(self._req("GET", "/api/p/beta", cookie=cookie)[0], 200)
        self.assertEqual(self._req("GET", "/api/p/alpha", cookie=cookie)[0], 403)
