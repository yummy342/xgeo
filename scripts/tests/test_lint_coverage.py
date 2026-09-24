"""回归：lint 在英文稿上不能是瞎的。

2026-09-25 实测：freemodel（英文项目）27 篇初稿跑 lint，报「0 问题、0 高风险」。
翻判据才发现它只管中文形态 ——

  · 数字扫描只认中文单位与 $ %，英文的「1,200 models」这类裸计数一律放过；
    而且拿整段（"477 models"）去比事实卡（卡里存的是 "477"），连合规数字也会
    被判成「未核实」。
  · 年份检查只匹配「20XX 年」，英文的 2026 / 2024 全部漏检。

于是「0 问题」不是干净，是**没查**。这份测试把两种语言形态都钉住。

跑法：.venv/bin/python -m unittest discover -s scripts/tests
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import generate as GN     # noqa: E402
import geolib as G        # noqa: E402

SLUG = "t-lint"
FACTS_MD = """# 事实库

## 一句话定义

> Example is an AI model gateway.

## 关键数字

| 事实 | 数值 | 来源 | 证据 |
|---|---|---|---|
| 条目总数 | 477 | /v1/models | A |
| 组合路由 | 38 | 同上 | A |
"""

CFG = {
    "slug": SLUG, "market": "global",
    "brand": {"name": "Example", "site": "https://example.test", "aliases": [], "products": []},
    "competitors": [{"name": "OpenRouter", "aliases": ["openrouter.ai"]}],
    "pages": {"max": 25, "seed": []},
    "questions": [{"id": "q1", "text": "x"}],
    "keywords": [],
}


class LintCoversEnglish(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pdir = Path(self.tmp.name) / SLUG
        (self.pdir / "content").mkdir(parents=True)
        (self.pdir / "drafts").mkdir(parents=True)
        (self.pdir / "geo.json").write_text(json.dumps(CFG), "utf-8")
        (self.pdir / "content" / "facts.md").write_text(FACTS_MD, "utf-8")
        self._work = G.WORK
        G.WORK = Path(self.tmp.name)
        self.addCleanup(self._restore)

    def _restore(self):
        G.WORK = self._work
        self.tmp.cleanup()

    def lint(self, body: str) -> list[dict]:
        p = self.pdir / "drafts" / "t.md"
        p.write_text(body, "utf-8")
        return GN.lint_draft(SLUG, p)

    def types(self, body: str) -> set[str]:
        return {i["type"] for i in self.lint(body)}

    def test_english_count_not_in_facts_is_flagged(self):
        self.assertIn("未核实数字", self.types("DataCite lists 1,200 models in total."))

    def test_english_count_that_is_verified_passes(self):
        """477 在事实卡里 —— 英文写法不该被误判成未核实。"""
        self.assertNotIn("未核实数字", self.types("The catalog holds 477 models today."))

    def test_english_unit_variants_are_covered(self):
        for s in ("512 providers", "9000 tokens", "30 requests", "250 ms"):
            with self.subTest(s=s):
                self.assertIn("未核实数字", self.types("It handles " + s + " per run."))

    def test_non_current_year_is_flagged_in_english(self):
        self.assertIn("年份存疑", self.types("Back in 2024 the tooling was different."))

    def test_current_year_passes(self):
        self.assertNotIn("年份存疑", self.types(f"Verified in {G.today()[:4]}."))

    def test_chinese_forms_still_covered(self):
        """原来的中文形态不能被这次改动弄丢。"""
        t = self.types("这个站有 888 万个条目，2024 年就上线了。")
        self.assertIn("未核实数字", t)
        self.assertIn("年份存疑", t)


if __name__ == "__main__":
    unittest.main()
