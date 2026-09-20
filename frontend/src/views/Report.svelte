<script>
  // 迁自 ui.html:2217 vReport。
  // headline() 与 onePager/editSheet 仍是 legacy 实现（前者是健康度结论文案的
  // 决策树，属于领域逻辑；后两者开新窗口/弹窗），这里直接按名调用。
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { pct } from '../lib/format.js'
  import PageHead from '../components/PageHead.svelte'

  const a = $derived(project.data?.analytics || {})
  const h = $derived(a.health || { subs: {} })
  const tr = $derived(a.trend || [])
  const slug = $derived(project.data?.slug || '')
  const deliveries = $derived(project.data?.deliveries || [])
  const reports = $derived(project.data?.reports || [])
  const sheets = $derived(project.data?.samples_sheets || [])
  const files = $derived(project.data?.deliverables_files || [])

  const prev = $derived(tr.length > 1 && tr[tr.length - 2].health != null ? tr[tr.length - 2] : null)

  const summary = $derived.by(() => {
    if (h.score == null) return t('No sampling data yet — cannot generate a summary.')
    const s = h.subs || {}
    const l1 = prev
      ? t('GEO health score {a} → {b}{trend}.').replace('{a}', String(prev.health)).replace('{b}', String(h.score))
          .replace('{trend}', h.score > prev.health ? t(', up') : h.score < prev.health ? t(', down') : t(', flat'))
      : t('Current GEO health score {a} (first baseline).').replace('{a}', String(h.score))
    const l2 = t('Mention {m}, cite share {c}, channel coverage {ch}, content readiness {ct}')
        .replace('{m}', pct(s.mention)).replace('{c}', pct(s.cite))
        .replace('{ch}', pct(s.channel)).replace('{ct}', pct(s.content))
      + (s.fact == null ? t('; fact consistency not measured (record a comparison first).')
                        : t(', fact consistency {f}.').replace('{f}', pct(s.fact)))
    const gap = (a.questions || []).filter((q) => !q.brand_probe && q.content !== '已成稿').length
    const chan = ((project.data?.blueprint || {}).channels || [])
      .filter((c) => !c.covered && c.priority !== 'P2').length
    return l1 + '\n' + l2 + '\n'
      + t('Next: fill the highest-priority batch of {g} content gaps, and build {c} P0/P1 channels.')
          .replace('{g}', String(gap)).replace('{c}', String(chan))
  })

  const cards = $derived([
    {
      who: t('For the boss'), name: t('One-page conclusion'),
      desc: t('One-line conclusion, health score, the five components, next step. Print or save as PDF.'),
      kind: 'onepager',
    },
    {
      who: t('For the delivery team'), name: t('Execution plan'),
      desc: t('Phased schedule, split by role, acceptance criteria per item, list of usable assets.'),
      kind: 'plan',
      exists: files.indexOf('3-GEO执行方案.html') >= 0,
    },
    {
      who: t('For the client'), name: t('Delivery package'),
      desc: t('Diagnostic report, optimization plan, task sheet (CSV), acceptance sheet, asset index and notes.'),
      kind: 'delivery',
      exists: deliveries.length > 0,
    },
  ])
</script>

<div class="page narrow">
  <PageHead
    kicker={t('RESULTS · REPORTS & DELIVERY')}
    title={t('Three people need three different reports')}
    sub={t('The boss wants the conclusion, the team wants the checklist, the client wants method and evidence. Different content and length — every number comes from the same sampling run.')}
  />

  <div class="rpt-cards">
    {#each cards as r (r.kind)}
      <div class="card elev rpt-card">
        <div class="rpt-who">{r.who}</div>
        <div class="rpt-name">{r.name}</div>
        <div class="rpt-desc">{r.desc}</div>
        <div class="row rpt-act">
          {#if r.kind === 'onepager'}
            <button class="btn btn-primary sm" onclick={() => window.onePager()}>{t('Generate')}</button>
          {:else if r.kind === 'plan'}
            {#if r.exists}
              <a class="btn btn-primary sm" target="_blank" href="/files/{slug}/deliverables/{encodeURIComponent('3-GEO执行方案.html')}">{t('Open')}</a>
            {:else}
              <button class="btn btn-secondary sm" onclick={() => window.runAction('deliverables')}>{t('Generate')}</button>
            {/if}
          {:else}
            {#if r.exists}
              <a class="btn btn-primary sm" target="_blank" href="/files/{slug}/delivery/{deliveries[0]}/index.html">{t('Open')}</a>
            {:else}
              <button class="btn btn-secondary sm" onclick={() => window.runAction('deliver')}>{t('Generate')}</button>
            {/if}
          {/if}
        </div>
      </div>
    {/each}
  </div>

  <h4 class="sec">{t('This round\'s summary (generated)')}</h4>
  <div class="card elev summary-card">
    <div class="summary">{summary}</div>
  </div>

  <h4 class="sec">{t('Manual sampling sheets (engines with no API)')}</h4>
  <p class="muted sheet-note">
    {t('Doubao App, Yuanbao, Baidu AI, ChatGPT web, and Google AI Overview have no public networked API. Export a sheet, paste each question\'s full answer into an ```answer block, then import.')}
  </p>
  <div class="row">
    <button class="btn btn-secondary" onclick={() => window.runAction('sample-sheet')}>{t('Export sampling sheet')}</button>
    {#each sheets.slice(0, 4) as s (s)}
      <button class="btn btn-ghost sm" onclick={() => window.editSheet(s)}>{s}</button>
    {/each}
  </div>

  <div class="rpt-bottom">
    <div class="card elev hist">
      <div class="hist-t">{t('Diagnostic report history')}</div>
      <div class="hist-s">{t('Archived per round, so deltas can be compared.')}</div>
      {#each reports as d (d)}
        <a class="hist-link" target="_blank" href="/files/{slug}/reports/{d}/report.html">{d}</a>
      {:else}
        <span class="muted hist-empty">{t('None yet')}</span>
      {/each}
    </div>
    <div class="card elev hist">
      <div class="hist-t">{t('Delivery package history')}</div>
      <div class="hist-s">{t('Client deliverables packaged per round.')}</div>
      {#each deliveries as d (d)}
        <div class="hist-row">
          <a target="_blank" href="/files/{slug}/delivery/{d}/index.html">{d}</a>
          <a class="muted hist-csv" href="/files/{slug}/delivery/{d}/03-工单表.csv">{t('Task CSV')}</a>
        </div>
      {:else}
        <span class="muted hist-empty">{t('None yet')}</span>
      {/each}
    </div>
  </div>

  <h4 class="sec tight">{t('Automatic delivery')}</h4>
  <p class="muted sheet-note">
    {t('This product ships no scheduler. To run weekly and send automatically, hang')}
    <code>geo.py serve --slug {slug}</code>
    {t('off Claude\'s schedule capability, then send deliverables/ to the recipient.')}
  </p>
</div>

<style>
  .rpt-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-top: 24px; }
  .rpt-card { padding: 18px; gap: 8px; }
  .rpt-who { font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: var(--accent); }
  .rpt-name { font-size: 18px; font-weight: 500; }
  .rpt-desc { font-size: 12.5px; color: var(--t400); line-height: 1.55; flex: 1; }
  .rpt-act { margin-top: 6px; }
  .sm { font-size: 12px; }

  .sec { font-size: 16px; margin: 34px 0 10px; }
  .sec.tight { margin: 30px 0 8px; }
  .summary-card { padding: 20px; }
  .summary { font-size: 15px; line-height: 1.7; color: #cfd3e5; max-width: 760px; white-space: pre-line; }
  .sheet-note { font-size: 12.5px; }

  .rpt-bottom { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 30px; }
  .hist { padding: 16px; gap: 6px; }
  .hist-t { font-size: 14px; font-weight: 500; }
  .hist-s { font-size: 11.5px; color: var(--t600); }
  .hist-link { font-size: 13px; }
  .hist-row { font-size: 13px; }
  .hist-csv { font-size: 11.5px; margin-left: 8px; }
  .hist-empty { font-size: 12.5px; }

  @media (max-width: 640px) {
    .rpt-cards, .rpt-bottom { grid-template-columns: 1fr; }
  }
</style>
