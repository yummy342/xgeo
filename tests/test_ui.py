"""前端构建产物的就位检查。

这里原来断言的是 scripts/ui.html 里的两条字符串（`<html lang="zh-CN">` 和
`document.documentElement.lang={zh:'zh-CN',...}`）——那种「正则匹配 HTML 源文件」
的检查又脆又测不到行为，而且它测的那个文件已经不再是实际托管的前端。

现在前端是 frontend/ 下的 Svelte 工程，构建产物落在 scripts/ui_dist/。
真正该在 Python 侧守住的是**产物就位**：它缺失时 dashboard 会静默回退到旧的
单文件看板（见 dashboard.py 的双分支），那是个不容易察觉的故障。

语言切换这类行为验证在 frontend/scripts/smoke.mjs（Playwright，跑真浏览器），
不在这里重复。
"""

import re
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import dashboard as D

DIST = Path(__file__).parent.parent / "scripts" / "ui_dist"


class TestBuildOutput(unittest.TestCase):
    def test_dist_exists_and_dashboard_points_at_it(self):
        self.assertTrue(
            (DIST / "index.html").is_file(),
            "缺少 scripts/ui_dist/index.html —— 跑 npm --prefix frontend run build",
        )
        self.assertEqual(D.UI_DIST, DIST,
                         "dashboard.UI_DIST 与实际产物目录不一致")

    def test_shell_references_vite_assets(self):
        html = (DIST / "index.html").read_text("utf-8")
        self.assertRegex(html, r'src="/assets/index-[\w-]+\.js"',
                         "构建产物没有引用 Vite 打出来的 js")
        self.assertRegex(html, r'href="/assets/index-[\w-]+\.css"',
                         "构建产物没有引用 Vite 打出来的 css")
        # 迁移期保留的旧辅助函数（弹窗、领域逻辑）仍以普通脚本加载
        self.assertIn("/assets/legacy-views.js", html)

    def test_assets_are_present_and_nonempty(self):
        assets = DIST / "assets"
        self.assertTrue(assets.is_dir(), "缺少 scripts/ui_dist/assets/")
        names = [p.name for p in assets.iterdir()]
        self.assertTrue(any(n.endswith(".js") for n in names), "没有 js 产物")
        self.assertTrue(any(n.endswith(".css") for n in names), "没有 css 产物")
        self.assertIn("legacy-views.js", names)

    def test_lang_attr_is_english_source(self):
        """英文是源语言（中文走字典），所以入口应当声明 lang="en"。"""
        html = (DIST / "index.html").read_text("utf-8")
        self.assertIn('<html lang="en">', html)


class TestNoStaleBundle(unittest.TestCase):
    def test_only_current_bundle_is_referenced(self):
        """index.html 引用的 js/css 必须真实存在，避免留下过期 bundle。"""
        html = (DIST / "index.html").read_text("utf-8")
        for ref in re.findall(r'(?:src|href)="(/assets/[\w.-]+)"', html):
            self.assertTrue((DIST / ref.lstrip("/")).is_file(),
                            f"index.html 引用了不存在的 {ref}")


if __name__ == "__main__":
    unittest.main()
