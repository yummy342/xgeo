"""从 scripts/ui.html 抽出旧辅助函数，生成 frontend/public/assets/legacy-views.js。

迁移收尾阶段的脚本，B6 之后连同这个文件一起删。

    python frontend/scripts/extract-legacy.py

17 个视图已经全部迁到 Svelte，这里只保留还被新组件调用的那部分函数：
纯工具、几个 HTML 片段生成器、弹窗、任务动作。

保留名单不是拍脑袋定的——它是 `grep -rhoE "window\\.[a-zA-Z_]+" frontend/src`
的结果。改这个名单前先重跑那条命令。

产物是普通脚本（非 ESM），函数落在全局作用域，由 lib/legacy.js 的
installBridge() 注入它们读的那些全局（D / SLUG / ST / RUNNING …）。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "scripts" / "ui.html"
OUT = ROOT / "frontend" / "public" / "assets" / "legacy-views.js"

# 脚本区在 ui.html 里的范围
SCRIPT_FROM, SCRIPT_TO = 144, 2958

# 仍然被 frontend/src 里某个模块调用的顶层函数/常量。
# 名单来源：grep -rhoE "window\.[a-zA-Z_][a-zA-Z0-9_]*" frontend/src | sort -u
KEEP = {
    # 纯工具（新组件里也有同名实现，但 legacy 内部互相调用，得留着）
    "$", "esc", "pct", "api", "mktLabel", "post", "head",
    # HTML 片段生成器
    "diagTag", "distRows", "progBar", "demandTag", "demandRank", "demandSort",
    # 领域逻辑（等后端提供接口后可以搬到后端）
    "headline", "chanFitQs", "distOf", "taskWbTarget",
    # 弹窗与动作
    "chanOpen", "taskModal", "setTask", "wbFromTask", "factModal", "editFactsSrc",
    "sampleModal", "addFact", "saveFact", "delFact", "editQuestions", "saveQuestions",
    # 下面这些不是被组件直接调用，而是被保留的弹窗内部调用——
    # 光看 window.* 的扫描结果会漏掉它们。
    "saveFactsSrc",
    # 样本复核链：Samples 组件目前只做展示，编辑仍走 legacy 的 sampleModal，
    # 它保存后靠 SMP=null + loadSamples() 刷新（loadSamples 末尾会调 render()，
    # 正好 bump 组件依赖的那个 tick）。整改时把复核弹窗也搬进组件，这几个就能删。
    # SMP 那行同时声明了 SMPF（`let SMP=null,SMPF={...}`），块按第一个名字归档，
    # 所以只列 SMP 就够。
    "saveSample", "delSample", "SMP", "loadSamples",
    "showMethod", "expandModal", "expAddIdx", "expAdd",
    "pendPubModal", "pubModal", "doPublishSel",
    "onePager", "editSheet", "importSheet",
    "editPub", "savePub", "editKey", "editConfig", "switchProject", "switchModal",
    "saveCfg", "saveKey",
    "auditFlag", "distToggle",
    "obCreate", "obRetry",
    "runAction", "pollJob", "stopJob", "showLog", "setMonitor",
    "setLang",
    # 侧栏复用
    "NAV", "badge", "ULANG",
}

HEAD = """/* 从 scripts/ui.html 抽出的旧辅助函数——迁移收尾阶段的遗留部分。
 *
 * 17 个视图已全部迁到 Svelte。这里只剩下还被新组件调用的那批：
 * 纯工具、HTML 片段生成器、弹窗、任务动作。保留名单由
 * frontend/scripts/extract-legacy.py 维护，来源是对 frontend/src 的扫描。
 *
 * 这是普通脚本（非 ESM），函数落在全局作用域。它们读的 D / SLUG / ST /
 * RUNNING 等由 lib/legacy.js 的 installBridge() 用 getter 注入。
 *
 * 下一步：把这里的弹窗逐个改写成 Svelte 组件，桥就能拆掉了。
 * 由 frontend/scripts/extract-legacy.py 生成，不要手改。
 */
"""

TAIL = """
// 新壳的侧栏复用这三者（普通脚本的 const 不挂 window，必须显式导出）
window.GL_NAV = NAV;
window.GL_BADGE = badge;
window.GL_ULANG = ULANG;

// const 箭头函数不会自动成为 window 属性，按名调用就得显式挂上
// （progBar/chanOpen 那些是 function 声明，本来就在 window 上）
window.diagTag = diagTag;
window.distRows = distRows;
"""

# 顶层的声明起始行：function / const / let / async function
DECL = re.compile(r"^(?:async\s+)?(?:function\s+([A-Za-z_$][\w$]*)"
                  r"|(?:const|let|var)\s+([A-Za-z_$][\w$]*))")


def top_level_blocks(lines):
    """按顶层声明切块。返回 [(名字, 起行, 止行, 行列表)]，行号 0-based。"""
    starts = []
    for i, ln in enumerate(lines):
        m = DECL.match(ln)
        if m:
            starts.append((m.group(1) or m.group(2), i))
    blocks = []
    for idx, (name, start) in enumerate(starts):
        end = starts[idx + 1][1] - 1 if idx + 1 < len(starts) else len(lines) - 1
        blocks.append((name, start, end, lines[start:end + 1]))
    return blocks


# 由桥或组件注入到 window 的名字：保留的函数引用它们不算问题
INJECTED = {
    "D", "SLUG", "ST", "R", "ACTIONS", "EXPD", "RUNNING", "LASTJOB", "LOGOFF", "POLL",
    "toast", "modal", "closeModal", "go", "render", "renderSide", "load",
    # 由组件自己挂到 window 上的缓存
    "KEYS", "PUB", "PROJECTS", "SET_CFG", "WB", "FACT_CARDS", "AS",
}


def check_dependencies(blocks, order, kept_names):
    """保留的函数不能引用被丢弃的符号。

    光靠扫描 window.* 定名单会漏：editFactsSrc 调的是裸名 saveFactsSrc，
    不是 window.saveFactsSrc，扫描结果里没有它。这个自检就是为此加的。
    """
    dropped = [n for n in order if n not in kept_names]
    bad = []
    for name in kept_names:
        body = "\n".join(blocks[name])
        for d in dropped:
            if d in INJECTED:
                continue
            if re.search(r"\b" + re.escape(d) + r"\b", body):
                bad.append(f"{name} → {d}")
    assert not bad, "保留的函数引用了被丢弃的符号:\n  " + "\n  ".join(bad)


def main():
    src = SRC.read_text(encoding="utf-8").split("\n")
    region = src[SCRIPT_FROM - 1:SCRIPT_TO]

    blocks = top_level_blocks(region)
    by_name = {n: b for n, _s, _e, b in blocks}
    order = [n for n, _s, _e, _b in blocks]
    kept, dropped = [], []
    for name, _s, _e, body in blocks:
        (kept if name in KEEP else dropped).append((name, body))

    # 名单里的名字必须都能找到；找不到说明 ui.html 改了名而这里没跟上
    found = {n for n, _ in kept}
    missing = KEEP - found
    assert not missing, f"保留名单里这些名字在 ui.html 中不存在: {sorted(missing)}"

    check_dependencies({n: b for n, b in kept}, order, found)

    out = [HEAD]
    for _name, body in kept:
        out.extend(body)
        out.append("")
    out.append(TAIL)

    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"保留 {len(kept)} 块 / 丢弃 {len(dropped)} 块")
    print(f"写出 {OUT.relative_to(ROOT)}  {OUT.stat().st_size} 字节")
    print("丢弃的顶层声明：")
    print("  " + ", ".join(n for n, _ in dropped))


if __name__ == "__main__":
    main()
