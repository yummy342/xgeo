"""数据完整性：全量审查里那些「会静默丢数据/静默改行为」的修复。

这一组不测业务语义，只钉住几条**不许静默发生**的事：
  · 写接口缺 text 键不能把文件清空（facts.md / content / assets 都没有备份）
  · `save_config` 拒写残缺配置（缺 brand 就是「把项目写残」，而不是报错）
  · `/api/config` 的局部 body 不能把 brand 整块洗掉（site 一没，项目就变成「无网站」）
  · jsonl 重写要把读不出来的行带回去（否则下一次读-改-写就永久删了它）
  · slug 校验用 fullmatch（`$` 会放行行尾换行）、Windows 保留名要挡
"""
import http.client
import io
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import dashboard as D
import geolib as G

for _k in ("XGEO_TOKEN", "XGEO_PROJECT_TOKENS", "XGEO_ACCOUNTS", "XGEO_AUTH_BASE",
           "XGEO_ADMIN_USER", "XGEO_ADMIN_PASSWORD", "XGEO_PUBLIC_HOST",
           "XGEO_TRUST_PROXY", "XGEO_SESSION_TTL"):
    os.environ.pop(_k, None)


CFG = {"brand": {"name": "示例品牌", "site": "https://a.test", "aliases": ["示例"]},
       "market": "cn", "questions": []}


class TestSlugAndJsonl(unittest.TestCase):
    def test_slug_rejects_trailing_newline_and_reserved_names(self):
        self.assertFalse(G.slug_ok("abc\n"), "`$` 放行了行尾换行 —— 目录名会真的带换行")
        self.assertFalse(G.slug_ok("nul"))
        self.assertFalse(G.slug_ok("con"))
        self.assertTrue(G.slug_ok("aiglade-cn"))
        self.assertTrue(G.slug_ok("屋瓴知"))

    def test_rewrite_jsonl_keeps_unreadable_lines(self):
        """读不出来的行必须在重写时带回去：`write_jsonl(p, read_jsonl(p) + rows)`
        这个形状会把它永久删掉，而 samples/*.jsonl 没有 geo.json 那样的备份。"""
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "s.jsonl"
            p.write_text("\n".join([json.dumps({"a": 1}), "{半行", json.dumps({"b": 2})]), "utf-8")
            G.rewrite_jsonl(p, [{"a": 1}, {"c": 3}])
            text = p.read_text("utf-8")
            self.assertIn("{半行", text, "坏行被吞了")
            lines = [l for l in text.strip().split("\n") if l.strip()]
            self.assertEqual(len(lines), 3, "2 条好行 + 1 条坏行")


class TestWriteGuards(unittest.TestCase):
    """起一个真服务打几个写接口 —— 这几条修的都是「回 ok 但把数据弄没了」。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = TemporaryDirectory()
        work = Path(cls.tmp.name) / "work"
        (work / "proj" / "content").mkdir(parents=True)
        (work / "proj" / "assets").mkdir(parents=True)
        (work / "proj" / "geo.json").write_text(json.dumps(CFG, ensure_ascii=False), "utf-8")
        (work / "proj" / "content" / "facts.md").write_text("人工写的事实，共 20 字节左右", "utf-8")
        cls.work = work
        cls.patches = [mock.patch.object(D.G, "WORK", work),
                       mock.patch.object(D.Handler, "TOKEN", None),
                       mock.patch.object(D.Handler, "SCOPES", {})]
        for p in cls.patches:
            p.start()
        cls.srv = D.ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        for p in cls.patches:
            p.stop()
        cls.tmp.cleanup()

    def _post(self, path, body):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            payload = json.dumps(body).encode("utf-8")
            conn.request("POST", path, body=payload,
                         headers={"Content-Type": "application/json"})
            r = conn.getresponse()
            return r.status, r.read()
        finally:
            conn.close()

    def _facts(self):
        return (self.work / "proj" / "content" / "facts.md").read_text("utf-8")

    def test_empty_body_does_not_wipe_facts(self):
        before = self._facts()
        status, _body = self._post("/api/facts/proj", {})
        self.assertEqual(status, 400, "缺 text 却回 ok —— facts.md 会被清成 0 字节")
        self.assertEqual(self._facts(), before, "文件被改了")

    def test_empty_body_does_not_wipe_an_asset(self):
        target = self.work / "proj" / "assets" / "snip.html"
        target.write_text("<b>人工写的片段</b>", "utf-8")
        status, _b = self._post("/api/asset/proj", {"path": "snip.html"})
        self.assertEqual(status, 400)
        self.assertEqual(target.read_text("utf-8"), "<b>人工写的片段</b>")

    def test_partial_brand_body_keeps_the_site(self):
        status, _b = self._post("/api/config/proj", {"brand": {"name": "改了名字"}})
        self.assertEqual(status, 200)
        cfg = json.loads((self.work / "proj" / "geo.json").read_text("utf-8"))
        self.assertEqual(cfg["brand"]["name"], "改了名字")
        self.assertEqual(cfg["brand"]["site"], "https://a.test",
                         "brand 被整块替换了 —— 项目会静默变成「无自有网站」")
        self.assertEqual(cfg["brand"]["aliases"], ["示例"])

    def test_save_config_refuses_a_brandless_config(self):
        with self.assertRaises(ValueError):
            G.save_config("proj", {"questions": []})
        # 好配置照写
        G.save_config("proj", dict(CFG))
        self.assertEqual(json.loads((self.work / "proj" / "geo.json").read_text("utf-8"))
                         ["brand"]["name"], "示例品牌")
