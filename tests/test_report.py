import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import geolib as G
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


class TestAuditDayIsNotReportDay(unittest.TestCase):
    """报告不能拿「今天」当体检日。

    2026-09-30 实测：audit.json 停在 09-17（report 只渲染、不重抓），归档却按今天写，
    history/ 里于是躺着 09-29、09-30 两条一模一样的 44.5 —— 趋势图看着像「连续三期
    持平」，而站点其实从 44.5 变成了 78.2，只是没人量过。
    """

    OLD = dict(AUDIT, audited_at="2026-09-17T16:13:48+08:00")

    def test_header_carries_audit_day(self):
        m = R.build_markdown(CFG, self.OLD, None, None, None, [])
        self.assertIn("体检 2026-09-17", m)
        self.assertIn("非本期", m)

    def test_header_has_no_stale_mark_when_fresh(self):
        a = dict(AUDIT, audited_at=G.now_iso())
        m = R.build_markdown(CFG, a, None, None, None, [])
        self.assertIn("体检 " + G.now_iso()[:10], m)
        self.assertNotIn("非本期", m)

    def test_audit_day_falls_back_without_timestamp(self):
        self.assertEqual(R.audit_day(self.OLD, "2030-01-01"), "2026-09-17")
        self.assertEqual(R.audit_day({}, "2030-01-01"), "2030-01-01")

    def test_prev_audit_skips_current_round(self):
        with tempfile.TemporaryDirectory() as t:
            pdir = Path(t)
            (pdir / "history").mkdir()
            G.write_json(pdir / "history" / "audit-2026-09-17.json",
                         {"avg_score": 44.5, "date": "2026-09-17"})
            G.write_json(pdir / "history" / "audit-2026-09-30.json",
                         {"avg_score": 78.2, "date": "2026-09-30"})
            self.assertEqual(R.prev_audit(pdir)["avg_score"], 78.2)
            # 排除本期体检日 → 拿到的是真基线，不是自己跟自己比
            self.assertEqual(R.prev_audit(pdir, "2026-09-30")["avg_score"], 44.5)

    def test_prev_audit_excludes_whole_current_day(self):
        # 同一天跑了多轮，文件名带时分秒-微秒；它们全是「本期」，一份都不能当上一期
        with tempfile.TemporaryDirectory() as t:
            pdir = Path(t)
            (pdir / "history").mkdir()
            G.write_json(pdir / "history" / "audit-2026-09-17.json",
                         {"avg_score": 44.5, "date": "2026-09-17"})
            for stamp in ("20260930-101500-000123", "20260930-101500-000456"):
                G.write_json(pdir / "history" / f"audit-2026-09-30-{stamp}.json",
                             {"avg_score": 78.2, "date": "2026-09-30"})
            self.assertEqual(R.prev_audit(pdir, "2026-09-30")["avg_score"], 44.5)

    def test_history_entry_keyed_by_audit_day(self):
        with tempfile.TemporaryDirectory() as t:
            old_work = G.WORK
            G.WORK = Path(t)
            try:
                pdir = G.WORK / "demo"
                pdir.mkdir(parents=True)
                G.write_json(pdir / "geo.json", dict(CFG, slug="demo"))
                G.write_json(pdir / "audit.json", self.OLD)
                R.run("demo")
                names = sorted(p.name for p in (pdir / "history").glob("*.json"))
                # 名字带的是**体检日**（09-17），不是跑报告那天 —— 否则一份旧 audit
                # 会被写成一条当天的新记录，趋势图上看就是「这一期没有任何变化」
                self.assertTrue(names and names[0].startswith("audit-2026-09-17-"), names)
                self.assertNotIn(G.today(), names[0])
            finally:
                G.WORK = old_work


if __name__ == "__main__":
    unittest.main()
