import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import report as R

CFG = {"brand": {"name": "Acme", "site": "https://www.acme.com"}, "market": "both"}

AUDIT = {
    "page_count": 10, "avg_score": 60,
    "site": {"has_sitemap": True, "sitemap_url_count": 5, "has_llms_txt": False,
             "ai_bots_blocked": [], "pages_ok": 10, "pages_crawled": 10},
    "site_issues": [], "language_coverage": {},
    "grade_distribution": {"A": 2, "B": 4, "C": 3, "D": 1},
    "pages": [], "block_gap": [],
}


def plat(market, mention, label=None):
    d = {"market": market, "mention_rate": mention, "samples": 5,
         "top1_rate": 0.0, "top3_rate": 0.0, "avg_rank": None,
         "own_domain_cite_rate": None, "probe": {},
         "competitor_mentions": {}, "top_cited_domains": {}}
    if label:
        d["label"] = label
    return d


def metrics_with(platforms):
    return {"date": "2026-07-27", "sample_count": 20, "question_count": 5,
            "platforms": platforms}


def md(platforms):
    return R.build_markdown(CFG, AUDIT, metrics_with(platforms), None, None, [])


class TestBestWorstDegenerate(unittest.TestCase):
    def test_all_zero_no_conclusion(self):
        m = md({"qwen": plat("cn", 0.0, "千问"), "deepseek": plat("cn", 0.0, "DeepSeek"),
                "perplexity": plat("global", 0.0, "Perplexity")})
        self.assertIn("不下结论", m)
        self.assertNotIn("最好", m)
        self.assertNotIn("最弱", m)

    def test_single_platform_no_conclusion(self):
        m = md({"qwen": plat("cn", 0.5, "千问")})
        self.assertIn("不下结论", m)
        self.assertNotIn("最好", m)
        self.assertNotIn("最弱", m)

    def test_all_equal_no_conclusion(self):
        m = md({"qwen": plat("cn", 0.3, "千问"), "deepseek": plat("cn", 0.3, "DeepSeek")})
        self.assertIn("不下结论", m)
        self.assertNotIn("最好", m)
        self.assertNotIn("最弱", m)

    def test_normal_two_platforms_conclusion(self):
        m = md({"qwen": plat("cn", 0.5, "千问"), "deepseek": plat("cn", 0.1, "DeepSeek")})
        self.assertIn("最好", m)
        self.assertIn("最弱", m)
        self.assertIn("千问", m)
        self.assertIn("DeepSeek", m)
        self.assertNotIn("不下结论", m)

    def test_none_filtered_then_single_no_conclusion(self):
        m = md({"qwen": plat("cn", 0.5, "千问"), "deepseek": plat("cn", None, "DeepSeek")})
        self.assertIn("不下结论", m)
        self.assertNotIn("最好", m)

    def test_all_none_market_untested(self):
        m = md({"qwen": plat("cn", 0.5, "千问"), "deepseek": plat("cn", 0.1, "DeepSeek"),
                "perplexity": plat("global", None, "Perplexity")})
        self.assertIn("海外：未测", m)
        self.assertIn("国内最好", m)


class TestMarketAvgCards(unittest.TestCase):
    def test_split_cn_global(self):
        cards = dict(R.market_avg_cards(metrics_with({
            "qwen": plat("cn", 0.5), "deepseek": plat("cn", 0.5),
            "perplexity": plat("global", 0.1)})))
        self.assertEqual(cards["国内平均提及率"], "50%")
        self.assertEqual(cards["海外平均提及率"], "10%")

    def test_none_market_untested(self):
        cards = dict(R.market_avg_cards(metrics_with({
            "qwen": plat("cn", 0.5), "perplexity": plat("global", None)})))
        self.assertEqual(cards["国内平均提及率"], "50%")
        self.assertEqual(cards["海外平均提及率"], "未测")

    def test_no_metrics_no_cards(self):
        self.assertEqual(R.market_avg_cards(None), [])


NO_SITE_AUDIT = {
    "no_site": True, "page_count": 0, "avg_score": None,
    "site": {}, "site_issues": [], "language_coverage": {},
    "grade_distribution": {}, "pages": [], "block_gap": [],
}


class TestNoSiteReport(unittest.TestCase):
    """无站点项目（商品 / 线下品牌）的报告不能出现站点体检的结论。

    audit 的 no_site 分支写的是 avg_score=None、site={}，照原样渲染就是正文里
    「站点均分 **None**」、技术底座表里「sitemap.xml **无**」—— 对一个根本没有
    官网的项目，那是在客户交付物里断言资产缺失。
    """

    def test_score_never_rendered_as_none(self):
        m = R.build_markdown(CFG, NO_SITE_AUDIT, None, None, None, [])
        self.assertNotIn("None", m)
        self.assertIn("站点体检不适用", m)

    def test_site_assets_not_claimed_missing(self):
        m = R.build_markdown(CFG, NO_SITE_AUDIT, None, None, None, [])
        self.assertNotIn("sitemap.xml", m)
        self.assertNotIn("llms.txt", m)

    def test_normal_site_still_reports_them(self):
        # 反向断言：有站点时这两项必须还在。少了它，上面两条会被「整节被删掉」
        # 这种改法骗过。
        m = R.build_markdown(CFG, AUDIT, None, None, None, [])
        self.assertIn("sitemap.xml", m)
        self.assertIn("llms.txt", m)


if __name__ == "__main__":
    unittest.main()
