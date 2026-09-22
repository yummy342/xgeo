import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import sample as S

CFG = {
    "brand": {"name": "AIGCLINK定制家", "aliases": ["定制家"], "site": "https://aigclink.example.com"},
    "competitors": [{"name": "竞品X", "aliases": []}],
    "market": "cn",
    "questions": [],
}


def make_row(platform="deepseek", qid="Q1", rnd=1, mode="api",
             question="有什么好用的工具？", mentioned=True, probe=False):
    return {
        "platform": platform, "question_id": qid, "round": rnd, "sample_mode": mode,
        "question": question, "market": "cn", "ok": True,
        "brand_in_question": probe,
        "analysis": {
            "brand_mentioned": mentioned,
            "brand_rank": 1 if mentioned else 0,
            "candidates": [], "competitors_mentioned": [], "cited_domains": [],
            "own_domain_cited": False, "answer_chars": 10,
        },
    }


class TestAliasBoundary(unittest.TestCase):
    def test_cjk_alias_substring_still_matches(self):
        # 纯 CJK 别名保持子串匹配：中文无空格分词，右侧 CJK 延续不代表是另一个词
        r = S.analyze_answer("这个定制家很好用，推荐试试", CFG)
        self.assertTrue(r["brand_mentioned"])
        self.assertFalse(r["needs_review"])

    def test_normal_hit_not_over_excluded(self):
        r = S.analyze_answer("AIGCLINK定制家很好用", CFG)
        self.assertTrue(r["brand_mentioned"])
        self.assertFalse(r["needs_review"])

    def test_negated_hit_not_counted_and_flagged(self):
        r = S.analyze_answer("这不是全屋定制家居类工具", CFG)
        self.assertFalse(r["brand_mentioned"])
        self.assertTrue(r["needs_review"])

    def test_latin_alias_requires_boundary(self):
        cfg = {"brand": {"name": "灵眸", "aliases": ["AIGC"], "site": "https://x.example.com"},
               "competitors": [], "questions": []}
        # "AIGC" 是 "AIGCLINK" 的子串：右侧紧跟拉丁字符 → 不算命中
        self.assertFalse(S.analyze_answer("AIGCLINK很好用", cfg)["brand_mentioned"])
        # 双侧都是边界 → 正常命中
        self.assertTrue(S.analyze_answer("AIGC 很好用", cfg)["brand_mentioned"])
        self.assertTrue(S.analyze_answer("推荐AIGC，挺好", cfg)["brand_mentioned"])


class TestDedup(unittest.TestCase):
    def test_same_day_rerun_keeps_last(self):
        first = make_row(mentioned=True)
        last = make_row(mentioned=False)  # 重跑结果：未提及
        rows = S.dedup_rows([first, last])
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["analysis"]["brand_mentioned"])
        agg = S.aggregate(S.dedup_rows([first, last]), CFG)
        self.assertEqual(agg["deepseek"]["samples"], 1)
        self.assertEqual(agg["deepseek"]["mention_rate"], 0.0)

    def test_dedup_key_distinguishes_round_and_mode(self):
        rows = [make_row(rnd=1), make_row(rnd=2), make_row(mode="manual")]
        self.assertEqual(len(S.dedup_rows(rows)), 3)


class TestProbeNoFallback(unittest.TestCase):
    def test_probe_only_platform_mention_rate_none(self):
        rows = [make_row(qid="Q1", probe=True, question="AIGCLINK定制家是什么"),
                make_row(qid="Q2", probe=True, question="AIGCLINK定制家官网是哪个")]
        agg = S.aggregate(rows, CFG)
        m = agg["deepseek"]
        self.assertIsNone(m["mention_rate"])
        self.assertEqual(m["samples"], 0)
        self.assertEqual(m["probe"]["samples"], 2)
        self.assertEqual(m["probe"]["recognized_rate"], 1.0)

    def test_mixed_platform_still_splits(self):
        rows = [make_row(qid="Q1", probe=True, question="AIGCLINK定制家是什么"),
                make_row(qid="Q2", mentioned=True),
                make_row(qid="Q3", mentioned=False)]
        agg = S.aggregate(rows, CFG)
        m = agg["deepseek"]
        self.assertEqual(m["samples"], 2)
        self.assertEqual(m["mention_rate"], 0.5)
        self.assertEqual(m["probe"]["samples"], 1)


class TestMarketOf(unittest.TestCase):
    def test_unknown_platform_code(self):
        self.assertEqual(S.market_of("deepssek"), "unknown")

    def test_known_codes_unchanged(self):
        self.assertEqual(S.market_of("deepseek"), "cn")
        self.assertEqual(S.market_of("perplexity"), "global")
        self.assertEqual(S.market_of("chatgpt"), "global")


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


OK_PAYLOAD = {"choices": [{"message": {"content": "你好"}}], "model": "deepseek-v4-flash"}


class TestAskRetry(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"BAILIAN_KEY": "test-key"})
        self._env.start()
        self._sleep = mock.patch.object(S.time, "sleep")
        self._sleep.start()

    def tearDown(self):
        self._env.stop()
        self._sleep.stop()

    def _ask(self, side_effect):
        with mock.patch.object(S.requests, "post", side_effect=side_effect) as post:
            res = S.ask("deepseek", "测试问题")
        return res, post

    def test_retry_on_429_then_success(self):
        res, post = self._ask([_Resp(429, text="rate limited"),
                               _Resp(500, text="server error"),
                               _Resp(200, OK_PAYLOAD)])
        self.assertTrue(res["ok"])
        self.assertEqual(post.call_count, 3)

    def test_retry_exhausted_returns_error(self):
        res, post = self._ask([_Resp(500, text="err")] * 5)
        self.assertFalse(res["ok"])
        self.assertEqual(post.call_count, 3)  # 1 + 2 次重试

    def test_timeout_retried(self):
        res, post = self._ask([S.requests.exceptions.Timeout("t"),
                               _Resp(200, OK_PAYLOAD)])
        self.assertTrue(res["ok"])
        self.assertEqual(post.call_count, 2)

    def test_timeout_exhausted(self):
        res, post = self._ask([S.requests.exceptions.Timeout("t")] * 5)
        self.assertFalse(res["ok"])
        self.assertEqual(post.call_count, 3)

    def test_no_retry_on_400(self):
        res, post = self._ask([_Resp(400, text="bad request")] * 5)
        self.assertFalse(res["ok"])
        self.assertEqual(post.call_count, 1)


class TestUsageAccounting(unittest.TestCase):
    """token 用量记账。三种协议的字段名不一样，都要认。

    只记 token 不记钱：单价会漂移，token 是事实——有 token 随时能乘出成本，
    反过来不成立。取不到时必须记 None 而不是 0，否则「不知道花了多少」
    会被伪装成「没花钱」。
    """

    def test_openai_shape(self):
        self.assertEqual(S._usage_of({"usage": {"prompt_tokens": 120, "completion_tokens": 30}}),
                         {"in": 120, "out": 30})

    def test_anthropic_shape(self):
        self.assertEqual(S._usage_of({"usage": {"input_tokens": 9, "output_tokens": 4}}),
                         {"in": 9, "out": 4})

    def test_missing_usage_is_none(self):
        for payload in ({}, {"usage": None}, {"usage": {}}, {"usage": "n/a"}):
            self.assertIsNone(S._usage_of(payload), payload)

    def test_half_present_is_kept(self):
        self.assertEqual(S._usage_of({"usage": {"prompt_tokens": 7}}), {"in": 7, "out": 0})

    def _ask_with(self, payload):
        with mock.patch.dict(os.environ, {"BAILIAN_KEY": "k"}):
            with mock.patch.object(S.requests, "post", return_value=_Resp(200, payload)):
                return S.ask("deepseek", "q")

    def test_ask_surfaces_usage(self):
        res = self._ask_with({**OK_PAYLOAD, "usage": {"prompt_tokens": 11, "completion_tokens": 2}})
        self.assertEqual(res["usage"], {"in": 11, "out": 2})

    def test_ask_without_usage_reports_none(self):
        self.assertIsNone(self._ask_with(OK_PAYLOAD)["usage"])


class TestUsageSummary(unittest.TestCase):
    """累计用量：逐条加总，缺用量单独计。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = S.G.WORK
        S.G.WORK = Path(self._tmp.name)
        self.pdir = S.G.project_dir("demo")
        (self.pdir / "samples").mkdir(parents=True)

    def tearDown(self):
        S.G.WORK = self._old
        self._tmp.cleanup()

    def _write(self, rows):
        (self.pdir / "samples" / "2026-09-21.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8")

    def test_sums_and_splits_by_platform(self):
        self._write([
            {**make_row(platform="deepseek"), "usage": {"in": 100, "out": 20}},
            {**make_row(platform="deepseek"), "usage": {"in": 50, "out": 10}},
            {**make_row(platform="openai"), "usage": {"in": 7, "out": 3}},
        ])
        u = S.usage_summary("demo")
        self.assertEqual((u["calls"], u["in"], u["out"]), (3, 157, 33))
        self.assertEqual(u["by_platform"]["deepseek"]["in"], 150)
        self.assertEqual(u["by_platform"]["openai"]["out"], 3)

    def test_missing_usage_counted_separately(self):
        # 没回传用量 ≠ 花了 0：并进总数会把「不知道」伪装成「没花钱」
        self._write([{**make_row(), "usage": None},
                     {**make_row(), "usage": {"in": 5, "out": 1}}])
        u = S.usage_summary("demo")
        self.assertEqual((u["calls"], u["unknown"], u["in"]), (1, 1, 5))

    def test_rows_without_usage_key_are_unknown(self):
        # 改动前采的历史样本没有 usage 字段，同样归入 unknown
        self._write([make_row()])
        u = S.usage_summary("demo")
        self.assertEqual((u["calls"], u["unknown"]), (0, 1))

    def test_failed_calls_excluded(self):
        self._write([{**make_row(), "ok": False, "usage": None},
                     {**make_row(), "usage": {"in": 3, "out": 1}}])
        u = S.usage_summary("demo")
        self.assertEqual((u["calls"], u["unknown"], u["in"]), (1, 0, 3))

    def test_no_samples_is_zero(self):
        u = S.usage_summary("demo")
        self.assertEqual((u["calls"], u["unknown"], u["in"], u["out"]), (0, 0, 0, 0))
        self.assertEqual(u["by_platform"], {})


if __name__ == "__main__":
    unittest.main()
