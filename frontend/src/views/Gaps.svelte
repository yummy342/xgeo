<script>
  // 迁自 ui.html:1599 vGaps。
  // gapTab 原本是全局 ST.gapTab（配合 onclick="ST.gapTab='x';render()"），
  // 这里下沉成组件内的 $state。它是这一页自己的 tab，放全局只是历史包袱。
  // diagTag 仍在 legacy 里（返回 HTML 字符串），所以走 {@html}。
  import { project } from '../lib/stores/project.svelte.js'
  import { ui } from '../lib/stores/ui.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { go } from '../lib/router.svelte.js'
  import { pct } from '../lib/format.js'
  import PageHead from '../components/PageHead.svelte'

  const a = $derived(project.data?.analytics || {})
  const bp = $derived(project.data?.blueprint || { channels: [] })

  const qs = $derived((a.questions || []).filter((q) => !q.brand_probe))
  const contentGap = $derived(qs.filter((q) => q.content !== '已成稿'))
  const chanGap = $derived(
    (bp.channels || []).filter((c) => !c.covered && (c.priority === 'P0' || c.priority === 'P1')),
  )
  const fc = $derived(a.factcheck || [])

  let tab = $state('content')

  // 来自「引擎表现 · 样本回放」的跳转传参（go('gaps', { gapTab: 'fact' })）。
  // 只取一次就清掉，否则下次进这一页会被旧值覆盖。
  $effect(() => {
    const g = ui.gapTab
    if (!g) return
    ui.gapTab = null
    tab = g
  })

  const cards = $derived([
    {
      k: 'content', order: t('Step 1 · fix first'), name: t('Content gap'),
      v: contentGap.length, unit: t('questions have no extractable answer'),
      sev: t('Biggest impact'),
      why: t('Without content, building channels and fixing claims have nothing to land on. Measured: numbers +61.6%, definitions +57.3%, comparisons +55.3% citation probability.'),
    },
    {
      k: 'channel', order: t('Step 2 · then build'), name: t('Channel gap'),
      v: chanGap.length, unit: t('P0/P1 channels not cited'),
      sev: t('Fastest payoff'),
      why: t('Sites engines actually cite but where you have nothing. P0 is the foundation.'),
    },
    {
      k: 'fact', order: t('Step 3 · calibrate'), name: t('Fact deviations'),
      v: fc.filter((f) => f.state !== '一致').length, unit: t('claims to fix or never compared'),
      sev: t('Costs more the more visible you get'),
      why: t('Rising mention rates amplify wrong claims. Compare by hand from the sample replay under Engines, then record it here.'),
    },
  ])

  const TABS = $derived([
    ['content', t('Content gap · {n}').replace('{n}', String(contentGap.length))],
    ['channel', t('Channel gap · {n}').replace('{n}', String(chanGap.length))],
    ['fact', t('Fact deviations · {n}').replace('{n}', String(fc.length))],
  ])

  function mktName(m) {
    return m === 'cn' ? t('CN market') : m === 'global' ? t('Global market') : t('Both markets')
  }
</script>

<div class="page">
  <PageHead
    kicker={t('DIAGNOSIS · GAPS')}
    title={t('A low score has only three causes — fix them in order')}
    sub={t('To be cited you need all three at once: something to cite (content), being where it looks (channels), and being described correctly (facts). They are ordered — with no content written, building channels is building on nothing.')}
  />

  <div class="gap-cards">
    {#each cards as c (c.k)}
      <div class="card gap-card" class:on={tab === c.k} onclick={() => (tab = c.k)}>
        <div class="row gap-top">
          <span class="gap-order">{c.order}</span>
          <span class="tag {c.k === 'content' ? 'tag-accent' : 'tag-dim'}">{c.sev}</span>
        </div>
        <div class="gap-name">{c.name}</div>
        <div class="gap-num"><span class="gap-v">{c.v}</span><span class="gap-unit">{c.unit}</span></div>
        <div class="gap-why">{c.why}</div>
      </div>
    {/each}
  </div>

  <div class="card elev gap-body">
    <div class="row tabs-row">
      {#each TABS as [k, label] (k)}
        <button class="btn gap-tab" class:on={tab === k} onclick={() => (tab = k)}>{label}</button>
      {/each}
    </div>

    {#if tab === 'content'}
      <div class="tbl">
        <table class="table">
          <thead><tr>
            <th>{t('Gap question')}</th><th style="width:70px">{t('Market')}</th>
            <th style="width:96px">{t('Your mention')}</th><th style="width:96px">{t('Diagnosis')}</th>
            <th style="width:100px">{t('Current state')}</th><th style="width:100px"></th>
          </tr></thead>
          <tbody>
            {#each contentGap as q (q.id)}
              <tr>
                <td class="q-cell">{q.text}</td>
                <td class="mkt-cell">{mktName(q.market)}</td>
                <td class="mention">{q.mention == null ? t('Not sampled') : pct(q.mention)}</td>
                <td>{@html window.diagTag(q.diagnosis)}</td>
                <td class="state-cell">{q.content}</td>
                <td><button class="btn btn-ghost sm" onclick={() => go('workbench', { wq: q.id })}>{t('Generate draft')}</button></td>
              </tr>
            {:else}
              <tr><td colspan="6" class="muted empty">{t('No content gaps')}</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else if tab === 'channel'}
      <div class="tbl">
        <table class="table">
          <thead><tr>
            <th>{t('Channel')}</th><th style="width:70px">{t('Priority')}</th>
            <th style="width:110px">{t('National citations')}</th><th style="width:100px">{t('Position')}</th>
            <th style="width:220px">{t('What to build')}</th><th style="width:100px"></th>
          </tr></thead>
          <tbody>
            {#each chanGap as c (c.name)}
              <tr>
                <td class="q-cell">{c.name}</td>
                <td><span class="tag {c.priority === 'P0' ? 'tag-accent' : 'tag-dim'}">{c.priority}</span></td>
                <td class="mention">{c.national ? c.national.toLocaleString() : '—'}</td>
                <td class="mention">{c.position == null ? '—' : c.position}</td>
                <td class="state-cell">{(c.forms || []).slice(0, 2).join(' / ')}</td>
                <td><button class="btn btn-ghost sm" onclick={() => go('channels', { chanSel: c.name })}>{t('Build plan')}</button></td>
              </tr>
            {:else}
              <tr><td colspan="6" class="muted empty">{t('All P0/P1 channels are covered')}</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <div class="row fact-bar">
        <span class="muted fact-hint">
          {t('Record what AI gets wrong, found via Engines → sample replay. Only once something is recorded does fact consistency become measurable, and the health score moves with it.')}
        </span>
        <button class="btn btn-secondary sm fact-add" onclick={() => window.addFact()}>{t('+ Record one')}</button>
      </div>
      <div class="tbl">
        <table class="table">
          <thead><tr>
            <th style="width:120px">{t('Field')}</th><th>{t('What AI said')}</th>
            <th>{t('Official claim')}</th><th style="width:90px">{t('Status')}</th><th style="width:56px"></th>
          </tr></thead>
          <tbody>
            {#each fc as f, i (f.field + i)}
              <tr>
                <td class="field-cell">{f.field || ''}</td>
                <td class="said-cell">{f.said || ''}</td>
                <td class="truth-cell">{f.truth || ''}</td>
                <td><span class="tag {f.state === '一致' ? 'pill-good' : 'tag-accent'}">{f.state || t('Not compared')}</span></td>
                <td><button class="btn btn-ghost sm" onclick={() => window.delFact(i)}>{t('Delete')}</button></td>
              </tr>
            {:else}
              <tr><td colspan="5" class="muted empty">{t('No comparisons recorded yet')}</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </div>
</div>

<style>
  .gap-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 24px 0 16px; }
  .gap-card { padding: 18px; cursor: pointer; box-shadow: var(--sh-sm); }
  .gap-card.on { box-shadow: 0 0 0 1px var(--a700); }
  .gap-top { justify-content: space-between; align-items: baseline; }
  .gap-order { font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: var(--accent); }
  .gap-name { font-size: 18px; font-weight: 500; margin-top: 4px; }
  .gap-num { display: flex; align-items: baseline; gap: 8px; }
  .gap-v { font-size: 30px; font-weight: 500; }
  .gap-unit { font-size: 12px; color: var(--t600); }
  .gap-why { font-size: 12.5px; color: var(--t400); line-height: 1.5; }

  .gap-body { padding: 20px; }
  .tabs-row { margin-bottom: 12px; }
  .gap-tab { font-size: 13px; color: var(--t500); }
  .gap-tab.on { background: var(--a900); color: var(--a300); box-shadow: inset 0 0 0 1px var(--a700); }

  .q-cell { font-size: 13.5px; }
  .mkt-cell { font-size: 12.5px; color: var(--t500); }
  .mention { font-size: 13px; color: var(--t400); }
  .state-cell { font-size: 12.5px; color: var(--t500); }
  .empty { font-size: 12.5px; }
  .sm { font-size: 12px; }

  .fact-bar { margin-bottom: 10px; }
  .fact-hint { font-size: 12.5px; }
  .fact-add { margin-left: auto; }
  .field-cell { font-size: 13px; }
  .said-cell { font-size: 12.5px; color: var(--a300); }
  .truth-cell { font-size: 12.5px; color: var(--t500); }

  @media (max-width: 640px) {
    .gap-cards { grid-template-columns: 1fr; }
  }
</style>
