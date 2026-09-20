"""从 scripts/ui.html 抽出旧视图，生成 frontend/public/assets/legacy-views.js。

迁移期脚本，B6 随旧看板一起删。

    python frontend/scripts/extract-legacy.py

产物是普通脚本（非 ESM），所有函数落在全局作用域——旧代码里
onclick="go('x')" 这类内联处理器依赖这一点。被裁掉的部分改由新壳提供，
见 frontend/src/lib/legacy.js 的 installBridge()。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "scripts" / "ui.html"
OUT = ROOT / "frontend" / "public" / "assets" / "legacy-views.js"

# 1-based 闭区间
KEEP = [
    (144, 176),    # 工具函数：$ esc pct api mktLabel diagTag distRows progBar post
    (193, 195),    # head()
    (197, 1027),   # i18n 字典 + uiTranslate（B6 整体废弃）
    (1028, 1047),  # 含区块注释 + NAV + badge
    (1083, 1106),  # 含区块注释 + runAction + pollJob
    (1108, 2958),  # 含区块注释 + headline + 17 个视图
]
DROP = [
    (177, 192),    # 全局变量声明 + toast/modal/closeModal/go/popstate
    (1048, 1081),  # renderSide（侧栏已换成 Svelte）
    (2959, 3022),  # VIEWS / render / normAnalytics / load / 启动 IIFE
]

HEAD = """/* 从 scripts/ui.html 抽出的旧视图实现——迁移期桥的一半。
 *
 * 抽取区间：工具函数(144-176) / head(193-195) / i18n 字典(197-1027) /
 *          NAV+badge(1029-1047) / runAction+pollJob(1084-1106) /
 *          headline + 17 个视图(1109-2958)
 * 已裁掉，改由新壳提供（见 lib/legacy.js）：
 *          全局变量声明(177-178) / toast+modal+closeModal(180-183) /
 *          go+popstate(184-192) / renderSide(1048-1081) /
 *          VIEWS+render+normAnalytics+load+启动IIFE(2959-3022)
 *          以及 2136 行里的 EXPD（原由 load() 赋值，现由桥注入）
 *
 * 这是普通脚本（非 ESM），所有函数与变量落在全局作用域——旧代码里
 * onclick="go('x')" 这类内联处理器依赖这一点。B2-B5 逐视图替换成
 * Svelte 组件后本文件随之缩小，B6 删除。
 *
 * 由 frontend/scripts/extract-legacy.py 生成，不要手改。
 */
"""

TAIL = """
window.LEGACY_VIEWS = {
  overview:vOverview, engines:vEngines, competitors:vCompetitors, questions:vQuestions,
  samples:vSamples, siteaudit:vSiteAudit, assets:vAssets,
  gaps:vGaps, channels:vChannels, facts:vFacts, plan:vPlan, workbench:vWorkbench,
  verify:vVerify, report:vReport, settings:vSettings, publishing:vPublishing, onboard:vOnboard,
};
// 新壳的侧栏复用这三者（普通脚本的 const 不挂 window，必须显式导出），
// 免得导航结构和当前语言在两套前端之间漂移。
window.GL_NAV = NAV;
window.GL_BADGE = badge;
window.GL_ULANG = ULANG;

// 这两个是 const 箭头函数，不会像 function 声明那样自动成为 window 属性，
// 新组件里要按名字调用就得显式挂上（progBar/chanOpen 那些是 function 声明，
// 本来就在 window 上，不必列）。
window.diagTag = diagTag;
window.distRows = distRows;
"""

# EXPD 原本由 load() 赋值，而 load 已被裁掉。留着这个声明会让视图永远读到
# null，所以摘掉它，改由桥注入 window.EXPD（裸引用会回落到 global object）。
EXPD_OLD = "let KEYS=null,PROJECTS=null,SET_CFG=null,PUB=null,SET_HTML='',EXPD=null;"
EXPD_NEW = "let KEYS=null,PROJECTS=null,SET_CFG=null,PUB=null,SET_HTML='';"


def main():
    lines = SRC.read_text(encoding="utf-8").split("\n")

    # 保留与删除必须严丝合缝地覆盖 144-3022，漏一行就可能丢代码
    kept = {i for a, b in KEEP for i in range(a, b + 1)}
    dropped = {i for a, b in DROP for i in range(a, b + 1)}
    assert not (kept & dropped), "保留与删除区间重叠"
    unclassified = [i for i in range(144, 3023) if i not in kept and i not in dropped]
    nonblank = [i for i in unclassified if lines[i - 1].strip()]
    assert not nonblank, f"有未归类的非空行: {nonblank}"

    body = []
    for a, b in KEEP:
        body.extend(lines[i - 1] for i in range(a, b + 1))
        body.append("")
    text = "\n".join(body)

    assert text.count(EXPD_OLD) == 1, f"EXPD 声明命中 {text.count(EXPD_OLD)} 次"
    text = text.replace(EXPD_OLD, EXPD_NEW)

    OUT.write_text(HEAD + text + TAIL, encoding="utf-8")
    print(f"写出 {OUT.relative_to(ROOT)}  {OUT.stat().st_size} 字节")


if __name__ == "__main__":
    main()
