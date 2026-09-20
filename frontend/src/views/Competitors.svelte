<script>
  // 迁自 ui.html:1307 vCompetitors。
  // compTab 原本是全局 ST.compTab，下沉成组件内 $state。
  // engSel 仍是跨视图传参（点引擎标签跳「引擎表现」），留在 ui store。
  import { project } from '../lib/stores/project.svelte.js'
  import { ui } from '../lib/stores/ui.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { pct } from '../lib/format.js'
  import { post } from '../lib/api.js'
  import { toast } from '../lib/stores/toast.svelte.js'
  import { loadProject } from '../lib/stores/project.svelte.js'
  import { go } from '../lib/router.svelte.js'
  import ExpandDialog from '../components/ExpandDialog.svelte'

  let mining = $state(false)

  // 单个候选题入库（旧的 expAddIdx）
  async function addOne(term) {
    const r = await post('/api/questions-add', {
      slug: D.slug,
      items: [{ text: term.question, group: term.group, market: term.market }],
    })
    if (!r.ok) { toast(r.error || t('Save failed'), 'err'); return }
    toast(t('Added {n} questions').replace('{n}', String(r.added)))
    await loadProject(D.slug, true)
  }
  import PageHead from '../components/PageHead.svelte'

  const D = $derived(project.data || {})
  const c = $derived(D.analytics?.competitors || {})
  const h = $derived(D.analytics?.health || { subs: {} })

  const T = $derived(c.tables || (c.table ? { cn: c.table, global: [] } : { cn: [], global: [] }))
  const NS = $derived(c.sample_ns || { cn: c.sample_n || 0, global: 0 })
  const flat = $derived((T.cn || []).concat(T.global || []))
  const topName = $derived(flat.length ? flat[0].name : t('the leader'))
  const mineTerms = $derived(
    D.expand ? (D.expand.terms || []).map((x, i) => ({ term: x, i })).filter((o) => o.term.kind === 'competitor') : [],
  )

  let tab = $state('market')

  const TABS = $derived([
    ['market', t('Market landscape'), flat.length],
    ['battle', t('Contested questions'), (c.lost || []).length + (c.won || []).length],
    ['mining', t('Rival keywords'), mineTerms.length],
  ])

  function mktName(m) {
    return m === 'cn' ? t('CN market') : m === 'global' ? t('Global market') : t('Both markets')
  }
</script>

<div class="page">
  <PageHead
    kicker={t('STATUS · COMPETITORS')}
    title={t('{n} wins on source coverage, not on product').replace('{n}', topName)}
    sub={t('Rival presence rate from the same unprompted sampling run, computed separately for CN ({cn} samples) and global ({gl}), each against its own denominator. A rival\'s lead is copyable — cover the same content they get cited for and you enter the same answers. Their cite share and content readiness cannot be measured from outside, so they are not shown.').replace('{cn}', String(NS.cn || 0)).replace('{gl}', String(NS.global || 0))}
  />

  <div class="tabs ctabs">
    {#each TABS as [k, label, n] (k)}
      <button class="tab" class:on={tab === k} onclick={() => (tab = k)}>
        <span>{label}</span>{#if n}<span class="cnt">{n}</span>{/if}
      </button>
    {/each}
  </div>

  {#if tab === 'market'}
    {#each [['cn', T.cn || [], NS.cn || 0], ['global', T.global || [], NS.global || 0]] as [mk, rows, n] (mk)}
      {#if rows.length}
        <h4 class="tbl-h">
          {t(mk === 'cn' ? 'CN market' : 'Global market')}<span class="tbl-h-sub"> · {t('denominator: {n} unprompted samples in this market').replace('{n}', String(n))}</span>
        </h4>
        <div class="tbl">
          <table class="table">
            <thead><tr>
              <th style="width:150px">{t('Brand')}</th><th style="width:90px">{t('Presence')}</th>
              <th style="width:80px">{t('Hits')}</th><th style="width:220px">{t('Strongest engines (click)')}</th>
              <th style="width:300px">{t('Cited by (highlighted = you have none)')}</th><th>{t('Note')}</th>
            </tr></thead>
            <tbody>
              <tr class="me-row">
                <td><span class="me-name">{D.brand?.name}</span><div class="me-you">{t('you')}</div></td>
                <td><span class="tag pill-good">{pct(h.subs?.mention)}</span></td>
                <td class="cell-soft">{t('mention-rate basis')}</td>
                <td><button class="btn btn-ghost xs" onclick={() => go('engines')}>{t('Per-engine detail →')}</button></td>
                <td class="cell-dim">
                  {t('Health {s} · cite share {c} · your mention rate is the whole-market basis').replace('{s}', String(h.score ?? '—')).replace('{c}', pct(h.subs?.cite))}
                </td>
              </tr>
              {#each rows as x (x.name)}
                {@const ahead = (x.presence || 0) > (h.subs?.mention || 0)}
                <tr>
                  <td class="brand-cell">{x.name}</td>
                  <td><span class="tag {ahead ? 'tag-accent' : 'tag-dim'}">{pct(x.presence)}</span></td>
                  <td class="cell-soft">{x.hits}</td>
                  <td>
                    {#each (x.top_engines || []) as e (e.platform)}
                      <span class="tag tag-outline eng-tag" role="button" tabindex="0"
                            title={t('Open this engine under Engines')}
                            onclick={() => { ui.engSel = e.platform; go('engines') }}
                            onkeydown={(e2) => { if (e2.key === 'Enter') { ui.engSel = e.platform; go('engines') } }}>{e.label} {pct(e.rate)}</span>
                    {:else}
                      <span class="muted cell-none">—</span>
                    {/each}
                  </td>
                  <td>
                    {#each (x.top_sources || []) as s (s.domain)}
                      <span class="tag {s.covered ? 'tag-dim' : 'tag-outline'} src-tag"
                            title={s.covered
                              ? t('{n} citations · this domain also appears in your context').replace('{n}', String(s.hits))
                              : t('{n} citations · only appears in rival contexts — a channel you have not covered').replace('{n}', String(s.hits))}>{s.domain} ×{s.hits}</span>
                    {:else}
                      <span class="muted cell-none">—</span>
                    {/each}
                  </td>
                  <td class="cell-dim">{ahead ? t('Ahead of you — look at what cites them') : t('Behind you')}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
      {#if ((c.source_gap || {})[mk] || []).length}
        {@const g = (c.source_gap || {})[mk]}
        <div class="card elev gap-card">
          <div class="gap-top">
            <div>
              <div class="gap-t">{t('{m} · sources rivals have and you do not').replace('{m}', t(mk === 'cn' ? 'CN market' : 'Global market'))}</div>
              <div class="gap-s">{t('These domains are cited 2+ times in rival contexts and never in yours — the most direct attack list.')}</div>
            </div>
            <button class="btn btn-ghost sm" onclick={() => go('channels')}>{t('Check the Channel Map →')}</button>
          </div>
          <div class="row gap-tags">
            {#each g as s (s.domain)}
              <span class="tag tag-accent src-tag2">{s.domain} ×{s.hits}</span>
            {/each}
          </div>
        </div>
      {/if}
    {/each}
    {#if !flat.length}
      <div class="muted empty-note">{t('No competitor data yet — configure competitors under Settings and run a full round.')}</div>
    {/if}

  {:else if tab === 'battle'}
    <div class="battle">
      <div class="card elev battle-card">
        <div class="battle-t">{t('Questions you lost')}</div>
        <div class="battle-s">{t('You appear in 0% while a rival appears consistently — the highest-priority topic pool.')}</div>
        {#each (c.lost || []) as q (q.qid)}
          <div class="q-row">
            <div class="q-text">{q.question}</div>
            <div class="q-meta">
              {mktName(q.market)} · {t('you')} {pct(q.mine)} / {q.rival} {pct(q.rival_rate)} · {q.samples} {t('samples')}
              <button class="btn btn-ghost q-write" onclick={() => go('workbench', { wq: q.qid })}>{t('Write →')}</button>
            </div>
          </div>
        {:else}
          <div class="muted empty-note">{t('No lost questions this round')}</div>
        {/each}
      </div>
      <div class="card elev battle-card">
        <div class="battle-t">{t('Questions you own')}</div>
        <div class="battle-s">{t('You appear and every rival is absent — hold it, and copy this kind of content onto other questions.')}</div>
        {#each (c.won || []) as q (q.qid)}
          <div class="q-row">
            <div class="q-text">{q.question}</div>
            <div class="q-meta">{t('you')} {pct(q.mine)} · {q.samples} {t('samples')} · {t('rivals absent')}</div>
          </div>
        {:else}
          <div class="muted empty-note">{t('No owned questions this round — fill the lost ones first')}</div>
        {/each}
      </div>
    </div>

  {:else}
    <div class="card elev mining">
      <div class="mining-top">
        <div>
          <div class="mining-t">{t('Rival keywords · users are actively looking for alternatives')}</div>
          <div class="mining-s">{t('Real autocomplete terms from rival word roots — the alternative/comparison phrasings users already search. The sharpest attack topics.')}</div>
        </div>
        <button class="btn btn-ghost" onclick={() => (D.expand ? (mining = true) : window.runAction('expand'))}>
          {D.expand ? t('Mine topics') : t('Start mining')}
        </button>
      </div>
      {#each mineTerms.slice(0, 40) as { term, i } (term.term + i)}
        <div class="row mining-row">
          <span class="mining-term">
            {term.term}
            <span class="mining-meta">· {term.root} · {mktName(term.market)}{#if term.new} · <span class="hl">{t('new term')}</span>{/if}</span>
          </span>
          <span class="tag tag-dim group-tag">{term.group}</span>
          {#if term.in_bank}
            <span class="muted inbank">{t('In the bank')}</span>
          {:else}
            <button class="btn btn-ghost sm" onclick={() => addOne(term)}>{t('Add')}</button>
          {/if}
        </div>
      {:else}
        <div class="muted empty-note">
          {D.expand ? t('No candidates from rival roots this round — try mining again.') : t('No keyword mining data yet')}
        </div>
      {/each}
      {#if mineTerms.length > 40}
        <div class="muted mining-foot">{t('Showing the first 40 — all candidates are selectable under Mine topics.')}</div>
      {/if}
    </div>
  {/if}
</div>

{#if mining}
  <ExpandDialog onclose={() => (mining = false)} />
{/if}

<style>
  .ctabs { margin-top: 18px; }
  .tbl-h { font-size: 15px; margin: 26px 0 4px; }
  .tbl-h-sub { font-size: 11.5px; color: var(--t600); font-weight: 400; }

  .me-row { background: linear-gradient(90deg, rgba(145, 132, 217, .10), transparent); }
  .me-name { font-size: 14px; }
  .me-you { font-size: 10.5px; color: var(--t600); }
  .brand-cell { font-size: 14px; }
  .cell-soft { font-size: 13px; color: var(--t400); }
  .cell-dim { font-size: 12.5px; color: var(--t500); }
  .cell-none { font-size: 11.5px; }
  .eng-tag { cursor: pointer; font-size: 11px; }
  .src-tag { font-size: 11px; }
  .src-tag2 { font-size: 11.5px; }
  .xs { font-size: 11.5px; padding: 2px 8px; }
  .sm { font-size: 12px; }

  .gap-card { padding: 16px 18px; margin-top: 14px; }
  .gap-top { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
  .gap-t { font-size: 14.5px; font-weight: 500; }
  .gap-s { font-size: 11.5px; color: var(--t600); }
  .gap-tags { gap: 6px; flex-wrap: wrap; margin-top: 8px; }

  .battle { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 18px; }
  .battle-card { padding: 18px; }
  .battle-t { font-size: 15px; font-weight: 500; }
  .battle-s { font-size: 11.5px; color: var(--t600); margin-bottom: 6px; }
  .q-row { padding: 10px 0; box-shadow: inset 0 -1px 0 var(--line); }
  .q-text { font-size: 13px; margin-bottom: 3px; }
  .q-meta { font-size: 11px; color: var(--t600); }
  .q-write { font-size: 11px; padding: 0 4px; }
  .empty-note { font-size: 12.5px; margin-top: 8px; }

  .mining { padding: 18px; margin-top: 18px; }
  .mining-top { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
  .mining-t { font-size: 15px; font-weight: 500; }
  .mining-s { font-size: 11.5px; color: var(--t600); }
  .mining-row { gap: 10px; padding: 8px 0; box-shadow: inset 0 -1px 0 var(--line); }
  .mining-term { flex: 1; font-size: 13px; }
  .mining-meta { font-size: 11px; color: var(--t600); }
  .hl { color: var(--a300); }
  .group-tag { flex: none; }
  .inbank { font-size: 11.5px; flex: none; }
  .mining-foot { font-size: 11.5px; margin-top: 8px; }

  @media (max-width: 640px) {
    .battle { grid-template-columns: 1fr; }
    .gap-top, .mining-top { flex-direction: column; align-items: stretch; }
  }
</style>
