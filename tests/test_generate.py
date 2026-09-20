import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import generate as GEN
import geolib as G


class DeployMdCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = G.WORK
        G.WORK = Path(self._tmp.name)
        self.slug = "deploytest"
        self.pdir = G.project_dir(self.slug)
        self.adir = self.pdir / "assets"
        self.adir.mkdir(parents=True)

    def tearDown(self):
        G.WORK = self._orig
        self._tmp.cleanup()

    def write_config(self, cfg):
        (self.pdir / "geo.json").write_text(json.dumps(cfg, ensure_ascii=False), "utf-8")

    def touch(self, rel: str):
        p = self.adir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", "utf-8")


class TestDeployMdInventory(DeployMdCase):
    """清单只能列 assets/ 下真实存在的文件。

    列一个不存在的文件名，等于让开发去找一个根本没有的东西——这份清单是给
    客户的开发同学照着做的，不是给人「看完点头」的。"""

    def setUp(self):
        super().setUp()
        self.write_config({"brand": {"name": "测试品牌", "site": "https://t.example.com"},
                           "market": "cn"})

    def test_lists_only_existing_files(self):
        self.touch("llms.txt")
        self.touch("jsonld/organization.json")
        md = GEN.gen_deploy_md(self.slug)
        self.assertIn("assets/llms.txt", md)
        self.assertIn("`organization.json`", md)
        # market=cn 不产英文版；没生成归因包就不该出现在清单里
        self.assertNotIn("llms.en.txt", md)
        self.assertNotIn("attribution/", md)
        self.assertNotIn("faq-page.json", md)

    def test_every_listed_asset_exists_on_disk(self):
        for rel in ("llms.txt", "llms.en.txt", "jsonld/organization.json",
                    "jsonld/article.json", "jsonld/faq-page.json",
                    "snippets/definition.zh.html", "snippets/faq.zh.html",
                    "attribution/ga4-channel.txt", "outlines/q001.md"):
            self.touch(rel)
        md = GEN.gen_deploy_md(self.slug)
        for line in md.split("\n"):
            if not line.startswith("| `assets/"):
                continue
            rel = line.split("|")[1].strip().strip("`")[len("assets/"):]
            if "*" in rel:
                continue
            self.assertTrue((self.adir / rel).exists(), f"清单列了不存在的 {rel}")

    def test_llms_txt_section_warns_about_the_spa_trap(self):
        """SPA 把 /llms.txt 重写到前端路由上时返回 200 + 首页 HTML——
        只看「能不能访问」发现不了，所以这一步必须写进验收里。"""
        self.touch("llms.txt")
        md = GEN.gen_deploy_md(self.slug)
        self.assertIn("不是网页", md)
        self.assertIn("catch-all", md)


class TestDeployMdNoSite(DeployMdCase):
    def test_no_site_project_points_at_channels_instead(self):
        self.write_config({"brand": {"name": "无站品牌", "site": ""}, "market": "cn"})
        md = GEN.gen_deploy_md(self.slug)
        self.assertIn("没有自有网站", md)
        # 没有站就不该教人往「站点根目录」传文件
        self.assertNotIn("站点根目录，即", md)
        self.assertIn("验收", md)


if __name__ == "__main__":
    unittest.main()
