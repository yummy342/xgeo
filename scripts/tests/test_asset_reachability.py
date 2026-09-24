"""回归：抓取失败 ≠ 页面/资产不存在。

两条真实踩过的坑（2026-09-24 复现）：

1. /llms.txt 线上 200 / 2849 字节，audit 报「没有 /llms.txt」并开出
   「上线 /llms.txt」工单 —— fetch_text 把「这次没抓到」也返回 ""，
   调用方读成了「站点没有这个文件」。
2. /v1/models 抓取时撞上 CF 502，那一页的 CDN 错误页（42 词、带 noindex）
   被当内容页打分，一口气产出 3 条 P0 + 1 条 P2 伪工单（页面不可访问 /
   noindex / 无 JSON-LD / 缺 canonical），还把七八条计数各撑大 1。

跑法：.venv/bin/python -m unittest discover -s scripts/tests
"""

from __future__ import annotations

import io
import itertools
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import audit as A          # noqa: E402
import crawl as C          # noqa: E402
import deliverables as D   # noqa: E402
import geolib as G         # noqa: E402
import report as R         # noqa: E402
import tasks as T          # noqa: E402
import verify as V         # noqa: E402

SLUG = "t-reach"
ROOT_URL = "https://example.test"

CFG = {
    "brand": {"name": "Example", "site": ROOT_URL, "aliases": [], "products": []},
    "market": "cn",
    "questions": [{"text": "example 怎么用"}],
    "pages": {"max": 25, "seed": []},
    "keywords": [],
}


def task(expr: str) -> dict:
    return {"acceptance": {"type": "auto", "check": expr}}


def page(url: str, **over) -> dict:
    """一页形状完整的最小记录：'https://example.test' + 路径。"""
    p = {
        "url": f"{ROOT_URL}/{url}", "final_url": f"{ROOT_URL}/{url}", "status": 200,
        "error": None, "content_type": "text/html; charset=utf-8",
        "title": "Example page", "meta_description": "", "meta_robots": "",
        "x_robots_tag": "", "hreflang_count": 0, "canonical": f"{ROOT_URL}/{url}",
        "lang": "en", "h1": ["Example"], "h2": [f"Section {i}" for i in range(7)],
        "h3_count": 0, "para_count": 30, "li_count": 20, "table_count": 0,
        "img_count": 0, "external_links": 3, "jsonld_types": ["Organization"],
        "jsonld_raw": [], "word_count": 900, "language": "en", "cjk_ratio": 0.0,
        "text": "Example text. " * 200, "fetched_at": "2026-09-24T00:00:00+00:00",
        "snapshot": "", "ua_fallback": False,
    }
    p.update(over)
    return p


def cf_502_page() -> dict:
    """CDN 错误页：状态 502、正文是错误页、带 noindex。抓到的样本见 evidence。"""
    return page("v1/models", status=502, error="HTTP 502", content_type="text/html; UTF-8",
                title="example.test | 502: Bad gateway", meta_robots="noindex",
                canonical="", jsonld_types=[], word_count=42, h2=["What happened?"],
                para_count=2, li_count=0, external_links=0, text="Error 502. " * 10)


SITE = {
    "slug": SLUG, "root": ROOT_URL, "crawled_at": "2026-09-24T00:00:00+00:00",
    "has_robots": True, "robots_fetched": True,
    "has_sitemap": True, "sitemap_url_count": 2,
    "robots_sitemap_declared": True, "sitemap_noisy_urls": 0, "sitemap_noisy_example": None,
    "ai_bots_blocked": [], "ai_bots_partial": [], "ai_ua_probe": {}, "ai_ua_blocked": [],
    "llms_txt_check": None, "pages_crawled": 1, "pages_ok": 1, "non_content_pages": 0,
    "ua_fallback_pages": 0,
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pdir = Path(self.tmp.name) / SLUG
        self.pdir.mkdir(parents=True)
        (self.pdir / "geo.json").write_text(json.dumps(CFG), "utf-8")
        self._work = G.WORK
        G.WORK = Path(self.tmp.name)
        self.addCleanup(self._restore)

    def _restore(self):
        G.WORK = self._work
        self.tmp.cleanup()

    def write_evidence(self, pages: list[dict], site: dict):
        ev = self.pdir / "evidence"
        ev.mkdir(exist_ok=True)
        with io.open(ev / "pages.jsonl", "w", encoding="utf-8") as f:
            for p in pages:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        (ev / "site.json").write_text(json.dumps(site, ensure_ascii=False), "utf-8")

    def run_audit(self, pages, site) -> dict:
        self.write_evidence(pages, site)
        return A.run(SLUG)


class FetchTextContract(Base):
    """fetch_text 三态：内容 / ""（404 确实没有）/ None（这次没拿到）。"""

    @staticmethod
    def _resp(status, body=b"", headers=None):
        r = mock.Mock()
        r.status_code = status
        r.encoding = "utf-8"
        r.headers = headers or {"Content-Type": "text/plain"}
        r.iter_content = lambda n: iter([body])
        r.close = lambda: None
        return r

    def test_200_returns_body(self):
        with mock.patch.object(G.requests, "get", return_value=self._resp(200, b"# hi")):
            self.assertEqual(G.fetch_text("http://x/llms.txt"), "# hi")

    def test_404_returns_empty_string(self):
        with mock.patch.object(G.requests, "get", return_value=self._resp(404)):
            self.assertEqual(G.fetch_text("http://x/llms.txt"), "")

    def test_transport_failure_returns_none(self):
        """这一条是本次修复的核心：失败不能再伪装成「文件不存在」。"""
        with mock.patch.object(G.requests, "get", side_effect=OSError("boom")):
            self.assertIsNone(G.fetch_text("http://x/llms.txt", retries=0))

    def test_5xx_returns_none(self):
        with mock.patch.object(G.requests, "get", return_value=self._resp(502)):
            self.assertIsNone(G.fetch_text("http://x/llms.txt", retries=0))


class UnreachablePageNotScored(Base):
    """502 错误页不进评分、不出页面级 issue，只在「访问」层报一次。"""

    def setUp(self):
        super().setUp()
        self.audit = self.run_audit([page("docs/"), cf_502_page()], dict(SITE))

    def test_counted_separately(self):
        self.assertEqual(self.audit["page_count"], 1)
        self.assertEqual(self.audit["unreachable_count"], 1)
        self.assertEqual(self.audit["unreachable_pages"][0]["status"], 502)

    def test_error_page_codes_do_not_leak(self):
        codes = {c for p in self.audit["pages"] for c in p["issue_codes"]}
        for leaked in ("PAGE_UNREACHABLE", "NOINDEX", "XROBOTS_NOINDEX",
                       "NO_JSONLD", "NO_CANONICAL"):
            self.assertNotIn(leaked, codes, f"{leaked} 来自 502 错误页，不该出现")

    def test_site_issues_have_no_unreachable_claim(self):
        self.assertFalse([i for i in self.audit["site_issues"] if "不可访问" in i])

    def test_access_layer_still_reports_the_failure(self):
        access = next(l for l in self.audit["layers"] if l["key"] == "access")
        self.assertTrue([t for t in access["issues"] if "抓取失败" in t])
        self.assertIn("/v1/models", " ".join(access["issues"]))

    def test_block_gap_counts_only_real_pages(self):
        faq = next(g for g in self.audit["block_gap"] if g["block"] == "FAQ")
        self.assertEqual(faq["total"], 1)

    def test_todo_list_has_no_pseudo_tickets(self):
        todos = R.collect_todos(self.audit)
        for pseudo in ("不可访问", "noindex", "canonical", "JSON-LD"):
            self.assertFalse([t for t in todos if pseudo in t["action"]],
                             f"「{pseudo}」是 502 错误页带出来的伪工单")


class RobotsUnknownIsNotAnAbsence(Base):
    """robots.txt 没抓到 ≠ robots 里没写 Sitemap、≠ llms.txt 的链接失效。

    2026-09-24 同一轮实测：robots.txt 抓取失败（CF 抖动），立刻多报两条假结论
    ——「P2 robots.txt 没有声明 Sitemap: 行」（线上末尾明明有 Sitemap 行），
    以及「P1 llms.txt 里 1/6 条抽样链接打不开」（那条是 /api/gateway/v1，一个
    GET 返回 404 的 POST 端点，llms.txt 写它的基址是正确做法；这条排除平时靠
    robots 里 Disallow: /api/ 生效，robots 一没拿到，排除也就没了）。
    """

    def _site(self, **over):
        s = dict(SITE)
        s.update({"has_sitemap": True, "sitemap_url_count": 2,
                  "robots_sitemap_declared": False})
        s.update(over)
        return s

    def test_unfetched_robots_is_not_a_sitemap_claim(self):
        audit = self.run_audit([page("docs/")], self._site(robots_fetched=False))
        self.assertFalse([i for i in audit["site_issues"] if "Sitemap" in i])
        orient = next(l for l in audit["layers"] if l["key"] == "orient")
        self.assertFalse([t for t in orient["issues"] if "Sitemap" in t])
        self.assertFalse([t for t in T.from_audit(audit, CFG, itertools.count(1))
                          if "Sitemap" in t["title"]])

    def test_fetched_but_undeclared_is_still_reported(self):
        """真没写 Sitemap 行的时候，工单该开还得开。"""
        audit = self.run_audit([page("docs/")], self._site(robots_fetched=True))
        self.assertTrue([i for i in audit["site_issues"] if "Sitemap" in i])
        self.assertTrue([t for t in T.from_audit(audit, CFG, itertools.count(1))
                         if "Sitemap" in t["title"]])

    def test_verify_defers_when_robots_unreachable(self):
        audit = self.run_audit([page("docs/")], self._site(robots_fetched=False))
        ok, why, _ = V.check(task("site.robots_sitemap_declared"), audit, {})
        self.assertIsNone(ok, f"应当交人工而不是判未达标，实际：{why}")

    def test_verify_fails_when_really_undeclared(self):
        audit = self.run_audit([page("docs/")], self._site(robots_fetched=True))
        ok, _, _ = V.check(task("site.robots_sitemap_declared"), audit, {})
        self.assertIs(ok, False)


class LlmsLinkSampling(Base):
    """llms.txt 的链接抽样：robots 规则拿不到时不做判定。"""

    ROBOTS = "User-agent: *\nAllow: /\nDisallow: /api/\n"
    LLMS = ("# Example\n\n## Endpoints\n"
            "- API base URL: https://example.test/api/gateway/v1\n"
            "- Docs: https://example.test/docs/\n")

    def test_api_base_url_is_not_sampled(self):
        with mock.patch.object(G, "fetch", return_value={"status": 200, "html": "ok"}):
            out = C.check_llms_txt(ROOT_URL, self.LLMS, self.ROBOTS, True)
        self.assertEqual(out["broken"], [], "/api/ 被 robots 排除，不该拿它判链接失效")
        self.assertEqual(out["total_links"], 1)

    def test_unknown_robots_skips_the_check(self):
        out = C.check_llms_txt(ROOT_URL, self.LLMS, "", False)
        self.assertIsNone(out, "robots 没拿到时排除规则失效，宁可不判")


class AssetReachability(Base):
    """站点级资产：只有真问到 404 才敢说「没有」。"""

    def _site(self, **over):
        s = dict(SITE)
        s.update(over)
        return s

    def test_unreachable_llms_is_not_reported(self):
        audit = self.run_audit([page("docs/")],
                               self._site(has_llms_txt=False, llms_txt_reachable=False))
        self.assertFalse([i for i in audit["site_issues"] if "llms.txt" in i])
        orient = next(l for l in audit["layers"] if l["key"] == "orient")
        self.assertFalse([t for t in orient["issues"] if "llms.txt" in t])
        self.assertFalse([t for t in T.from_audit(audit, CFG, itertools.count(1))
                          if "llms.txt" in t["title"]])
        cell = R.build_markdown(CFG, audit, {}, None, None, [])
        self.assertIn("未测出", cell)

    def test_missing_llms_still_reported(self):
        """404 是真没有，工单该开还得开 —— 别把判据一起删了。"""
        audit = self.run_audit([page("docs/")],
                               self._site(has_llms_txt=False, llms_txt_reachable=True))
        self.assertTrue([i for i in audit["site_issues"] if "llms.txt" in i])
        self.assertTrue([t for t in T.from_audit(audit, CFG, itertools.count(1))
                         if "llms.txt" in t["title"]])

    def test_verify_defers_when_unreachable(self):
        audit = self.run_audit([page("docs/")],
                               self._site(has_llms_txt=False, llms_txt_reachable=False))
        t = task("site.has_llms_txt")
        ok, why, _ = V.check(t, audit, {})
        self.assertIsNone(ok, f"应当交人工而不是判未达标，实际：{why}")

    def test_verify_fails_when_真的缺失(self):
        audit = self.run_audit([page("docs/")],
                               self._site(has_llms_txt=False, llms_txt_reachable=True))
        ok, _, _ = V.check(task("site.has_llms_txt"), audit, {})
        self.assertIs(ok, False)

    def test_unreachable_sitemap_is_not_a_p0(self):
        audit = self.run_audit([page("docs/")],
                               self._site(has_sitemap=False, sitemap_reachable=False,
                                          sitemap_url_count=0))
        self.assertFalse([i for i in audit["site_issues"] if "sitemap" in i])
        self.assertFalse([t for t in T.from_audit(audit, CFG, itertools.count(1))
                          if "sitemap" in t["title"]])


class UnmeasuredRowsAreNotConclusions(Base):
    """报告与交付物里的「无」不能来自一次抓取失败。

    这两处是给人做决定看的：报告里写「robots 封禁 AI 抓取器：无」、交付物里写
    「技术底座基本干净」，客户就当真了。而 robots.txt 抓不到时 ai_bots_blocked
    恒为空 —— 与「一个引擎都没被封」同形。
    """

    def _site(self, **over):
        s = dict(SITE)
        s.update(over)
        return s

    def test_report_says_unmeasured_not_none(self):
        audit = self.run_audit([page("docs/")], self._site(robots_fetched=False))
        md = R.build_markdown(CFG, audit, {}, None, None, [])
        self.assertIn("未测出（robots.txt 抓取失败）", md)
        self.assertNotIn("| robots 封禁 AI 抓取器 | 无 |", md)

    def test_report_says_none_when_robots_read(self):
        audit = self.run_audit([page("docs/")], self._site(robots_fetched=True))
        md = R.build_markdown(CFG, audit, {}, None, None, [])
        self.assertIn("| robots 封禁 AI 抓取器 | 无 |", md)

    def test_deliverable_does_not_claim_clean_baseline(self):
        audit = self.run_audit([page("docs/")], self._site(robots_fetched=False))
        plan = D.optimization_plan(SLUG)
        self.assertIn("robots.txt 本次没抓到", plan)
        self.assertNotIn("技术底座基本干净", plan)


if __name__ == "__main__":
    unittest.main()
