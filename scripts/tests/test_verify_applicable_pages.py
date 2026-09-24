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

import itertools
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import tasks as T          # noqa: E402
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

    def test_page_not_crawled_defers(self):
        """本轮没抓到这页（超时/5xx）时 pages 里查不到，不能读成「还是没挂」。"""
        ok, why, _ = V.check(task("pages.has_jsonld", [PAGE]), audit([], []), {})
        self.assertIsNone(ok, f"应当交人工，实际：{why}")


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

    def test_page_not_crawled_defers(self):
        ok, why, _ = V.check(task("pages.static_text", [PAGE]), audit([], []), {})
        self.assertIsNone(ok, f"应当交人工，实际：{why}")


class AbsentDataIsNotAPass(unittest.TestCase):
    """缺数据时判「通过」，和缺数据时判「未达标」一样错。

    前者更隐蔽：判据都是「没问题 → 通过」，字段在抓取失败时默认为空/0，于是
    一次抖动就把工单自动标 done，写进客户记录；后者至少会有人来看一眼。
    2026-09-24 系统扫了一遍全部 checker，找出 5 处。
    """

    def _audit(self, **over):
        a = {"pages": [], "non_content_pages": [], "site": {}, "unreachable_count": 0}
        a.update(over)
        return a

    def _site_audit(self, **site):
        return self._audit(site=site)

    def test_robots_unknown_does_not_pass_ai_block(self):
        a = self._site_audit(robots_fetched=False, ai_bots_blocked=[])
        ok, why, _ = V.check(task("site.no_ai_bot_block", []), a, {})
        self.assertIsNone(ok, f"一次 robots 抖动就会把这条 P0 自动标 done，实际：{why}")

    def test_robots_read_and_unblocked_passes(self):
        a = self._site_audit(robots_fetched=True, ai_bots_blocked=[])
        ok, why, _ = V.check(task("site.no_ai_bot_block", []), a, {})
        self.assertIs(ok, True, why)

    def test_robots_read_and_blocked_fails(self):
        a = self._site_audit(robots_fetched=True, ai_bots_blocked=["GPTBot"])
        ok, why, _ = V.check(task("site.no_ai_bot_block", []), a, {})
        self.assertIs(ok, False, why)

    def test_sitemap_unreachable_does_not_pass_clean(self):
        """抓不到 sitemap 时污染数是 0（数的是空列表），不是「已经干净了」。"""
        a = self._site_audit(sitemap_reachable=False, sitemap_noisy_urls=0)
        ok, why, _ = V.check(task("site.sitemap_clean", []), a, {})
        self.assertIsNone(ok, why)

    def test_sitemap_read_and_clean_passes(self):
        a = self._site_audit(sitemap_reachable=True, sitemap_noisy_urls=0)
        ok, why, _ = V.check(task("site.sitemap_clean", []), a, {})
        self.assertIs(ok, True, why)

    def test_missing_pages_do_not_pass_block_check(self):
        """少抓几页 → 缺口数跟着变小 → 「下降 ≥50%」假通过。"""
        a = self._audit(unreachable_count=3, pages=[content_page(PAGE, blocks={"FAQ": []})])
        t = task("pages.block:FAQ", [PAGE])
        t["baseline_count"] = 20
        ok, why, _ = V.check(t, a, {})
        self.assertIsNone(ok, why)

    def test_missing_pages_do_not_pass_wordcount_check(self):
        a = self._audit(unreachable_count=3, pages=[content_page(PAGE, word_count=100)])
        t = task("pages.wordcount_gte:1000", [PAGE])
        t["baseline_count"] = 20
        ok, why, _ = V.check(t, a, {})
        self.assertIsNone(ok, why)

    def test_no_samples_does_not_fail_citation_check(self):
        ok, why, _ = V.check(task("external.any:a.com", []), self._audit(), None)
        self.assertIsNone(ok, f"没测过不能判未达标，实际：{why}")

    def test_samples_without_citation_still_fails(self):
        """有样本、确实没被引用 —— 这才是真的未达标。"""
        m = {"platforms": {"gpt": {"samples": 3, "cited_domains_all": {"b.com": 1}}}}
        ok, why, _ = V.check(task("external.any:a.com", []), self._audit(), m)
        self.assertIs(ok, False, why)


class ChannelCapabilityGatesMetrics(unittest.TestCase):
    """引用类指标只在联网通道上判。

    2026-09-24 实测：geo.json 那 4 条通道里 3 条是 api2d 中转、不联网（PROVIDERS
    里 search: False）。它们 26 个样本里抽出来的「引用域名」是
    your-api-base.example.com / localhost:8000 / api.yourdomain.com 这类示例代码
    占位符，一条真引用都没有（同期 sonar 是 289 个真实域名）。拿它们判「点名
    提问时引不到官网」，指标恒为 0，工单永远闭不了环 —— 三条 P0 死题就是这么来的。
    """

    def _m(self, **plats):
        return {"platforms": plats}

    CFG = {"brand": {"name": "Example", "site": "https://example.test"},
           "market": "global", "targets": {"mention_rate": 0.3}}

    def test_probe_cite_on_non_searching_channel_defers(self):
        m = self._m(**{"api2d-gpt": {"market": "global", "samples": 26,
                                     "probe": {"samples": 1, "own_domain_cite_rate": 0.0}}})
        ok, why, _ = V.check(task("metrics.probe_own_cite_gte:api2d-gpt:0.1", []), {}, m)
        self.assertIsNone(ok, f"不联网通道不该判引用率，实际：{why}")
        self.assertIn("不联网", why)

    def test_probe_cite_on_searching_channel_still_fails(self):
        """联网通道上「点名了还是引不到」是真信号，该判未达标。"""
        m = self._m(**{"openrouter-sonar": {"market": "global", "samples": 26,
                                            "probe": {"samples": 1,
                                                      "own_domain_cite_rate": 0.0}}})
        ok, why, _ = V.check(task("metrics.probe_own_cite_gte:openrouter-sonar:0.1", []), {}, m)
        self.assertIs(ok, False, why)

    def test_market_cite_ignores_non_searching_channels(self):
        """不联网通道的 0 不该把联网通道的 15% 稀释成 7.5%。"""
        m = self._m(**{
            "api2d-gpt": {"market": "global", "own_domain_cite_rate": 0.0},
            "openrouter-sonar": {"market": "global", "own_domain_cite_rate": 0.15},
        })
        ok, why, prog = V.check(task("metrics.own_cite_gte:global:0.1", []), {}, m)
        self.assertIs(ok, True, why)
        self.assertAlmostEqual(prog["cur"], 0.15, places=3)

    def test_market_cite_without_any_searching_channel_defers(self):
        """说明里要写清「没有联网通道」，不能落成「本期无采样数据」——
        后者会让人去找采样，而采样明明跑了，跑的是不联网的通道。"""
        m = self._m(**{"api2d-gpt": {"market": "global", "own_domain_cite_rate": 0.0}})
        ok, why, _ = V.check(task("metrics.own_cite_gte:global:0.1", []), {}, m)
        self.assertIsNone(ok, f"没有联网通道时不该判，实际：{why}")
        self.assertIn("联网通道", why)

    def test_mention_rate_still_uses_all_channels(self):
        """提及率不受影响：不联网通道照样能说明「模型认不认识这个品牌」。"""
        m = self._m(**{
            "api2d-gpt": {"market": "global", "mention_rate": 0.2},
            "openrouter-sonar": {"market": "global", "mention_rate": 0.0},
        })
        ok, why, prog = V.check(task("metrics.mention_rate_gte:global:0.1", []), {}, m)
        self.assertIs(ok, True, why)
        self.assertAlmostEqual(prog["cur"], 0.1, places=3)

    def test_market_cite_ticket_uses_only_searching_channels(self):
        """联网通道 15% 已经达标，不该被不联网通道的 0 拉成 7.5% 后又开一张单。"""
        m = self._m(**{
            "api2d-gpt": {"market": "global", "label": "GPT(api2d)", "samples": 26,
                          "mention_rate": 0.5, "own_domain_cite_rate": 0.0},
            "openrouter-sonar": {"market": "global", "label": "Perplexity(OpenRouter)",
                                 "samples": 26, "mention_rate": 0.5,
                                 "own_domain_cite_rate": 0.15},
        })
        titles = [t["title"] for t in T.from_metrics(m, self.CFG, itertools.count(1))]
        self.assertFalse([x for x in titles if "进得了 AI 的检索结果" in x], titles)

    def test_no_probe_ticket_for_non_searching_channel(self):
        """开工单那一侧同样要挡：挡了判据却照旧开单，就是开出一张判不了的工单。"""
        m = self._m(**{"api2d-gpt": {"market": "global", "label": "GPT(api2d)",
                                     "samples": 26, "mention_rate": 0.0,
                                     "probe": {"samples": 1, "own_domain_cite_rate": 0.0}}})
        titles = [t["title"] for t in T.from_metrics(m, self.CFG, itertools.count(1))]
        self.assertFalse([x for x in titles if "引不到官网" in x], titles)

    def test_probe_ticket_still_opened_for_searching_channel(self):
        m = self._m(**{"openrouter-sonar": {"market": "global", "label": "Perplexity(OpenRouter)",
                                            "samples": 26, "mention_rate": 0.0,
                                            "probe": {"samples": 1, "own_domain_cite_rate": 0.0}}})
        titles = [t["title"] for t in T.from_metrics(m, self.CFG, itertools.count(1))]
        self.assertTrue([x for x in titles if "引不到官网" in x], titles)


if __name__ == "__main__":
    unittest.main()
