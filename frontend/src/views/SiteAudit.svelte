<script>
  import PageHead from '../components/PageHead.svelte'
  import TaskDialog from '../components/TaskDialog.svelte'
  import { esc } from '../lib/format.js'
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'

  // 迁自 ui.html:2671 vSiteAudit。
  // agrade / ablk 两个联动筛选原本是全局 ST 键，下沉成组件内 $state。
  // auditFlag(i) 也搬进来了：六张卡片的联动，能直接看源文件的开新窗口，
  // 其余跳到相关工单。

  let openTask = $state(null)

  const D = $derived(project.data || {})
  const A = $derived(D.audit || {})
  const site = $derived(A.site || {})
  const lc = $derived(A.language_coverage || {})
  const gd = $derived(A.grade_distribution || {})
  const pages = $derived(A.pages || [])
  const layers = $derived(A.layers || [])
  const tasks = $derived(D.tasks || [])

  let agrade = $state(null)
  let ablk = $state(null)

  const LWORD = { ok: 'OK', warn: 'At risk', fail: 'Failing' }
  const GAIN = { 数字事实: '+61.6%', 定义: '+57.3%', 对比: '+55.3%', 操作步骤: '+41.2%', FAQ: 'Helps recall' }
  const GNOTE = { A: 'Directly citable', B: 'Basically usable', C: 'Needs rework', D: 'As good as absent' }

  const probe = $derived(site.ai_ua_probe || {})
  const probeN = $derived(Object.keys(probe).length)
  const uaBad = $derived((site.ai_ua_blocked || []).length)
  const partial = $derived((site.ai_bots_partial || []).length)
  const lch = $derived(site.llms_txt_check || {})
  const lbad = $derived((lch.broken || []).length + (lch.robots_blocked || []).length)

  const flags = $derived([
    {
      label: t('robots blocks AI crawlers'),
      value: (site.ai_bots_blocked || []).length ? t('Blocked: {list}').replace('{list}', site.ai_bots_blocked.join(', '))
        : partial ? t('Some paths restricted ({n} crawlers)').replace('{n}', String(partial)) : t('Not blocked'),
      ok: !(site.ai_bots_blocked || []).length && !partial,
      hint: t('View robots.txt ↗'),
    },
    {
      label: t('WAF/UA probe'),
      value: uaBad ? t('Refused: {list}').replace('{list}', site.ai_ua_blocked.join(', '))
        : probeN ? t('{n} crawlers allowed in practice').replace('{n}', String(probeN)) : t('Not probed (re-crawl)'),
      ok: !uaBad,
      hint: uaBad ? t('Related task →') : t('Fetch homepage as AI crawler UA'),
    },
    {
      label: 'sitemap.xml',
      value: site.has_sitemap
        ? t('Present · {n} URLs').replace('{n}', String(site.sitemap_url_count || 0)) + (site.robots_sitemap_declared === false ? t(' · not declared in robots') : '')
        : t('Missing'),
      ok: !!site.has_sitemap && site.robots_sitemap_declared !== false,
      hint: t('View sitemap.xml ↗'),
    },
    {
      label: 'llms.txt',
      value: site.has_llms_txt ? (lbad ? t('Live · {n} broken links').replace('{n}', String(lbad)) : t('Live')) : t('Missing'),
      ok: !!site.has_llms_txt && !lbad,
      hint: t('See Assets →'),
    },
    {
      label: t('Pages reachable'),
      value: `${site.pages_ok || 0} / ${site.pages_crawled || 0}`,
      ok: (site.pages_ok || 0) === (site.pages_crawled || 0),
      hint: t('Locate problem pages ↓'),
    },
    {
      label: t('Language coverage'),
      value: t('CN {z} pages · EN {e} pages').replace('{z}', String(lc.zh_pages || 0)).replace('{e}', String(lc.en_pages || 0)),
      ok: (D.market !== 'both') || ((lc.en_pages || 0) > 0 && (lc.zh_pages || 0) > 0),
      hint: t('Related task →'),
    },
  ])

  const gmax = $derived(Math.max(1, ...['A', 'B', 'C', 'D'].map((g) => gd[g] || 0)))
  const gradeOf = (s) => s >= 80 ? 'A' : s >= 65 ? 'B' : s >= 45 ? 'C' : 'D'

  const plist = $derived.by(() => {
    let list = pages
    if (agrade) list = list.filter((p) => gradeOf(p.score) === agrade)
    if (ablk) list = list.filter((p) => !(p.blocks || {})[ablk])
    return list
  })

  const blkTask = (b) => tasks.find((x) => ((x.acceptance || {}).check || '') === 'pages.block:' + b)

  // 搬自 ui.html:2776 auditFlag。顶部六张卡片的联动：能直接看源文件的就开新窗口，
  // 有对应工单的打开任务详情，其余跳到相关页面。
  // 它原来在 legacy 里调 taskModal，迁到这里之后就能用本组件自己的弹窗状态。
  function auditFlag(i) {
    const siteRoot = (D.brand?.site || '').replace(/\/$/, '')
    const byCheck = (rx) => {
      const hit = tasks.find((x) => rx.test((x.acceptance || {}).check || ''))
      if (hit) openTask = hit
      else go('plan')
    }
    if (i === 0 && siteRoot) window.open(siteRoot + '/robots.txt', '_blank')
    else if (i === 1) byCheck(/^site\.no_ai_ua_block/)
    else if (i === 2 && siteRoot) window.open(siteRoot + '/sitemap.xml', '_blank')
    else if (i === 3) go('assets', { assetSel: 'llms.txt' })
    else if (i === 4) document.querySelector('#audit-pages')?.scrollIntoView({ block: 'start' })
    else if (i === 5) byCheck(/^site\.(en_pages_gte|lang_balance)/)
  }
</script>

{#if !D.brand?.site}
  <div class="page">
    <PageHead
      kicker={t('DIAGNOSIS · SITE AUDIT')}
      title={t('This project has no site of its own — the technical layer does not apply')}
      sub={t('Products and brands without their own site (e-commerce, offline, mini-programs) need no site audit — AI visibility comes from external channels and content. See Channel Map for where to build and Questions for what to write.')}
    />
  </div>
{:else if !A.page_count}
  <div class="page">
    <PageHead
      kicker={t('DIAGNOSIS · SITE AUDIT')}
      title={t('No audit data yet')}
      sub={t('Run "Crawl site" and "Audit pages" under Settings → Run tasks.')}
    />
  </div>
{:else}
  <div class="page">
    <PageHead
      kicker={t('DIAGNOSIS · SITE AUDIT')}
      title={t('Content issues live in Gap Diagnosis — this is the technical layer')}
      sub={t('Four dependent layers: Access → Orientation → Understanding → Quotability. Each depends on the one above — if Access fails, nothing downstream is visible to engines. Page scoring follows published empirical data.')}
    />

    {#if layers.length}
      <div class="lchain">
        {#each layers as l, i (l.key || l.name)}
          {#if i}<div class="arrow">→</div>{/if}
          <div class="card layer" class:fail={l.status === 'fail'} class:warn={l.status === 'warn'}
               title={(l.issues || []).join('; ') || t('No issues')}>
            <div class="layer-top">
              <span class="layer-name">{l.name}</span>
              <span class="layer-state" class:ok={l.status === 'ok'} class:warn={l.status === 'warn'}>{t(LWORD[l.status] || '')}</span>
            </div>
            <div class="layer-q">{l.question || ''}</div>
            {#each (l.issues || []).slice(0, 2) as x (x)}
              <div class="layer-issue">· {x}</div>
            {/each}
            {#if (l.issues || []).length > 2}
              <div class="layer-more">{t('…{n} total').replace('{n}', String(l.issues.length))}</div>
            {/if}
            {#if l.blocked_by}
              <div class="layer-blocked">{t('⚠ Fix the "{b}" layer first — only then is work here visible').replace('{b}', l.blocked_by)}</div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}

    <div class="kpis six audit-flags">
      {#each flags as f, i (f.label)}
        <div class="card elev flag" onclick={() => auditFlag(i)} title={f.hint}>
          <div class="flag-l">{f.label}</div>
          <div class="flag-v" class:bad={!f.ok}>{f.value}</div>
          <div class="flag-foot">
            <span class:ok={f.ok} class:bad={!f.ok}>{f.ok ? t('OK') : t('Needs attention')}</span>
            <span class="flag-hint">{f.hint}</span>
          </div>
        </div>
      {/each}
    </div>

    {#if (A.site_issues || []).length}
      <div class="card issues">
        {#each A.site_issues as i (i)}
          <div class="issue">· {i}</div>
        {/each}
      </div>
    {/if}

    <div class="audit-grid">
      <div class="card elev panel">
        <div class="panel-t">{t('Page grade distribution · avg {n}').replace('{n}', A.avg_score ?? '—')}</div>
        <div class="panel-s">{t('70 and above counts as "basically usable".')}</div>
        {#each ['A', 'B', 'C', 'D'] as g (g)}
          <div class="grade-row-a" class:on={agrade === g} title={t('Click to filter the page list below')}
               onclick={() => (agrade = agrade === g ? null : g)}>
            <span class="grade-name" class:on={agrade === g}>{g} · {t(GNOTE[g])}</span>
            <span class="bar grade-bar"><span style="width:{((gd[g] || 0) / gmax * 100).toFixed(0)}%"></span></span>
            <span class="grade-n">{gd[g] || 0}</span>
          </div>
        {/each}
        <div class="muted panel-foot">{t('Click a grade → the list below shows only those pages')}</div>
      </div>

      <div class="card elev panel">
        <div class="panel-t">{t('Extraction block gaps, site-wide')}</div>
        <div class="panel-s">{t('The single biggest GEO lever. The right column is the measured citation-probability lift.')}</div>
        <div class="tbl">
          <table class="table">
            <thead><tr>
              <th>{t('Block')}</th><th style="width:100px">{t('Missing pages')}</th>
              <th style="width:90px">{t('Measured lift')}</th><th style="width:110px">{t('Ticket')}</th>
            </tr></thead>
            <tbody>
              {#each (A.block_gap || []) as g (g.block)}
                {@const task = blkTask(g.block)}
                <tr class="blk-row" class:on={ablk === g.block} title={t('Click to filter the pages missing this block')}
                    onclick={() => (ablk = ablk === g.block ? null : g.block)}>
                  <td class="blk-name" class:on={ablk === g.block}>{g.block}</td>
                  <td class="blk-n">{g.missing_pages} / {g.total}</td>
                  <td class="blk-gain">{GAIN[g.block] || '—'}</td>
                  <td>
                    {#if task}
                      <span class="tag tag-outline task-chip" title={t('Open task details')}
                            role="button" tabindex="0"
                            onclick={(e) => { e.stopPropagation(); openTask = task }}
                            onkeydown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); openTask = task } }}>{task.id} →</span>
                    {:else}
                      <span class="muted blk-none">—</span>
                    {/if}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        <div class="muted panel-foot">{t('Click a row → the list below shows pages missing that block; click a task id to see how to fix it.')}</div>
      </div>
    </div>

    <div class="row pages-head" id="audit-pages">
      <h4 class="pages-t">{t('Pages most in need of rework (lowest score first)')}</h4>
      {#if agrade || ablk}
        <span class="tag tag-accent">
          {agrade ? t('Grade {g}').replace('{g}', agrade) : ''}{agrade && ablk ? ' + ' : ''}{ablk ? t('missing "{b}"').replace('{b}', ablk) : ''} · {plist.length} {t('pages')}
        </span>
        <button class="btn btn-ghost clear-btn" onclick={() => { agrade = null; ablk = null }}>{t('Clear filters')}</button>
      {/if}
    </div>

    <div class="tbl">
      <table class="table">
        <thead><tr>
          <th style="width:70px">{t('Score')}</th><th style="width:70px">{t('Words')}</th>
          <th style="width:86px" title={t('Independently citable paragraphs / H2 sections — retrieval picks by paragraph, so a long page is not a citable one')}>{t('Citable sections')}</th>
          <th style="width:250px">{t('Missing blocks')}</th><th>{t('Page')}</th>
        </tr></thead>
        <tbody>
          {#each plist.slice(0, (agrade || ablk) ? 40 : 12) as pg (pg.url)}
            <tr>
              <td class="pg-score" class:low={pg.score < 45}>{pg.score}</td>
              <td class="pg-wc">{pg.word_count}</td>
              <td class="pg-sec" class:zero={pg.sections_total >= 3 && pg.sections_quotable === 0}>
                {pg.sections_total != null ? `${pg.sections_quotable}/${pg.sections_total}` : '—'}
              </td>
              <td class="pg-blocks">{Object.keys(pg.blocks || {}).filter((k) => !pg.blocks[k]).join('、') || '—'}</td>
              <td class="pg-url"><a href={pg.url} target="_blank" rel="noopener">{(pg.title || pg.url).slice(0, 60)}</a></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <p class="muted audit-foot">
      {t('Pages with near-zero word counts are client-rendered shells — AI crawlers see blank, which is the most common fatal flaw on Chinese sites. The fix list is in the Action Plan.')}
    </p>
  </div>
{/if}

{#if openTask}
  <TaskDialog task={openTask} onclose={() => (openTask = null)} />
{/if}

<style>
  .lchain { display: flex; gap: 0; align-items: stretch; margin-top: 20px; flex-wrap: wrap; }
  .arrow { align-self: center; padding: 0 7px; color: var(--t600); flex: none; }
  .layer { flex: 1; min-width: 0; padding: 13px 15px; gap: 4px; }
  .layer.fail { box-shadow: 0 0 0 1px var(--a700); }
  .layer.warn { box-shadow: 0 0 0 1px var(--a800); }
  .layer-top { display: flex; justify-content: space-between; align-items: baseline; }
  .layer-name { font-size: 14px; font-weight: 500; }
  .layer-state { font-size: 11px; color: var(--accent); }
  .layer-state.ok { color: var(--t600); }
  .layer-state.warn { color: var(--a300); }
  .layer-q { font-size: 11px; color: var(--t600); }
  .layer-issue { font-size: 11.5px; color: var(--t400); }
  .layer-more { font-size: 11px; color: var(--t600); }
  .layer-blocked { font-size: 11px; color: var(--a300); }

  .audit-flags { margin-top: 14px; }
  .flag { gap: 4px; padding: 15px; cursor: pointer; }
  .flag-l { font-size: 11.5px; color: var(--t500); }
  .flag-v { font-size: 15px; font-weight: 500; }
  .flag-v.bad { color: var(--a300); }
  .flag-foot { display: flex; justify-content: space-between; font-size: 11px; }
  .flag-foot .ok { color: var(--t600); }
  .flag-foot .bad { color: var(--accent); }
  .flag-hint { color: var(--a300); }

  .issues { margin-top: 14px; box-shadow: 0 0 0 1px var(--a700); padding: 14px 16px; gap: 5px; }
  .issue { font-size: 13px; color: var(--t400); }

  .audit-grid { display: grid; grid-template-columns: 1fr 1.2fr; gap: 14px; margin-top: 14px; }
  /* grid item 的 min-width 默认是 auto：右侧面板里那张 .table 带 min-width:820px，
     会把整列顶宽。app.css 里那条 min-width:0 只匹配内联 grid，够不着组件内的 class。 */
  .audit-grid > * { min-width: 0; }
  .panel { padding: 18px; }
  .panel-t { font-size: 15px; font-weight: 500; }
  .panel-s { font-size: 11.5px; color: var(--t600); margin-bottom: 10px; }
  .panel-foot { font-size: 11px; margin-top: 6px; }

  .grade-row-a { display: flex; align-items: center; gap: 10px; padding: 5px 0; cursor: pointer; border-radius: 6px; }
  .grade-row-a.on { background: var(--deep); }
  .grade-name { width: 110px; font-size: 12.5px; flex: none; }
  .grade-name.on { color: var(--a300); }
  .grade-bar { flex: 1; }
  .grade-n { width: 30px; text-align: right; font-size: 12px; color: var(--t400); }

  .blk-row { cursor: pointer; }
  .blk-row.on { background: var(--deep); }
  .blk-name { font-size: 13.5px; }
  .blk-name.on { color: var(--a300); }
  .blk-n { font-size: 13px; color: var(--t400); }
  .blk-gain { font-size: 13px; color: var(--a300); }
  .task-chip { cursor: pointer; font-size: 11px; }
  .blk-none { font-size: 11px; }

  .pages-head { margin: 26px 0 8px; }
  .pages-t { font-size: 16px; margin: 0; }
  .clear-btn { font-size: 11.5px; }

  .pg-score { font-size: 13px; color: var(--t400); }
  .pg-score.low { color: var(--a300); }
  .pg-wc { font-size: 13px; color: var(--t400); }
  .pg-sec { font-size: 13px; color: var(--t400); }
  .pg-sec.zero { color: var(--accent); }
  .pg-blocks { font-size: 12.5px; color: var(--t500); }
  .pg-url { font-size: 12.5px; }
  .audit-foot { font-size: 12px; margin-top: 10px; }

  @media (max-width: 640px) {
    .lchain { flex-direction: column; }
    .arrow { transform: rotate(90deg); padding: 4px 0; }
    .audit-grid { grid-template-columns: 1fr; }
  }
</style>
