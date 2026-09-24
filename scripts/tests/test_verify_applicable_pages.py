"""回归：页面级 checker 只对「能改的页」判达标，否则工单是死题。

2026-09-24 在 freemodel 上实测到的：`全站补 JSON-LD 结构化数据` 的受影响列表里
只剩 `https://freemodel.online/v1/models` —— 一个返回 JSON 的 API 端点，audit 归为
non_document，连 jsonld_types 字段都不带。给端点挂 JSON-LD 无从下手，这条验收每次
跑都是「0/1 页已挂 JSON-LD」，工单永远闭不了环，而页面上根本没有可改的东西。

判据：JSON-LD 只能挂在 HTML 文档上 —— non_document 的 URL 不参与判定；
SPA 外壳（spa_shell）是 HTML，仍然要算，否则空壳页的工单会被同一个豁免漏掉。

同理 `pages.static_text` 的分母要用实际参评页数：功能页被豁免后，如果 aff 里还混着
功能页，base 会算出「2/1 页已能抓到正文」这种数。

跑法：.venv/bin/python -m unittest discover -s scripts/tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import verify as V         # noqa: E402

ROOT = "https://example.test"
API = f"{ROOT}/v1/models"
SHELL = f"{ROOT}/console"
LOGIN = f"{ROOT}/login"
PAGE = f"{ROOT}/docs"


def task(expr: str, affected: list[str]) -> dict:
    return {"acceptance": {"type": "auto", "check": expr}, "affected": affected}


def content_page(url: str, **over) -> dict:
    p = {"url": url, "status": 200, "word_count": 900, "jsonld_types": ["Organization"],
         "issue_codes": []}
    p.update(over)
    return p


def non_content(url: str, reason: str, **over) -> dict:
    """audit 里非内容页的形状：只有 url/reason/word_count，没有 jsonld_types。"""
    p = {"url": url, "reason": reason, "reason_label": reason,
         "title": "", "word_count": 0, "issue_codes": []}
    p.update(over)
    return p


def audit(pages: list[dict], non: list[dict]) -> dict:
    return {"pages": pages, "non_content_pages": non, "site": {}}


class JsonLdSkipsNonDocument(unittest.TestCase):
    def test_api_endpoint_alone_is_not_a_failure(self):
        """只剩 API 端点时判通过，且说明里不能写「0/0 页已挂 JSON-LD」。"""
        a = audit([], [non_content(API, "non_document")])
        ok, why, prog = V.check(task("pages.has_jsonld", [API]), a, {})
        self.assertIs(ok, True, why)
        self.assertIn("非网页端点", why)
        self.assertIsNone(prog, f"没有可判定的页，不该给量化进度：{prog}")

    def test_api_endpoint_does_not_mask_a_real_failure(self):
        """端点豁免了，但同一张工单里真没挂 JSON-LD 的页仍要判未达标。"""
        a = audit([content_page(PAGE, jsonld_types=[])], [non_content(API, "non_document")])
        ok, why, prog = V.check(task("pages.has_jsonld", [API, PAGE]), a, {})
        self.assertIs(ok, False, why)
        self.assertEqual((prog["cur"], prog["base"]), (1, 1))

    def test_spa_shell_is_still_judged(self):
        """SPA 外壳是 HTML，JSON-LD 挂得上，不能一起豁免掉。"""
        a = audit([], [non_content(SHELL, "spa_shell")])
        ok, why, prog = V.check(task("pages.has_jsonld", [SHELL]), a, {})
        self.assertIs(ok, False, why)
        self.assertEqual((prog["cur"], prog["base"]), (1, 1))

    def test_all_affected_pages_fixed_passes(self):
        a = audit([content_page(PAGE)], [non_content(API, "non_document")])
        ok, why, prog = V.check(task("pages.has_jsonld", [API, PAGE]), a, {})
        self.assertIs(ok, True, why)
        self.assertEqual((prog["cur"], prog["base"]), (0, 1))


class StaticTextDenominator(unittest.TestCase):
    def test_func_page_excluded_from_denominator(self):
        a = audit([content_page(PAGE, word_count=400)], [])
        ok, why, prog = V.check(task("pages.static_text", [PAGE, LOGIN]), a, {})
        self.assertIs(ok, True, why)
        self.assertIn("1/1", why)
        self.assertEqual(prog["base"], 1)

    def test_only_func_pages_is_not_a_failure(self):
        a = audit([content_page(LOGIN, word_count=30)], [])
        ok, why, prog = V.check(task("pages.static_text", [LOGIN]), a, {})
        self.assertIs(ok, True, why)
        self.assertIn("功能页", why)
        self.assertIsNone(prog)

    def test_spa_shell_without_text_fails(self):
        a = audit([], [non_content(SHELL, "spa_shell")])
        ok, why, _ = V.check(task("pages.static_text", [SHELL]), a, {})
        self.assertIs(ok, False, why)

    def test_fixed_spa_shell_passes(self):
        """修好之后该页变回内容页回到 pages 里，同一张工单要能判过。"""
        a = audit([content_page(SHELL, word_count=300)], [])
        ok, why, _ = V.check(task("pages.static_text", [SHELL]), a, {})
        self.assertIs(ok, True, why)


if __name__ == "__main__":
    unittest.main()
