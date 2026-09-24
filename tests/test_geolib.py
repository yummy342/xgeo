import json, re, tempfile, time, unittest
from pathlib import Path
from unittest import mock
import sys; sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import geolib as G

class TestJsonIO(unittest.TestCase):
    def test_write_json_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            G.write_json(p, {"a": 1})
            self.assertEqual(G.read_json(p), {"a": 1})
            self.assertFalse(list(Path(d).glob("*.tmp")))

    def test_temp_name_is_not_shared_between_writes(self):
        """临时文件名必须逐次唯一。

        用 pid 拼临时名的话，同一进程里两个线程写同一个文件会写进同一个临时文件：
        一个先 os.replace 走，另一个 replace 时临时文件已经不存在了，内容直接丢。"""
        names = set()
        real = G.os.replace

        def spy(src, dst):
            names.add(Path(src).name)
            return real(src, dst)

        with tempfile.TemporaryDirectory() as d, mock.patch.object(G.os, "replace", spy):
            p = Path(d) / "x.json"
            G.write_json(p, {"a": 1})
            G.write_json(p, {"a": 2})
        self.assertEqual(len(names), 2, f"两次写的临时文件名撞了：{names}")

    def test_write_jsonl_keeps_old_content_when_interrupted(self):
        """写一半崩掉不能把原文件毁掉——样本 jsonl 是一期采样的唯一记录。"""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            G.write_jsonl(p, [{"a": 1}])
            with mock.patch.object(G.json, "dumps", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    G.write_jsonl(p, [{"a": 2}])
            self.assertEqual(G.read_jsonl(p), [{"a": 1}], "中断把旧内容覆盖了")
            self.assertEqual(list(Path(d).glob("*.tmp")), [], "留下了临时文件")

    def test_save_config_is_atomic_and_backs_up(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(G, "WORK", Path(d)):
            G.save_config("atomic", {"brand": {"name": "第一版"}})
            G.save_config("atomic", {"brand": {"name": "第二版"}})
            self.assertEqual(G.load_config("atomic")["brand"]["name"], "第二版")
            self.assertEqual(list((Path(d) / "atomic").glob("*.tmp")), [])
            baks = list((Path(d) / "atomic" / ".geo.bak").glob("geo-*.json"))
            self.assertTrue(baks, "覆盖前没留备份")
            self.assertEqual(json.loads(baks[0].read_text("utf-8"))["brand"]["name"], "第一版")

    def test_strip_comments_matches_the_regex_semantics(self):
        cases = ["a<!--x-->b", "a<!--x-->b<!--y-->c", "a<!--unclosed", "<!--a-->b<!--c",
                 "no comments", "<!--\n跨行\n-->tail", "<!--a--><!--b-->", "--><!---->"]
        for src in cases:
            self.assertEqual(G.strip_comments(src),
                             re.sub(r"<!--.*?-->", "", src, flags=re.S), src)

    def test_strip_comments_is_linear_on_unclosed_comments(self):
        """塞满 `<!--` 而结尾没有 `-->` 时，正则那版每个起点都要扫到末尾才收工，
        5000 个就是 0.3 秒、20000 个 12 秒——预检接口吃的正是用户粘贴的正文，
        一条请求就能把服务拖住。这版是线性扫描，同样的输入不到 1 毫秒。"""
        src = "<!--" * 20000          # 80KB，一篇长文的量级
        t0 = time.perf_counter()
        G.strip_comments(src)
        self.assertLess(time.perf_counter() - t0, 2.0)

    def test_read_jsonl_skips_a_truncated_line(self):
        """进程被杀会在末尾留下半行。一行坏不该让整期体检中断。"""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text('{"a": 1}\n{"b": 2}\n{"c": ', "utf-8")
            self.assertEqual(G.read_jsonl(p), [{"a": 1}, {"b": 2}])

    def test_read_jsonl_skips_a_corrupt_middle_line(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text('{"a": 1}\n\nnot json at all\n{"b": 2}\n', "utf-8")
            self.assertEqual(G.read_jsonl(p), [{"a": 1}, {"b": 2}])

    def test_read_json_corrupt_returns_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text("{broken", "utf-8")
            self.assertEqual(G.read_json(p, default={}), {})

    def test_project_dir_rejects_traversal(self):
        for bad in ("../x", "/etc", "a/b", ".."):
            with self.assertRaises(SystemExit):
                G.project_dir(bad)

    def test_project_dir_accepts_valid_slug(self):
        self.assertEqual(G.project_dir("aigclink"), G.WORK / "aigclink")

    def test_read_json_missing_returns_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "nope.json"
            self.assertEqual(G.read_json(p, default={"x": 1}), {"x": 1})
            self.assertIsNone(G.read_json(p))

    def test_main_text_single_article_stays_focused(self):
        soup = G.parse_html(
            "<main><nav>menu</nav><article>the post body</article></main>")
        self.assertEqual(G.main_text(soup), "the post body")

    def test_main_text_multiple_articles_takes_whole_main(self):
        soup = G.parse_html(
            "<main><article>intro section</article>"
            "<article>steps: 1 2 3</article>"
            "<article>faq answers</article></main>")
        text = G.main_text(soup)
        for piece in ("intro section", "steps: 1 2 3", "faq answers"):
            self.assertIn(piece, text)

    def test_jsonl_roundtrip_with_unicode_line_separators(self):
        """正文含 U+2028/U+2029/U+0085 时 JSONL 必须仍能读回。

        json.dumps 不转义这些字符，而 str.splitlines() 会在它们处断行，
        导致一条记录被劈成两半。真实触发场景：抓取的网页正文里带 U+2028。
        """
        rows = [
            {"url": "https://a.example/1", "text": "line one\u2028line two"},
            {"url": "https://a.example/2", "text": "para\u2029break"},
            {"url": "https://a.example/3", "text": "next\u0085line"},
            {"url": "https://a.example/4", "text": "vert\u000btab and form\u000cfeed"},
            {"url": "https://a.example/5", "text": "plain"},
        ]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pages.jsonl"
            G.write_jsonl(p, rows)
            # 前提确认：这些字符确实原样落盘了，否则本测试没有鉴别力
            self.assertIn("\u2028", p.read_text("utf-8"))
            self.assertEqual(G.read_jsonl(p), rows)

    def test_project_lock_enter_exit(self):
        with tempfile.TemporaryDirectory() as d:
            slug = "locktest"
            orig_work = G.WORK
            G.WORK = Path(d)
            try:
                with G.project_lock(slug):
                    self.assertTrue((Path(d) / slug / ".lock").exists())
                self.assertTrue((Path(d) / slug / ".lock").exists())
            finally:
                G.WORK = orig_work

class TestNoSiteMode(unittest.TestCase):
    """无自有网站项目（电商商品/线下品牌/小程序）的判定与降级。"""

    def test_has_site(self):
        self.assertTrue(G.has_site({"brand": {"site": "https://a.com"}}))
        for empty in ({"brand": {"site": ""}}, {"brand": {"site": "   "}}, {"brand": {}}, {}):
            self.assertFalse(G.has_site(empty), empty)

    def test_no_site_metrics_are_none_not_zero(self):
        """无站点时「引用官网率」必须是 None（不适用），绝不能退化成 0——
        0 会被读成「一次都没被引用」，那是编数。"""
        import sample as S
        cfg = {"brand": {"name": "商品", "site": "", "aliases": []}, "competitors": [],
               "questions": [{"id": "q001", "text": "有哪些好用的绿茶", "group": "推荐"}]}
        rows = [{"platform": "deepseek", "market": "cn", "question_id": "q001",
                 "question": "有哪些好用的绿茶", "ok": True,
                 "analysis": {"brand_mentioned": False, "brand_rank": 0, "candidates": [],
                              "competitors_mentioned": [], "cited_domains": ["x.com"],
                              "own_domain_cited": False, "answer_chars": 100}}]
        agg = S.aggregate(rows, cfg)
        self.assertIsNone(agg["deepseek"]["own_domain_cite_rate"])
        self.assertEqual(agg["deepseek"]["mention_rate"], 0.0)   # 提及率照常可测

    def test_no_site_generates_no_site_tickets(self):
        import tasks as T
        cfg = {"brand": {"name": "商品", "site": ""}, "market": "cn"}
        self.assertEqual(T.from_audit({"no_site": True}, cfg, iter(["T-001"])), [])


if __name__ == "__main__":
    # 必须放在文件末尾：写在中间的话，单跑本文件时 unittest.main() 会在后面那些
    # 类定义之前收集用例 —— 它们静默不执行，而输出照样是 OK。
    unittest.main()
