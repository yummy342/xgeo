<script>
  import PageHead from '../components/PageHead.svelte'
  import { go } from '../lib/router.svelte.js'
  import { headline } from '../lib/domain.js'
  import { pct } from '../lib/format.js'
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'

  // 迁自 ui.html:1121 vOverview。
  // headline() 仍是 legacy——它是「健康分 → 结论文案」的决策树，属于领域逻辑，
  // 由后端算更合适；在迁走之前按名调用。趋势图是内联 SVG，这里原样重画。

  const D = $derived(project.data || {})
  const a = $derived(D.analytics || {})
  const h = $derived(a.health || { subs: {}, measured: [] })
  const tr = $derived(a.trend || [])
  const engs = $derived(a.engines || [])
  const comp = $derived(a.competitors || {})
  const S = $derived(h.subs || {})

  // headline() 现在读 store（lib/domain.js）。数据未到时先给空串，
  // 免得首屏闪一下「还没有采样数据」再跳到真实结论。
  const headlinePair = $derived(project.data ? headline() : ['', ''])
  const topRival = $derived((comp.table || [])[0])

  const kpis = $derived([
    [t('GEO health score'), h.score == null ? '—' : h.score,
      t('{n}/5 measurable').replace('{n}', String((h.measured || []).length)) + (S.fact == null ? t(' · fact consistency untested') : '')],
    [t('Mention rate'), pct(S.mention), t('mentioned unprompted')],
    [t('Cite share'), pct(S.cite), t('your share of cited domains')],
    [t('Coverage'), S.channel == null ? '—' : pct(S.channel), t('channels already cited by AI')],
    [t('Content readiness'), S.content == null ? '—' : pct(S.content), t('target questions with final content')],
  ])

  const open = $derived(
    (D.tasks || []).filter((x) => x.status !== 'done')
      .sort((x, y) => x.priority.localeCompare(y.priority)).slice(0, 3),
  )

  const maxm = $derived(Math.max(0.001, ...engs.map((e) => e.mention || 0)))

  // 趋势折线：点数不足以画线时给提示，不画空图
  const chart = $derived.by(() => {
    if (tr.length < 2) return null
    const W = 620, H = 170, P = { l: 8, r: 8, t: 12, b: 10 }
    const xs = (i) => P.l + (W - P.l - P.r) * (i / (tr.length - 1))
    const ys = (v) => H - P.b - (H - P.t - P.b) * ((v || 0) / 100)
    const pts = tr.map((p, i) => [xs(i), ys(p.health)])
    const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ')
    const grid = [0, .33, .66, 1].map((f) => ({
      y: (P.t + (H - P.t - P.b) * f).toFixed(0),
      dashed: f > 0 && f < 1,
    }))
    const last = pts[pts.length - 1]
    return { W, H, line, grid, last, area: `${line} L${last[0]},${H} L${pts[0][0]},${H} Z` }
  })

  const LAYERS = $derived([
    [t('Exposure · mention'), S.mention, topRival ? topRival.presence : null, topRival ? topRival.name : '—'],
    [t('Citation · cite share'), S.cite, null, t('not measurable')],
    [t('Readiness · content'), S.content, null, t('not measurable')],
  ])
</script>

<div class="page">
  <PageHead
    kicker={t('STATUS · OVERVIEW')}
    title={headlinePair[0]}
    sub={headlinePair[1]}
  />

  <div class="kpis">
    {#each kpis as [l, v, n] (l)}
      <div class="card elev kpi">
        <div class="kpi-l">{l}</div>
        <div class="kpi-v">{v}</div>
        <div class="kpi-n">{n}</div>
      </div>
    {/each}
  </div>

  <div class="ov-grid">
    <div class="card elev panel">
      <div class="panel-top">
        <div>
          <div class="panel-t">{t('GEO health trend')}</div>
          <div class="panel-s">{t('Weights: mention 30, citation 25, channels 20, content 15, facts 10; untested components re-normalized.')}</div>
        </div>
        {#if h.score != null}<span class="tag tag-accent">{h.score}</span>{/if}
      </div>
      <div class="chart">
        {#if chart}
          <svg viewBox="0 0 {chart.W} {chart.H}" preserveAspectRatio="none">
            {#each chart.grid as g (g.y)}
              <line x1="0" y1={g.y} x2={chart.W} y2={g.y} stroke="#3f424d" stroke-width="1"
                    stroke-dasharray={g.dashed ? '3 4' : undefined}></line>
            {/each}
            <path d={chart.area} fill="#9184d9" opacity="0.10"></path>
            <path d={chart.line} fill="none" stroke="#9184d9" stroke-width="2.5" stroke-linejoin="round"></path>
            <circle cx={chart.last[0]} cy={chart.last[1]} r="4" fill="#9184d9"></circle>
          </svg>
          <div class="chart-axis">
            {#each tr as p (p.date)}<span>{p.date.slice(5)}</span>{/each}
          </div>
        {:else}
          <div class="muted chart-empty">
            {t('{n} rounds of data so far — two are needed to draw a trend.').replace('{n}', String(tr.length))}
          </div>
        {/if}
      </div>
    </div>

    <div class="card elev panel next-panel">
      <div>
        <div class="panel-t">{t('Next {n} things to do').replace('{n}', String(open.length))}</div>
        <div class="panel-s">{t('Top priorities from the action plan.')}</div>
      </div>
      {#each open as task (task.id)}
        <div class="task-card">
          <div class="task-top">
            <span class="task-title">{task.title}</span>
            <span class="tag {task.priority === 'P0' ? 'tag-accent' : 'tag-dim'} pri">{task.priority}</span>
          </div>
          <div class="task-why">{task.why}</div>
          <div class="task-meta">{task.owner} · {task.effort} · {t('Acceptance')}: {(task.acceptance || {}).desc || ''}</div>
        </div>
      {:else}
        <div class="muted panel-s">{t('No tasks yet — run a round from Settings.')}</div>
      {/each}
      <button class="btn btn-primary btn-block" onclick={() => go('plan')}>
        {t('Open action plan ({n} items)').replace('{n}', String((D.tasks || []).length))}
      </button>
    </div>
  </div>

  <div class="ov-grid2">
    <div class="card elev panel">
      <div class="panel-t">{t('Engine performance')}</div>
      <div class="panel-s">{t('Cross-engine gaps on the same questions come almost entirely from source structure.')}</div>
      {#each engs as e (e.platform)}
        <div class="eng-row">
          <span class="eng-label">{e.label}</span>
          <span class="bar eng-bar"><span style="width:{((e.mention || 0) / maxm * 100).toFixed(0)}%"></span></span>
          <span class="eng-pct">{pct(e.mention)}</span>
        </div>
      {:else}
        <div class="muted panel-s">{t('Not sampled yet')}</div>
      {/each}
      <button class="btn btn-ghost self-start" onclick={() => go('engines')}>{t('Drill into each engine →')}</button>
    </div>

    <div class="card elev panel">
      <div class="panel-t">{t('Which layer you trail on')}</div>
      <div class="panel-s">{t('Rival data comes from the same samples; layers marked — cannot be measured for rivals.')}</div>
      {#each LAYERS as [n, me, them, who] (n)}
        {@const mx = Math.max(0.001, me || 0, them || 0)}
        <div class="layer-row">
          <div class="layer-head">
            <span>{n}</span>
            <span class="layer-gap">{them != null && me != null && me > 0 ? t('{n}× gap').replace('{n}', (them / me).toFixed(1)) : ''}</span>
          </div>
          <div class="layer-bar">
            <span class="layer-who">{t('you')}</span>
            <span class="bar"><span style="width:{((me || 0) / mx * 100).toFixed(0)}%"></span></span>
            <span class="layer-val">{pct(me)}</span>
          </div>
          <div class="layer-bar">
            <span class="layer-who ellipsis">{who}</span>
            <span class="bar"><span style="width:{them != null ? (them / mx * 100).toFixed(0) : 0}%;background:#595d6c"></span></span>
            <span class="layer-val">{them != null ? pct(them) : '—'}</span>
          </div>
        </div>
      {/each}
      <button class="btn btn-ghost self-start" onclick={() => go('gaps')}>{t('See gap diagnosis →')}</button>
    </div>
  </div>
</div>

<style>
  .kpi { gap: 4px; padding: 15px; }
  .kpi-l { font-size: 11.5px; color: var(--t500); }
  .kpi-v { font-size: 29px; font-weight: 500; letter-spacing: -.02em; }
  .kpi-n { font-size: 11px; color: var(--t600); line-height: 1.4; }

  .ov-grid { display: grid; grid-template-columns: 1.35fr 1fr; gap: 14px; margin-top: 14px; }
  .ov-grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 14px; }
  .panel { padding: 18px; }
  .panel-top { display: flex; justify-content: space-between; align-items: baseline; }
  .panel-t { font-size: 15px; font-weight: 500; }
  .panel-s { font-size: 11.5px; color: var(--t600); }

  .chart { margin-top: 10px; }
  .chart svg { width: 100%; height: 170px; }
  .chart-axis { display: flex; justify-content: space-between; font-size: 10.5px; color: var(--t600); }
  .chart-empty { font-size: 12.5px; padding: 20px 0; }

  .next-panel { gap: 10px; }
  .task-card {
    padding: 12px; border-radius: var(--r-md); background: var(--deep);
    box-shadow: var(--sh-sm); display: flex; flex-direction: column; gap: 5px;
  }
  .task-top { display: flex; justify-content: space-between; gap: 8px; }
  .task-title { font-size: 13.5px; }
  .pri { flex: none; }
  .task-why { font-size: 11.5px; color: var(--t500); line-height: 1.45; }
  .task-meta { font-size: 11px; color: var(--t600); }

  .eng-row { display: flex; align-items: center; gap: 10px; padding: 5px 0; }
  .eng-label { width: 96px; font-size: 12.5px; flex: none; }
  .eng-bar { flex: 1; }
  .eng-pct { width: 48px; text-align: right; font-size: 12px; color: var(--t400); flex: none; }
  .self-start { align-self: flex-start; margin-top: 6px; }

  .layer-row { padding: 11px 0; box-shadow: inset 0 -1px 0 var(--line); }
  .layer-head { display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 6px; }
  .layer-gap { font-size: 12px; color: var(--a400); }
  .layer-bar { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--t600); }
  .layer-who { width: 48px; flex: none; }
  .layer-who.ellipsis { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .layer-bar .bar { flex: 1; }
  .layer-val { width: 44px; text-align: right; }

  @media (max-width: 640px) {
    .ov-grid, .ov-grid2 { grid-template-columns: 1fr; }
  }
</style>
