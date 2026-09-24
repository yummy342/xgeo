#!/usr/bin/env python3
"""GEO 自动化管线 CLI。

  python3 scripts/geo.py init --url https://example.com --name 品牌名
  python3 scripts/geo.py crawl        --slug example
  python3 scripts/geo.py audit        --slug example
  python3 scripts/geo.py sample       --slug example
  python3 scripts/geo.py sample-sheet --slug example
  python3 scripts/geo.py sample-import --slug example --file work/example/samples/2026-07-26-manual.md
  python3 scripts/geo.py report       --slug example
  python3 scripts/geo.py cycle        --slug example      # 一条命令跑完整期
  python3 scripts/geo.py list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import geolib as G  # noqa: E402
except ModuleNotFoundError as e:
    raise SystemExit(f"缺少依赖：{e.name}。请先 pip3 install requests beautifulsoup4 lxml") from e


DEFAULT_PLATFORMS = {
    "cn": ["glm", "doubao", "deepseek", "kimi", "minimax", "nano_ai", "baidu"],
    "global": ["gemini", "openai", "claude", "grok", "perplexity", "chatgpt", "google_aio"],
    "both": ["glm", "doubao", "deepseek", "kimi", "minimax", "nano_ai", "baidu",
             "gemini", "openai", "claude", "grok", "perplexity", "chatgpt", "google_aio"],
}


def cmd_init(a):
    # 无站点模式：电商商品、线下品牌、小程序等没有自有官网的对象同样能做 GEO。
    # 抓取/体检/站内资产不适用，采样、竞品、阵地、内容、验收全部照常。
    no_site = getattr(a, "no_site", False) or not (a.url or "").strip()
    if no_site:
        if not a.name:
            G.die("无站点项目必须用 --name 指定品牌/商品名（没有官网可供推断）")
        url, host = "", ""
        slug = a.slug or G.slugify(a.name)
    else:
        url = a.url.rstrip("/")
        if not url.startswith("http"):
            url = "https://" + url
        host = urlparse(url).netloc.removeprefix("www.")
        slug = a.slug or G.slugify(host.split(".")[0])

    # 已存在的项目绝不覆盖：geo.json 里有问题库、竞品、事实口径，
    # 覆盖等于把一期的人工投入清零。要重建必须显式加 --force。
    existing = G.project_dir(slug) / "geo.json"
    if existing.exists() and not getattr(a, "force", False):
        cur = G.read_json(existing, {})
        G.die(f"项目 `{slug}` 已存在（问题 {len(cur.get('questions', []))} 题、"
              f"竞品 {len(cur.get('competitors', []))} 个）。换一个 --slug，"
              f"或确认要清空后加 --force")

    name = a.name
    if not name and url:
        res = G.fetch(url)
        # 只在 200 时用页面标题推断品牌名：404 页的 <title> 是站点的错误页标题，
        # 拿它当品牌名会得到一个离谱的名字（而这个字段会进 facts.md 的「规范名」）。
        if res["status"] == 200 and res["html"]:
            soup = G.parse_html(res["html"])
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            name = (title.split("|")[0].split("-")[0].split("_")[0].strip() or host)[:40]
        else:
            name = host

    cfg = {
        "slug": slug,
        "created_at": G.now_iso(),
        "market": a.market,
        "brand": {
            "name": name,
            "aliases": [],
            "site": url,
            "products": [],
            "industry": "",
            "target_users": "",
            "business_goal": "",
        },
        "competitors": [],
        "platforms": DEFAULT_PLATFORMS[a.market],
        "pages": {"seed": [], "max": a.max_pages},
        "questions": [],
        "materials": [],
        "targets": {"mention_rate": 0.5, "top3_rate": 0.3, "avg_page_score": 75},
        "notes": "questions / competitors / aliases 由 Claude 按 SKILL.md 步骤 2 填充",
    }
    G.save_config(slug, cfg)
    for sub in ("evidence", "samples", "metrics", "reports", "history", "content"):
        (G.project_dir(slug) / sub).mkdir(parents=True, exist_ok=True)

    # 无站点项目：材料文本取代官网正文，成为品牌事实/竞品/问题库的推导底座
    mat_path = G.project_dir(slug) / "content" / "materials.md"
    materials = (getattr(a, "materials", "") or "").strip()
    if materials:
        src = Path(materials)
        text = src.read_text("utf-8") if src.exists() else materials
        mat_path.write_text(text, "utf-8")
    elif no_site and not mat_path.exists():
        mat_path.write_text(
            f"# {name} · 商品/品牌介绍材料\n\n"
            "> 无自有官网的项目，这份材料取代官网正文，是推导品牌事实、竞品与问题库的唯一依据。\n"
            "> 写得越具体，推导越准；不知道的留空，不要编——bootstrap 会把空缺标成「待确认」。\n\n"
            "## 它是什么\n（一句话定义：面向谁、属于什么品类、解决什么问题）\n\n"
            "## 卖点与关键数字\n（规格、价格区间、产能、认证、销量等可核实的事实）\n\n"
            "## 目标用户与典型场景\n\n"
            "## 已知竞品\n（真实存在的品牌名，一行一个）\n\n"
            "## 售卖/曝光渠道\n（天猫/京东/抖音店铺、小程序、线下门店等）\n", "utf-8")

    print(f"[geo] 项目已创建：{G.project_dir(slug)/'geo.json'}（品牌：{name}）")
    if no_site:
        print(f"[geo] 无站点模式：抓取/体检/站内资产不适用，其余流程照常")
        print(f"[geo] 下一步：填写 {mat_path} 后跑 bootstrap")
    else:
        print("[geo] 下一步：让 Claude 补全 brand/competitors/questions，再跑 crawl")
    return cfg


def cmd_bootstrap(a):
    import bootstrap

    bootstrap.run(a.slug, skip_llm=a.skip_llm)


def cmd_deliverables(a):
    import deliverables

    deliverables.run(a.slug)


def cmd_new(a):
    """只给一个网址，跑完全流程出三份交付物。"""
    import audit as A
    import blueprint as BP
    import bootstrap
    import crawl as C
    import deliver
    import deliverables as DV
    import generate
    import report as Rp
    import sample as S
    import tasks
    import verify as V

    G.info("═══ 1/9 建项目 ═══")
    cfg = cmd_init(a)
    slug = cfg["slug"]
    G.info("═══ 2/9 抓取官网 ═══")
    C.run(slug, max_pages=a.max_pages)
    G.info("═══ 3/9 体检 ═══")
    A.run(slug)
    G.info("═══ 4/9 自动推导品牌事实、竞品与问题库 ═══")
    bootstrap.run(slug, skip_llm=a.skip_llm)
    G.info("═══ 5/9 重跑体检（问题库影响对题性评分）═══")
    A.run(slug)
    G.info("═══ 6/9 AI 答案采样 ═══")
    if a.no_sample:
        G.info("跳过：--no-sample")
    elif not G.load_config(slug).get("questions"):
        G.info("跳过：问题库为空")
    else:
        try:
            S.run(slug, limit=a.limit)
        except Exception as e:  # noqa: BLE001
            G.info(f"采样跳过：{type(e).__name__}: {e}")
    G.info("═══ 7/9 工单与建设蓝图 ═══")
    tasks.build(slug)
    BP.build(slug)
    G.info("═══ 8/9 资产与报告 ═══")
    generate.run(slug, with_draft=a.draft, draft_limit=a.draft_limit)
    Rp.run(slug)
    G.info("═══ 9/9 三份交付物 + 交付包 ═══")
    DV.run(slug)
    try:
        V.run(slug, recrawl=False)
    except Exception as e:  # noqa: BLE001
        G.info(f"验收失败：{e}")
    deliver.run(slug)
    G.info("")
    G.info(f"完成。交付物在 work/{slug}/deliverables/：")
    G.info("  1-GEO诊断报告.html   现在什么样")
    G.info("  2-GEO优化方案.html   应该改成什么样")
    G.info("  3-GEO执行方案.html   谁在什么时候做什么")
    G.info("")
    G.info("下一步：打开工作台核对自动推导的品牌事实与问题库（标「待确认」的需人工补齐）")
    G.info("  python3 scripts/geo.py ui")


def cmd_autopilot(a):
    """对已建好的项目跑完整引导：推导底座 → 采样 → 工单 → 资产 → 三份交付物。"""
    import audit as A
    import blueprint as BP
    import bootstrap
    import crawl as C
    import deliver
    import deliverables as DV
    import generate
    import report as Rp
    import sample as S
    import tasks
    import verify as V

    cfg = G.load_config(a.slug)
    G.info("═══ 1/8 抓取官网 ═══")
    C.run(a.slug)
    G.info("═══ 2/8 体检 ═══")
    A.run(a.slug)
    if not cfg.get("questions"):
        G.info("═══ 3/8 自动推导品牌事实、竞品与问题库 ═══")
        bootstrap.run(a.slug, skip_llm=a.skip_llm)
        A.run(a.slug)
    else:
        G.info("═══ 3/8 已有问题库，跳过自动推导 ═══")
    G.info("═══ 4/8 AI 答案采样 ═══")
    if a.no_sample:
        G.info("跳过：--no-sample")
    elif G.load_config(a.slug).get("questions"):
        try:
            S.run(a.slug, limit=a.limit)
        except Exception as e:  # noqa: BLE001
            G.info(f"采样跳过：{type(e).__name__}: {e}")
    G.info("═══ 5/8 工单与建设蓝图 ═══")
    tasks.build(a.slug)
    BP.build(a.slug)
    G.info("═══ 6/8 资产与报告 ═══")
    generate.run(a.slug)
    Rp.run(a.slug)
    G.info("═══ 7/8 三份交付物 ═══")
    DV.run(a.slug)
    G.info("═══ 8/8 验收与打包 ═══")
    try:
        V.run(a.slug, recrawl=False)
    except Exception as e:  # noqa: BLE001
        G.info(f"验收失败：{e}")
    deliver.run(a.slug)
    G.info("完成。三份交付物在 deliverables/，标「待确认」的品牌事实需人工补齐。")


def cmd_crawl(a):
    import crawl

    crawl.run(a.slug, max_pages=a.max_pages)


def cmd_audit(a):
    import audit

    audit.run(a.slug)


def cmd_sample(a):
    import sample

    sample.run(a.slug, platforms=a.platforms.split(",") if a.platforms else None,
               repeat=a.repeat, limit=a.limit)


def cmd_sheet(a):
    import sample

    sample.sheet(a.slug, intent=a.intent, limit=a.limit)


def cmd_import(a):
    import sample

    sample.sample_import(a.slug, a.file)


def cmd_report(a):
    import report

    report.run(a.slug)


def cmd_cycle(a):
    import audit
    import crawl
    import report
    import sample

    G.info("=== 1/4 抓取 ===")
    crawl.run(a.slug, max_pages=a.max_pages)
    G.info("=== 2/4 体检 ===")
    audit.run(a.slug)
    G.info("=== 3/4 采样 ===")
    # 采样失败不能把整期带崩：报告和待办比采样更重要
    if not G.load_config(a.slug).get("questions"):
        G.info("跳过采样：geo.json 里还没有问题库（见 SKILL.md 步骤 2）")
    else:
        try:
            sample.run(a.slug, limit=a.limit)
        except Exception as e:  # noqa: BLE001
            G.info(f"采样跳过：{type(e).__name__}: {e}")
    G.info("=== 4/4 报告 ===")
    report.run(a.slug)
    # 一期跑完立刻给对照：复测的全部意义就在这一步，
    # 等用户自己记得回去翻页面，等于这一步没做。
    _print_effect(a.slug)


def cmd_expand(a):
    import expand
    expand.run(a.slug, use_llm=not a.no_llm)


def cmd_plan(a):
    import tasks

    tasks.build(a.slug)


def cmd_blueprint(a):
    import blueprint

    blueprint.build(a.slug)


def cmd_generate(a):
    import generate

    generate.run(a.slug, which=a.asset.split(",") if a.asset else None,
                 with_draft=a.draft, draft_limit=a.draft_limit)


def cmd_variants(a):
    """同一篇出几个角度，供人挑一个。"""
    import generate

    generate.variants(a.slug, qid=a.qid, n=a.n, provider=a.provider)


def cmd_pick(a):
    """人工选定版本 —— 选定之后才进发布流程。"""
    import generate

    generate.pick(a.slug, a.qid, a.variant)


def cmd_lint(a):
    import generate

    rep = generate.lint_all(a.slug)
    if not rep["files"]:
        print("没有 AI 初稿可检查（用 generate --draft 生成）")
        return
    print(f"\n检查 {len(rep['files'])} 份初稿，共 {rep['total_issues']} 项待核实（高风险 {rep['high']} 项）")
    for fn, issues in rep["files"].items():
        if not issues:
            print(f"\n  {fn}：无风险")
            continue
        print(f"\n  {fn}")
        for i in issues:
            print(f"    [{i['level']}] {i['type']}：{i['detail']}")
            print(f"          …{i['excerpt'][:76]}")
    print("\n高风险项必须处理后才能发布；未核实数字需补来源与核验日期。\n")


def cmd_verify(a):
    import verify

    verify.run(a.slug, recrawl=not a.no_recrawl)


def cmd_deliver(a):
    import deliver

    deliver.run(a.slug)


def _print_prepared(r: dict, slug: str) -> None:
    """把备好的内容打到终端。

    **不写文件也不进剪贴板**：CLI 常跑在服务器上（隔着 ssh），写文件没用、进剪贴板
    更不可能。这里只负责「看得到、选得中」，复制由前端的按钮做。
    """
    G.info(f"已备好（本条不会自动发出）：{r['name']} · 记录 id {r['id']}")
    if r.get("title"):
        G.info(f"  标题（{len(r['title'])} 字）: {r['title']}")
    else:
        G.info("  标题：无（该渠道的标题并入正文首行）")
    if r.get("tags_text"):
        G.info(f"  标签: {r['tags_text']}")
    if r.get("publish_url"):
        G.info(f"  发布页: {r['publish_url']}")
    elif r.get("missing_placeholders"):
        G.info(f"  发布页：待配置（缺 {'、'.join(r['missing_placeholders'])}，先用渠道配置补上）")
    else:
        G.info("  发布页：待核实 —— 先手动打开站点确认发文入口")
    if r.get("editor_hint"):
        G.info(f"  编辑器提示: {r['editor_hint']}")
    for w in r.get("warnings") or []:
        G.info(f"  警告: {w}")
    print()
    print(r.get("body") or "")
    print()
    G.info(f"粘贴发布完成后回填：geo.py publish-mark --slug {slug} "
           f"--platform {r['code']} --id {r['id']} --url <公开链接>")
    if r.get("link_hint"):
        G.info(f"  链接从哪来: {r['link_hint']}")


def cmd_publish(a):
    import publish

    via = getattr(a, "via", None)
    paths = publish.paths_of(a.platform)
    # 指了 --via 但那条通路不存在时要明说。否则「--via api 打在只有半自动的渠道上」
    # 会安静地走半自动、退出码 0，用户以为发到 API 了。
    if via and via not in paths:
        G.die(f"「{publish.PUBLISHERS[a.platform]['name']}」没有 {via} 通路"
              f"（可选：{'/'.join(paths) or '无'}）")
    # 半自动渠道不进发布流程，只备好并打印。**这不是失败**，所以不能用 G.die。
    if publish.resolve_path(a.platform, a.slug, force=via) == "semi":
        # force 必须一路传下去：不传的话，用户明明指了 --via semi，
        # prepare 里会按默认（凭证齐 → api）再判一次，回一句
        # 「当前走自动发布通路，用 geo.py publish 即可」—— 正是他刚敲的那条命令。
        r = publish.prepare(a.slug, a.platform, a.path, a.title or "", force=via)
        if not r.get("ok"):
            G.die(f"备好失败：{r.get('error')}")
        _print_prepared(r, a.slug)
        return
    r = publish.publish(a.slug, a.platform, a.path, a.title or "",
                        publish_now=a.published, force=via)
    if r.get("ok"):
        G.info(f"已发布：{r.get('url') or r.get('note') or 'ok'}")
    else:
        G.die(f"发布失败：{r.get('error')}")


def cmd_publish_mark(a):
    """半自动渠道：人工发布完成后回填公开链接（或作废那条待办）。"""
    import publish

    r = publish.record_manual(a.slug, a.platform, a.path or "", a.id,
                              url=a.url or "", note=a.note or "", cancel=a.cancel)
    if not r.get("ok"):
        G.die(f"回填失败：{r.get('error')}")
    if r.get("cancelled"):
        G.info(f"已作废待办 {a.id}")
        return
    G.info(f"已记入发布记录：{r['url']}")
    if r.get("dist_ticked"):
        G.info(f"  顺带勾上分发清单：{'、'.join(r['dist_ticked'])}")


def cmd_task(a):
    import tasks

    if a.status:
        try:
            tasks.set_status(a.slug, a.id, a.status, a.note or "")
        except KeyError as e:
            G.die(e.args[0] if e.args else str(e))
    else:
        data = tasks.load(a.slug)
        t = next((x for x in data["tasks"] if x["id"] == a.id), None)
        if not t:
            G.die(f"找不到工单 {a.id}")
        print(json.dumps(t, ensure_ascii=False, indent=2))


def _print_effect(slug: str) -> None:
    """效果趋势。跟 trend 子命令共用 analytics.trend/question_delta，
    这里只负责把它印出来——命令行看不到的指标，等于没有。

    样本只有一期时不给结论：单期数字没有对照，说了也是噪音。
    """
    import analytics
    tr = analytics.trend(slug)
    if not tr:
        print("\n  效果趋势   还没有采样数据")
        return
    print(f"\n  效果趋势（{len(tr)} 期）")
    for p in tr[-6:]:
        mn = f"{p['mention'] * 100:5.1f}%" if p["mention"] is not None else "    —"
        ct = f"{p['cite'] * 100:5.1f}%" if p["cite"] is not None else "    —"
        print(f"    {p['date']}   提及 {mn}   引用 {ct}   {p['samples']} 样本")
    if len(tr) < 2:
        print("    只有一期，等下一期才有对照")
        return
    b, n = tr[-2], tr[-1]
    moved = []
    if (n["mention"] or 0) > (b["mention"] or 0):
        moved.append("提及率上升")
    if (n["cite"] or 0) > (b["cite"] or 0):
        moved.append("引用率上升")
    up = [x for x in analytics.question_delta(slug) if (x["after"] or 0) > (x["before"] or 0)]
    if moved or up:
        tail = f"，{len(up)} 道题上升" if up else ""
        print(f"    ↑ {b['date']} → {n['date']}：{'、'.join(moved) or '有题目上升'}{tail}")
    else:
        print(f"    · {b['date']} → {n['date']}：两期持平，提及率与引用率均未变化")


def cmd_status(a):
    import sample as S
    import tasks

    cfg = G.load_config(a.slug)
    audit = G.read_json(G.project_dir(a.slug) / "audit.json", {})
    data = tasks.load(a.slug)
    s = data.get("summary", {})
    print(f"\n{cfg['brand']['name']}  ({cfg.get('market')})  {cfg['brand']['site']}")
    print(f"  站点均分 {audit.get('avg_score', '—')}  页面 {audit.get('page_count', '—')}"
          f"  工单 {s.get('total', 0)} 条（可自动验收 {s.get('auto_verifiable', 0)}）")
    u = S.usage_summary(a.slug)
    if u["calls"]:
        tail = f"，另有 {u['unknown']} 次未回传用量" if u["unknown"] else ""
        print(f"  采样用量 输入 {u['in']:,} / 输出 {u['out']:,} tokens"
              f"（{u['calls']} 次调用{tail}）")
    elif u["unknown"]:
        # 一次都没记上（记账之前采的样本，或中转不回传 usage）——报「未记录」而不是 0，
        # 「不知道花了多少」和「没花钱」不是一回事
        print(f"  采样用量 未记录（{u['unknown']} 次调用未回传用量）")
    _print_effect(a.slug)
    if not data.get("tasks"):
        print("  还没有工单，运行 plan 生成\n")
        return
    order = {"P0": 0, "P1": 1, "P2": 2}
    for pri in ("P0", "P1", "P2"):
        rows = [t for t in data["tasks"] if t["priority"] == pri]
        if not rows:
            continue
        done = sum(1 for t in rows if t["status"] == "done")
        print(f"\n  {pri}  {done}/{len(rows)} 完成")
        for t in sorted(rows, key=lambda x: (x["status"] != "todo", x["package"])):
            mark = {"done": "✓", "doing": "◐", "blocked": "✗", "wontfix": "—"}.get(t["status"], "·")
            print(f"    {mark} {t['id']} [{t['package']}/{t['owner']}/{t['market']}] {t['title']}")
    print()


def cmd_serve(a):
    """一条命令跑完整个服务周期：诊断 → 方案 → 资产 → 验收 → 交付。"""
    import audit as A
    import crawl as C
    import deliver
    import generate
    import report as Rp
    import sample as S
    import tasks
    import verify as V

    G.info("═══ 1/7 抓取 ═══")
    C.run(a.slug, max_pages=a.max_pages)
    G.info("═══ 2/7 体检 ═══")
    A.run(a.slug)
    G.info("═══ 3/7 AI 答案采样 ═══")
    if not G.load_config(a.slug).get("questions"):
        G.info("跳过：问题库为空（见 SKILL.md 步骤 2）")
    elif a.no_sample:
        G.info("跳过：--no-sample")
    else:
        try:
            S.run(a.slug, limit=a.limit)
        except Exception as e:  # noqa: BLE001
            G.info(f"采样跳过：{type(e).__name__}: {e}")
    try:
        import expand
        expand.run(a.slug)
    except Exception as e:  # noqa: BLE001
        G.info(f"拓词跳过：{type(e).__name__}: {e}")
    G.info("═══ 4/7 生成工单与建设蓝图 ═══")
    tasks.build(a.slug)
    import blueprint
    blueprint.build(a.slug)
    G.info("═══ 5/7 生成资产 ═══")
    generate.run(a.slug, with_draft=a.draft, draft_limit=a.draft_limit)
    G.info("═══ 6/7 报告 ═══")
    Rp.run(a.slug)
    G.info("═══ 7/7 验收上期工单 ═══")
    V.run(a.slug, recrawl=False)
    G.info("═══ 打包交付 ═══")
    deliver.run(a.slug)


def cmd_ui(a):
    import dashboard

    dashboard.run(port=a.port, open_browser=not a.no_open)


def cmd_list(a):
    if not G.WORK.exists():
        print("还没有任何项目")
        return
    for d in sorted(G.WORK.iterdir()):
        cfg_path = d / "geo.json"
        if cfg_path.exists():
            cfg = G.read_json(cfg_path, {})
            reports = sorted((d / "reports").glob("2*")) if (d / "reports").exists() else []
            last = reports[-1].name if reports else "—"
            print(f"{d.name:20s} {cfg.get('brand', {}).get('name', ''):22s} 问题 {len(cfg.get('questions', [])):3d}  最近报告 {last}")


def main():
    p = argparse.ArgumentParser(prog="geo", description="GEO 自动化管线")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="新建项目")
    s.add_argument("--url", default="", help="官网地址；无自有网站时留空并加 --no-site")
    s.add_argument("--no-site", action="store_true", dest="no_site",
                   help="无自有网站（电商商品/线下品牌/小程序等），需配 --name")
    s.add_argument("--materials", default="",
                   help="商品/品牌介绍材料：文件路径或直接给文本，取代官网正文作为推导底座")
    s.add_argument("--name")
    s.add_argument("--slug")
    s.add_argument("--market", choices=["cn", "global", "both"], default="cn")
    s.add_argument("--max-pages", type=int, default=25, dest="max_pages")
    s.add_argument("--force", action="store_true", help="项目已存在时清空重建（危险）")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("new", help="★ 只给一个网址，全自动出三份交付物")
    s.add_argument("--url", required=True)
    s.add_argument("--name")
    s.add_argument("--slug")
    s.add_argument("--market", choices=["cn", "global", "both"], default="both")
    s.add_argument("--max-pages", type=int, default=25, dest="max_pages")
    s.add_argument("--limit", type=int, default=None, help="采样只跑前 N 题")
    s.add_argument("--no-sample", action="store_true", dest="no_sample")
    s.add_argument("--skip-llm", action="store_true", dest="skip_llm", help="不用 LLM 推导底座")
    s.add_argument("--draft", action="store_true")
    s.add_argument("--draft-limit", type=int, default=3, dest="draft_limit")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_new)

    s = sub.add_parser("autopilot", help="对已有项目跑完整引导流程")
    s.add_argument("--slug", required=True)
    s.add_argument("--limit", type=int, default=None)
    s.add_argument("--no-sample", action="store_true", dest="no_sample")
    s.add_argument("--skip-llm", action="store_true", dest="skip_llm")
    s.set_defaults(func=cmd_autopilot)

    s = sub.add_parser("bootstrap", help="从官网正文自动推导品牌事实、竞品与问题库")
    s.add_argument("--slug", required=True)
    s.add_argument("--skip-llm", action="store_true", dest="skip_llm")
    s.set_defaults(func=cmd_bootstrap)

    s = sub.add_parser("deliverables", help="出三份正式交付物（诊断/优化/执行）")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_deliverables)

    s = sub.add_parser("crawl", help="抓取官网")
    s.add_argument("--slug", required=True)
    s.add_argument("--max-pages", type=int, default=None, dest="max_pages")
    s.set_defaults(func=cmd_crawl)

    s = sub.add_parser("audit", help="页面 GEO 体检")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_audit)

    s = sub.add_parser("sample", help="API 平台答案采样")
    s.add_argument("--slug", required=True)
    s.add_argument("--platforms", help="逗号分隔，默认取 geo.json 里有 Key 的")
    s.add_argument("--repeat", type=int, default=1, help="每题重复采样次数")
    s.add_argument("--limit", type=int, default=None, help="只跑前 N 个问题")
    s.set_defaults(func=cmd_sample)

    s = sub.add_parser("sample-sheet", help="导出人工/浏览器采样表")
    s.add_argument("--slug", required=True)
    s.add_argument("--intent", choices=["buyer"], default=None,
                   help="buyer = 只出买家意图题（价格/推荐/比较/替代），适合每周轻量核查")
    s.add_argument("--limit", type=int, default=None, help="每平台最多题数（周检建议 15–20）")
    s.set_defaults(func=cmd_sheet)

    s = sub.add_parser("sample-import", help="导入人工采样表")
    s.add_argument("--slug", required=True)
    s.add_argument("--file", required=True)
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("report", help="生成报告")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("cycle", help="抓取→体检→采样→报告 一次跑完")
    s.add_argument("--slug", required=True)
    s.add_argument("--max-pages", type=int, default=None, dest="max_pages")
    s.add_argument("--limit", type=int, default=None)
    s.set_defaults(func=cmd_cycle)

    s = sub.add_parser("expand", help="拓词：百度下拉/Google suggest 扩出真实需求候选题")
    s.add_argument("--slug", required=True)
    s.add_argument("--no-llm", action="store_true", dest="no_llm",
                   help="不调 LLM 转写问句，用模板兜底")
    s.set_defaults(func=cmd_expand)

    s = sub.add_parser("plan", help="诊断结果 → 结构化工单（含验收标准）")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("blueprint", help="GEO 建设蓝图：在哪些平台建、建什么内容、覆盖度多少")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_blueprint)

    s = sub.add_parser("generate", help="产出可直接部署的资产（llms.txt/JSON-LD/片段/大纲）")
    s.add_argument("--slug", required=True)
    s.add_argument("--asset", help="逗号分隔：llms,jsonld,snippets,outlines,attribution")
    s.add_argument("--draft", action="store_true", help="额外调用 LLM 出文章初稿")
    s.add_argument("--draft-limit", type=int, default=3, dest="draft_limit")
    s.set_defaults(func=cmd_generate)

    s = sub.add_parser("variants", help="同一篇出多个叙事角度，供人挑一个（发布前的人工环节）")
    s.add_argument("--slug", required=True)
    s.add_argument("--qid", help="目标问题 ID；省略则取第一个问题")
    s.add_argument("--n", type=int, default=3, help="出几个角度（最多 3：权威型/实用型/对比型）")
    s.add_argument("--provider", help="指定用哪个引擎起草；省略则自动挑")
    s.set_defaults(func=cmd_variants)

    s = sub.add_parser("pick", help="人工选定哪个版本 —— 选定后才进发布流程")
    s.add_argument("--slug", required=True)
    s.add_argument("--qid", required=True)
    s.add_argument("--variant", required=True, help="版本 ID：a=权威型 / b=实用型 / c=对比型")
    s.set_defaults(func=cmd_pick)

    s = sub.add_parser("lint", help="检查 AI 初稿的编造风险（发布/交付前必跑）")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_lint)

    s = sub.add_parser("verify", help="重抓并自动验收工单")
    s.add_argument("--slug", required=True)
    s.add_argument("--no-recrawl", action="store_true", dest="no_recrawl",
                   help="用现有 audit 结果验收，不重新抓站")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("deliver", help="打包客户交付物")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_deliver)

    s = sub.add_parser("publish", help="把成稿/资产发布到已配置的渠道（永远手动触发）")
    s.add_argument("--slug", required=True)
    s.add_argument("--path", required=True, help="content/ 或 assets/ 下的相对路径")
    import publish as _pub  # 渠道清单以 publish.PUBLISHERS 为单一来源，不在 CLI 再抄一份
    s.add_argument("--platform", required=True, choices=sorted(_pub.PUBLISHERS))
    s.add_argument("--title")
    s.add_argument("--published", action="store_true",
                   help="直接对外发布；不加则只建草稿（目前作用于 dev.to）")
    s.add_argument("--via", choices=["api", "semi"],
                   help="强制走哪条通路；不给则按平台规则自动选。选 semi 时只备好并打印，不外发")
    s.set_defaults(func=cmd_publish)

    s = sub.add_parser("publish-mark", help="半自动渠道：人工发布完成后回填公开链接")
    s.add_argument("--slug", required=True)
    s.add_argument("--platform", required=True, choices=sorted(_pub.PUBLISHERS))
    s.add_argument("--id", required=True, help="备好时打印的 8 位记录 id")
    s.add_argument("--url", help="发布后的公开链接（回链与分发清单都靠它）")
    s.add_argument("--path", help="成稿相对路径（可选，用于消歧）")
    s.add_argument("--note")
    s.add_argument("--cancel", action="store_true", help="作废这条待办（备了但没发）")
    s.set_defaults(func=cmd_publish_mark)

    s = sub.add_parser("task", help="查看或更新单条工单状态")
    s.add_argument("--slug", required=True)
    s.add_argument("--id", required=True)
    s.add_argument("--status", choices=["todo", "doing", "done", "blocked", "wontfix"])
    s.add_argument("--note")
    s.set_defaults(func=cmd_task)

    s = sub.add_parser("status", help="项目进度看板")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("serve", help="完整服务周期：抓取→体检→采样→工单→资产→报告→验收→交付")
    s.add_argument("--slug", required=True)
    s.add_argument("--max-pages", type=int, default=None, dest="max_pages")
    s.add_argument("--limit", type=int, default=None, help="采样只跑前 N 个问题")
    s.add_argument("--no-sample", action="store_true", dest="no_sample")
    s.add_argument("--draft", action="store_true", help="额外生成文章初稿")
    s.add_argument("--draft-limit", type=int, default=3, dest="draft_limit")
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("ui", help="启动可观测看板（趋势、工单、信源、验收历史）")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-open", action="store_true", dest="no_open")
    s.set_defaults(func=cmd_ui)

    s = sub.add_parser("list", help="列出所有项目")
    s.set_defaults(func=cmd_list)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
