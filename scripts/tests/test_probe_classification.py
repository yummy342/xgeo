"""回归：品牌认知探测题由问题库声明，不靠拿问题原文撞别名表。

2026-09-24 实测的坑：判据是 `brand_in_question()` —— 把问题原文拿去撞别名表。
而别名表 09-20 起刻意去掉裸词 FreeModel（六个同名站共用，裸词命中更可能是竞品），
于是「What is FreeModel?」这种一眼点名的题反而撞不上。后果两头都错：

  1. 它留在可见性的分母里。答案必然出现品牌名，却永远命中不了（命中要求写出
     「FreeModel by Aiglade」完整短语或网址），把提及率一直往下拖；
  2. 品牌认知那栏只剩 1 个样本（27 题里只有 q027「…freemodel.online…」撞得上），
     报出来的 1.0 / 0.0 是一个样本的噪声，不是指标。

线上实测（同一份 108 条样本，只换判据，不重采）：
  分母 26→23，点名 n 1→4，认知率从「n=1 的 1.0」变成 n=4 的 0.25。

跑法：.venv/bin/python -m unittest discover -s scripts/tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import sample as S         # noqa: E402

CFG = {
    "brand": {"name": "FreeModel by Aiglade",
              "site": "https://freemodel.online",
              "aliases": ["freemodel.online", "FreeModel by Aiglade", "Aiglade FreeModel"]},
    "competitors": [],
    "questions": [
        {"id": "q1", "group": "推荐", "market": "global", "text": "Best gateway for one key?"},
        {"id": "q2", "group": "推荐", "market": "global", "text": "Cheapest LLM API?"},
        {"id": "q3", "group": "品牌验证", "market": "global", "text": "What is FreeModel?", "probe": True},
        {"id": "q4", "group": "品牌验证", "market": "global",
         "text": "Does freemodel.online work with Claude Code?", "probe": True},
    ],
}


def row(plat: str, qid: str, mentioned: bool) -> dict:
    return {"platform": plat, "question_id": qid, "question": "x", "ok": True,
            "market": "global", "brand_in_question": False, "answer": "x",
            "analysis": {"brand_mentioned": mentioned, "brand_rank": 0,
                         "competitors_mentioned": [], "cited_domains": [],
                         "own_domain_cited": False, "answer_chars": 1,
                         "candidates": [], "negative_cues": [], "needs_review": False}}


class DeclaredProbe(unittest.TestCase):
    def test_declared_ids_come_from_the_question_bank(self):
        self.assertEqual(S.declared_probe_ids(CFG), {"q3", "q4"})

    def test_plain_brand_question_is_probe_even_though_the_text_does_not_match(self):
        """「What is FreeModel?」撞不上别名表（裸词刻意不在表里），但问题库声明了。"""
        q3 = CFG["questions"][2]
        self.assertFalse(S.brand_in_question(q3["text"], CFG), "前提：文本匹配确实认不出")
        self.assertTrue(S.is_probe_question(q3, CFG))

    def test_undeclared_question_falls_back_to_text_matching(self):
        q = {"id": "q9", "text": "Does freemodel.online support Claude Code?"}
        self.assertTrue(S.is_probe_question(q, CFG))

    def test_declared_ids_ignores_questions_without_the_flag(self):
        cfg = {"questions": [{"id": "a", "text": "x"}, {"id": "b", "text": "y"}]}
        self.assertEqual(S.declared_probe_ids(cfg), set())

    def test_missing_questions_block_is_not_a_crash(self):
        self.assertEqual(S.declared_probe_ids({}), set())


class AggregateSplitsByDeclaration(unittest.TestCase):
    def test_probe_samples_leave_the_visibility_denominator(self):
        rows = [row("api2d-gpt", "q1", False), row("api2d-gpt", "q2", True),
                row("api2d-gpt", "q3", True), row("api2d-gpt", "q4", True)]
        m = S.aggregate(rows, CFG)["api2d-gpt"]
        self.assertEqual(m["probe"]["samples"], 2, "两道声明过的题都该归品牌认知")
        # 分母只剩 q1/q2，其中只有 q2 提到品牌
        self.assertEqual(m["mention_rate"], 0.5)
        self.assertEqual(m["probe"]["recognized_rate"], 1.0)

    def test_all_probe_means_visibility_is_not_measured(self):
        """绝不回退：只剩点名题时提及率是「未测」，不是 100%。"""
        rows = [row("api2d-gpt", "q3", True), row("api2d-gpt", "q4", True)]
        m = S.aggregate(rows, CFG)["api2d-gpt"]
        self.assertIsNone(m["mention_rate"])
        self.assertEqual(m["probe"]["samples"], 2)


if __name__ == "__main__":
    unittest.main()
