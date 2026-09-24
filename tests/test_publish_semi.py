"""半自动通路：备好、幂等、回填、作废。

背景：半自动渠道（Reddit/搜狐/头条/知乎/CSDN/百家号/微博/什么值得买）没有可用的
自动发布通路，工具只做「备好内容 + 一键复制 + 打开发布页」，发布由账号主人点。
这条链**不发任何外发请求** —— 所以本文件最重要的一条断言是 `test_prepare_makes_no_request`。

另一条口径：半自动从不写「已发布」。它先写 state=prepared，回填 URL 之后才转
published —— 否则就会重演 dev.to 那次「草稿被当已发布」（见 test_publish_state.py）。
"""

import itertools
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import geolib as G        # noqa: E402
import publish as P       # noqa: E402

SLUG = "t-semi"
CFG = {
    "slug": SLUG, "market": "cn",
    "brand": {"name": "Example", "site": "https://example.test", "aliases": [], "products": []},
    "keywords": ["api 网关", "多模型", "免费额度", "故障切换", "对比", "第六个"],
    "publishing": {"reddit": {"subreddit": ""}, "toutiao": {}},
}
ARTICLE = """# 一个标题

正文第一段，带 **加粗** 与 [链接](https://example.test/a)。

## 小节

- 要点一
- 要点二

| 列 | 值 |
|---|---|
| a | 1 |

```py
print("x")
```

<!-- 目标问题 q007 -->
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pdir = Path(self.tmp.name) / SLUG
        (self.pdir / "content").mkdir(parents=True)
        (self.pdir / "geo.json").write_text(json.dumps(CFG, ensure_ascii=False), "utf-8")
        (self.pdir / "content" / "a.md").write_text(ARTICLE, "utf-8")
        self._work = G.WORK
        G.WORK = Path(self.tmp.name)
        self.addCleanup(self._restore)

    def _restore(self):
        G.WORK = self._work
        self.tmp.cleanup()

    def records(self) -> list:
        return json.loads((self.pdir / "publish.json").read_text("utf-8"))


class TestPathResolution(Base):
    def test_semi_only_channel_is_semi(self):
        self.assertEqual(P.paths_of("toutiao"), ["semi"])
        self.assertEqual(P.resolve_path("toutiao", SLUG), "semi")

    def test_api_only_channel_is_api(self):
        with mock.patch.dict("os.environ", {"GITHUB_TOKEN": "x"}):
            self.assertEqual(P.paths_of("github"), ["api"])
            self.assertEqual(P.resolve_path("github", SLUG), "api")

    def test_dual_channel_falls_back_to_semi_without_credentials(self):
        """Reddit 两条路都有：没凭证就该落半自动，而不是报「缺凭证」了事。"""
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(P.paths_of("reddit"), ["api", "semi"])
            self.assertEqual(P.resolve_path("reddit", SLUG), "semi")

    def test_dual_channel_uses_api_when_credentials_and_cfg_are_there(self):
        env = {"REDDIT_CLIENT_ID": "a", "REDDIT_CLIENT_SECRET": "b",
               "REDDIT_USERNAME": "c", "REDDIT_PASSWORD": "d"}
        cfg = json.loads((self.pdir / "geo.json").read_text("utf-8"))
        cfg["publishing"]["reddit"] = {"subreddit": "LocalLLaMA"}
        (self.pdir / "geo.json").write_text(json.dumps(cfg, ensure_ascii=False), "utf-8")
        with mock.patch.dict("os.environ", env):
            self.assertEqual(P.resolve_path("reddit", SLUG), "api")

    def test_force_overrides(self):
        """force 是给界面「改用手动」用的：凭证明明齐，也要能强制走半自动。"""
        env = {"REDDIT_CLIENT_ID": "a", "REDDIT_CLIENT_SECRET": "b",
               "REDDIT_USERNAME": "c", "REDDIT_PASSWORD": "d"}
        with mock.patch.dict("os.environ", env):
            self.assertEqual(P.resolve_path("reddit", SLUG, force="semi"), "semi")
            self.assertEqual(P.resolve_path("reddit", SLUG, force="api"), "api")


class TestSpec(Base):
    def test_placeholder_unfilled_falls_back_to_generic_page(self):
        spec = P.semi_spec("reddit", SLUG)
        self.assertEqual(spec["missing_placeholders"], ["subreddit"])
        self.assertEqual(spec["publish_url"], "https://www.reddit.com/submit")

    def test_tags_capped_by_channel_max(self):
        spec = P.semi_spec("csdn", SLUG)
        self.assertEqual(spec["tags"]["max"], 5)

    def test_weibo_has_no_title_field(self):
        spec = P.semi_spec("weibo", SLUG)
        self.assertTrue(spec["title_inline"])
        self.assertEqual(spec["api"]["status"], "blocked")


class TestPrepare(Base):
    def test_prepare_makes_no_request(self):
        """备好这条链不许有任何外发请求 —— 这是它与「自动发布」的分界。"""
        with mock.patch.object(P.requests, "request", side_effect=AssertionError("不该发请求")), \
                mock.patch.object(P.requests, "get", side_effect=AssertionError("不该发请求")), \
                mock.patch.object(P.requests, "post", side_effect=AssertionError("不该发请求")):
            r = P.prepare(SLUG, "toutiao", "content/a.md")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["mode"], "semi")

    def test_record_is_prepared_not_published(self):
        r = P.prepare(SLUG, "toutiao", "content/a.md")
        rec = self.records()[-1]
        self.assertEqual(rec["state"], P.SEMI_STATE)
        self.assertEqual(rec["url"], "")
        self.assertEqual(rec["id"], r["id"])

    def test_prepare_is_idempotent(self):
        """反复点「备好」不该刷出一串待办。"""
        a = P.prepare(SLUG, "toutiao", "content/a.md")
        b = P.prepare(SLUG, "toutiao", "content/a.md")
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(len(self.records()), 1)

    def test_title_truncated_to_channel_limit(self):
        r = P.prepare(SLUG, "toutiao", "content/a.md", title="标" * 40)
        self.assertEqual(len(r["title"]), 30)
        self.assertTrue(any("已截断" in w for w in r["warnings"]))

    def test_weibo_puts_title_into_body(self):
        r = P.prepare(SLUG, "weibo", "content/a.md", title="标题在这")
        self.assertTrue(r["body"].startswith("标题在这"))
        self.assertTrue(r["tags_text"].startswith("#"), "微博话题要 # 包起来")

    def test_api_channel_refuses_to_prepare(self):
        with mock.patch.dict("os.environ", {"GITHUB_TOKEN": "x"}):
            r = P.prepare(SLUG, "github", "content/a.md")
        self.assertFalse(r["ok"])
        self.assertIn("自动发布通路", r["error"])

    def test_unknown_channel(self):
        self.assertFalse(P.prepare(SLUG, "nope", "content/a.md")["ok"])

    def test_path_traversal_still_blocked(self):
        r = P.prepare(SLUG, "toutiao", "../../etc/passwd")
        self.assertFalse(r["ok"])


class TestRefill(Base):
    def test_refill_marks_published_with_url(self):
        r = P.prepare(SLUG, "toutiao", "content/a.md")
        m = P.record_manual(SLUG, "toutiao", "content/a.md", r["id"],
                            url="https://www.toutiao.com/a123/")
        self.assertTrue(m["ok"], m)
        rec = self.records()[-1]
        self.assertEqual(rec["state"], "published")
        self.assertEqual(rec["url"], "https://www.toutiao.com/a123/")

    def test_refill_requires_a_url(self):
        r = P.prepare(SLUG, "toutiao", "content/a.md")
        self.assertFalse(P.record_manual(SLUG, "toutiao", "content/a.md", r["id"])["ok"])

    def test_refill_ticks_the_distribution_list(self):
        """回填顺带勾分发清单：原来那是另一条没有 URL 的人工链，两条并成一条。"""
        r = P.prepare(SLUG, "toutiao", "content/a.md")
        m = P.record_manual(SLUG, "toutiao", "content/a.md", r["id"],
                            url="https://www.toutiao.com/a123/")
        self.assertEqual(m["dist_ticked"], ["q007"])
        dist = json.loads((self.pdir / "distribution.json").read_text("utf-8"))
        self.assertIn("toutiao", dist["q007"])

    def test_cancel_removes_the_pending_record(self):
        r = P.prepare(SLUG, "sohu", "content/a.md")
        self.assertTrue(P.record_manual(SLUG, "sohu", "content/a.md", r["id"], cancel=True)["ok"])
        self.assertEqual(self.records(), [])

    def test_unknown_id_is_reported(self):
        self.assertFalse(P.record_manual(SLUG, "sohu", "content/a.md", "deadbeef",
                                        url="https://x.test/")["ok"])


class TestMd2Text(unittest.TestCase):
    def test_degrades_markdown_to_plain(self):
        out = P.md2text("# 标题\n\n**粗** 与 [文字](https://a.test/x)\n\n- 要点")
        self.assertNotIn("#", out)
        self.assertNotIn("**", out)
        self.assertIn("粗", out)
        self.assertIn("https://a.test/x", out)
        self.assertIn("· 要点", out)

    def test_code_fence_content_is_kept_indented(self):
        out = P.md2text("```py\nprint(1)\n```")
        self.assertIn("print(1)", out)
        self.assertNotIn("```", out)


class TestStateRegistry(unittest.TestCase):
    def test_semi_only_channels_default_to_draft(self):
        """**只有**半自动一条路的渠道不许默认 published —— 把这条写进测试，不是写进注释。

        双路渠道（Reddit/公众号）不在此列：它们走 API 时确实直接公开，
        DEFAULT_STATE 描述的是 API 那条路的结果，而半自动从不调用 _state_of。
        """
        checked = []
        for code, meta in P.PUBLISHERS.items():
            if meta.get("semi") and code not in P._IMPL:
                self.assertEqual(P.DEFAULT_STATE.get(code), "draft", code)
                checked.append(code)
        self.assertTrue(checked, "半自动渠道一个都没匹配上，测试失效了")


if __name__ == "__main__":
    unittest.main()
