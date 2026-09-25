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

    def test_tags_actually_capped_in_the_payload(self):
        """断言落在组装结果上，不是把注册表常量抄一遍 —— 抄一遍的断言永远红不了。

        fixture 的 keywords 有 6 项，CSDN 上限 5，所以出来的标签必须正好 5 个。
        """
        spec = P.semi_spec("csdn", SLUG)
        r = P.prepare(SLUG, "csdn", "content/a.md")
        self.assertEqual(len(r["tags_text"].split(",")), spec["tags"]["max"])

    def test_weibo_has_no_title_field(self):
        spec = P.semi_spec("weibo", SLUG)
        self.assertTrue(spec["title_inline"])
        self.assertEqual(spec["api"]["status"], "blocked")


class TestPrepare(Base):
    def test_prepare_makes_no_request(self):
        """备好这条链不许有任何外发请求 —— 这是它与「自动发布」的分界。

        把整个 requests 换成「取任何属性都炸」的桩，而不是只 patch get/post：
        只 patch 三个方法时，将来接上只走 `requests.put`（或 Session、httpx）的实现
        照样溜过去，这条测试就成了摆设。
        """
        class _NoNet:
            def __getattr__(self, name):
                raise AssertionError(f"备好不许发请求，却碰了 requests.{name}")

        with mock.patch.object(P, "requests", _NoNet()):
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

    def test_title_inline_channel_does_not_repeat_the_headline(self):
        """微博这类把标题并进正文首行，而正文首行往往就是同一个 H1 —— 摘掉它。

        不摘的话每次备好都是「标题 / 标题 / 正文」（md2text 只去掉 # 号、文字留着）。
        上一版测试抓到不这个，因为它传的 title 与文章 H1 不同字。
        """
        r = P.prepare(SLUG, "weibo", "content/a.md")     # 不传 title，走 _title_of 取 H1
        self.assertEqual(r["title"], "一个标题")
        head_lines = [l for l in r["body"].split("\n") if l.strip() == "一个标题"]
        self.assertEqual(len(head_lines), 1, r["body"][:120])

    def test_force_semi_works_on_a_credentialed_channel(self):
        """--via semi 打在凭证齐的双路渠道上要真的备好，而不是回一句「用自动通路」。

        之前 force 没往下传，prepare 按默认（凭证齐 → api）再判一次就拒了 ——
        拒的理由还是让用户去执行他刚敲的那条命令。
        """
        env = {"REDDIT_CLIENT_ID": "a", "REDDIT_CLIENT_SECRET": "b",
               "REDDIT_USERNAME": "c", "REDDIT_PASSWORD": "d"}
        cfg = json.loads((self.pdir / "geo.json").read_text("utf-8"))
        cfg["publishing"]["reddit"] = {"subreddit": "LocalLLaMA"}
        (self.pdir / "geo.json").write_text(json.dumps(cfg, ensure_ascii=False), "utf-8")
        with mock.patch.dict("os.environ", env):
            self.assertEqual(P.resolve_path("reddit", SLUG), "api")
            r = P.prepare(SLUG, "reddit", "content/a.md", force="semi")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["mode"], "semi")

    def test_path_is_normalized_for_idempotency(self):
        """`content//a.md` 与 `content/a.md` 是同一个文件，不该备出两条待办。"""
        a = P.prepare(SLUG, "sohu", "content/a.md")
        b = P.prepare(SLUG, "sohu", "content//./a.md")
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(len(self.records()), 1)

    def test_non_string_platform_is_rejected_not_crashed(self):
        """body 里塞 dict/list 不能把 500 抛出去（不可哈希 → TypeError）。"""
        self.assertFalse(P.prepare(SLUG, {"a": 1}, "content/a.md")["ok"])
        self.assertFalse(P.record_manual(SLUG, ["sohu"], "content/a.md", "x",
                                        url="https://a.test/")["ok"])

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

    def test_refill_rejects_a_non_http_url(self):
        """回填的链接会渲染成可点链接、还会被当回链 —— 只收 http(s)。

        存进去一个 `javascript:` 等于在别人的待发布清单里放了个可点的脚本；
        渲染侧有守卫，但入口这里也要挡一道（守卫守的是渲染，不是数据）。
        """
        r = P.prepare(SLUG, "sohu", "content/a.md")
        m = P.record_manual(SLUG, "sohu", "content/a.md", r["id"], url="javascript:alert(1)")
        self.assertFalse(m["ok"])
        self.assertIn("http", m["error"])
        self.assertEqual(self.records()[-1]["state"], P.SEMI_STATE, "被拒之后仍该是待回填")

    def test_refill_accepts_http_and_https(self):
        for u in ("http://a.test/x", "https://a.test/x"):
            with self.subTest(u=u):
                r = P.prepare(SLUG, "zhihu", "content/a.md")
                m = P.record_manual(SLUG, "zhihu", "content/a.md", r["id"], url=u)
                self.assertTrue(m["ok"], m)

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


class TestLinkableAndPaths(unittest.TestCase):
    """两处边界：协议相对地址不能被当成「站内相对路径」；每个渠道至少要有一条路。"""

    def test_protocol_relative_is_not_linkable(self):
        """`//evil.com/x` 以 `/` 开头，但浏览器会去外站 —— 注释写的是「只认站内
        相对路径」，那就得把这一支也挡掉（原来放行）。"""
        self.assertFalse(P._linkable("//evil.com/x"))
        self.assertTrue(P._linkable("/a/b"))
        self.assertTrue(P._linkable("https://a.test/b"))
        self.assertFalse(P._linkable("javascript:alert(1)"))
        self.assertNotIn('href="//evil.com', P.md2html("[a](//evil.com)"))

    def test_every_channel_has_at_least_one_path(self):
        """`paths_of` 为空 = 这个渠道既不能自动发、也不能半自动备好 —— 前端会把它
        渲染成「Automatic + Ready」（`path=''` 的判据只看 missing 为空），静默装成可用。"""
        for code in P.PUBLISHERS:
            with self.subTest(code=code):
                self.assertTrue(P.paths_of(code), f"{code} 一条通路都没有")

    def test_tbd_body_form_is_normalised(self):
        """"tbd 按 text 处理" 是规格里写明的，那就别把内部占位符送到界面上
        （用户会在「正文 · tbd」里看到它）。"""
        payload = P._prepare_payload("smzdm", P.PUBLISHERS["smzdm"]["semi"],
                                     chr(10).join(["# 标题", "", "正文"]),
                                     "标题", "content/a.md", {}, [], {})
        self.assertNotEqual(payload["body_form"], "tbd")


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


class TestHtmlSafety(unittest.TestCase):
    """md2html 的产物会被前端 {@html} 渲染，也会发到 WordPress/公众号/webhook。

    所以「链接目标认不认 scheme」是安全边界，不是格式偏好：
    `content/*.md` 能经 `POST /api/content/` 写入，转义只挡得住「拼出属性」。
    """

    def test_javascript_link_is_not_emitted_as_a_link(self):
        out = P.md2html("点[这里](javascript:alert(1))看看")
        self.assertNotIn("<a href", out)
        self.assertIn("这里", out, "信息别丢：退化成纯文本")

    def test_percent_encoded_javascript_link_is_also_refused(self):
        """Chromium 执行前会解码，所以百分号编码不是绕过口。"""
        out = P.md2html("[x](javascript:fetch%28%27//evil/%27%29)")
        self.assertNotIn("<a href", out)

    def test_data_uri_is_refused(self):
        self.assertNotIn("<a href", P.md2html("[x](data:text/html,<script>1</script>)"))

    def test_http_and_relative_links_still_work(self):
        self.assertIn('<a href="https://a.test/x">t</a>', P.md2html("[t](https://a.test/x)"))
        self.assertIn('<a href="/docs/">d</a>', P.md2html("[d](/docs/)"))

    def test_backlink_is_escaped_in_the_prepared_body(self):
        """回链来自 cfg.link_url（界面可填）或渠道响应 url —— 不转义就是免点击 XSS。

        走 html 型渠道（sohu/头条/百家号/公众号）时它会直接进 {@html} 渲染的正文。
        """
        with tempfile.TemporaryDirectory() as tmp:
            pdir = Path(tmp) / SLUG
            (pdir / "content").mkdir(parents=True)
            local = json.loads(json.dumps(CFG))
            local["publishing"] = {"sohu": {"link_url": '<img src=x onerror="alert(1)">'}}
            (pdir / "geo.json").write_text(json.dumps(local, ensure_ascii=False), "utf-8")
            (pdir / "content" / "a.md").write_text(ARTICLE, "utf-8")
            old = G.WORK
            G.WORK = Path(tmp)
            try:
                r = P.prepare(SLUG, "sohu", "content/a.md")
            finally:
                G.WORK = old
        self.assertNotIn("<img", r["body"], "回链里的标签必须被转义")
        self.assertIn("&lt;img", r["body"])


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
