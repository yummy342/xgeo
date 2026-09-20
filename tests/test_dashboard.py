import http.client
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
        self.assertTrue(D.auth_ok(None, None))
        self.assertTrue(D.auth_ok("", "anything=1"))

    def test_query_token_matches(self):
        self.assertTrue(D.auth_ok(self.TOKEN, None, query_token=self.TOKEN))

    def test_header_token_matches(self):
        self.assertTrue(D.auth_ok(self.TOKEN, None, header_token=self.TOKEN))

    def test_cookie_digest_matches(self):
        cookie = f"other=1; {D.AUTH_COOKIE}={D._token_digest(self.TOKEN)}"
        self.assertTrue(D.auth_ok(self.TOKEN, cookie))

    def test_wrong_credentials_rejected(self):
        self.assertFalse(D.auth_ok(self.TOKEN, None))
        self.assertFalse(D.auth_ok(self.TOKEN, None, query_token="wrong"))
        self.assertFalse(D.auth_ok(self.TOKEN, f"{D.AUTH_COOKIE}=deadbeef"))
        # cookie 里放原始令牌不行——cookie 存的是摘要
        self.assertFalse(D.auth_ok(self.TOKEN, f"{D.AUTH_COOKIE}={self.TOKEN}"))


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
