"""geo.py status 的效果趋势段：对照的两侧必须同源。

2026-09-30 审查（Everest）：原来基准侧跳过残轮、对比侧 n 永远取最新一期 ——
最新一期是残轮时，结论就是拿噪声比完整轮；而且同一屏里「几道题上升」来自
question_delta（完整轮之间比），可能与 b→n 基于不同的日期对。
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import analytics as A
import geolib as G
import geo as CLI

CFG = {
    "brand": {"name": "Acme", "site": "https://www.acme.com", "aliases": []},
    "market": "cn",
    "questions": [
        {"id": "q1", "text": "有什么好用的方案工具？", "group": "推荐", "market": "cn"},
        {"id": "q2", "text": "Acme 是什么？", "group": "品牌验证", "market": "cn"},
        {"id": "q3", "text": "Best proposal tools?", "group": "推荐", "market": "global"},
    ],
}


def row(qid, mentioned=False, probe=False):
    return {
        "platform": "p1", "question_id": qid, "round": 1, "sample_mode": "api",
        "question": "Q?", "market": "cn", "ok": True, "brand_in_question": probe,
        "analysis": {"brand_mentioned": mentioned, "brand_rank": 1 if mentioned else 0,
                     "candidates": [], "competitors_mentioned": [], "cited_domains": [],
                     "own_domain_cited": False, "answer_chars": 10},
    }


def full(mentioned=False):
    """一轮完整轮：题库 3 道题各一条。"""
    return [row("q1", mentioned), row("q2", probe=True), row("q3", mentioned)]


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = G.WORK
        G.WORK = Path(self._tmp.name)
        pdir = G.WORK / "demo"
        (pdir / "samples").mkdir(parents=True)
        (pdir / "geo.json").write_text(json.dumps(CFG, ensure_ascii=False), "utf-8")

    def tearDown(self):
        G.WORK = self._old
        self._tmp.cleanup()

    def samples(self, days):
        p = G.WORK / "demo" / "samples"
        for name, rows in days.items():
            p.joinpath(f"{name}.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8")


class TestEffectVerdictPairing(Base):
    def _out(self, slug="demo"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            CLI._print_effect(slug)
        return buf.getvalue()

    def test_latest_partial_is_not_the_comparison_side(self):
        # 三期：完整 → 完整 → 残轮。结论必须基于前两个完整轮，且印明白
        self.samples({
            "2026-07-25": full(mentioned=False),
            "2026-07-26": full(mentioned=True),
            "2026-07-27": [row("q1")],          # 残轮
        })
        out = self._out()
        self.assertIn("最新一期", out)
        self.assertIn("2026-07-26", out)        # 对照的右侧是完整轮，不是残轮那天
        self.assertIn("2026-07-25 → 2026-07-26", out)

    def test_verdict_dates_match_question_delta(self):
        # 同一屏里两个结论必须基于同一对日期 —— 否则读者会把两组数当一回事
        self.samples({
            "2026-07-25": full(mentioned=False),
            "2026-07-26": full(mentioned=True),
            "2026-07-27": [row("q1")],
        })
        out = self._out()
        pairs = {tuple(x["dates"]) for x in A.question_delta("demo")}
        for pair in pairs:
            self.assertIn(f"{pair[0]} → {pair[1]}", out)

    def test_fallback_says_so(self):
        # 只有一个完整轮时不静默比较，要说明这次对照含残轮
        self.samples({
            "2026-07-26": full(mentioned=True),
            "2026-07-27": [row("q1")],
        })
        out = self._out()
        self.assertIn("完整轮不足两个", out)


if __name__ == "__main__":
    unittest.main()
