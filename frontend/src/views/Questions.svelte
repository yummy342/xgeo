<script>
  // 迁自 ui.html:1469 vQuestions。
  // qGroup 原本是全局 ST.qGroup，下沉成组件内 $state。
  // demandSort/demandTag 读 window.EXPD（桥注入），仍是 legacy 实现，直接复用。
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { go } from '../lib/router.svelte.js'
  import { pct } from '../lib/format.js'
  import PageHead from '../components/PageHead.svelte'
  import PublishDialog from '../components/PublishDialog.svelte'

  let publishRel = $state(null)

  const a = $derived(project.data?.analytics || {})
  const contentPub = $derived(project.data?.content_pub || [])

  let group = $state(null)

  // qid → 已发布渠道 / 承接成稿文件。旧代码把这两个挂在 window 上供 pubModal 使用，
  // 这里照旧——弹窗仍是 legacy 实现，读的就是这两个全局。
  const pubMaps = $derived.by(() => {
    const pubQ = {}
    const qFile = {}
    for (const f of contentPub) {
      for (const q of (f.qids || [])) {
        qFile[q] = qFile[q] || f.path
        if ((f.published || []).length) pubQ[q] = (f.published || []).map((p) => p.platform_name).join('、')
      }
    }
    window.__pubQ = pubQ
    window.__qFile = qFile
    return { pubQ, qFile }
  })

  const all = $derived(window.demandSort ? window.demandSort(a.questions || []) : (a.questions || []))
  const groups = $derived(a.question_groups || [])
  const qs = $derived(group ? all.filter((q) => q.group === group) : all)
  const hasExpand = $derived(!!project.data?.expand)

  const KIND_COLOR = { 买家: 'var(--a300)', 教育: 'var(--t400)', 探测: 'var(--t600)' }

  function mktName(m) {
    return m === 'cn' ? t('CN market') : m === 'global' ? t('Global market') : t('Both markets')
  }
</script>

<div class="page">
  <div class="row q-head">
    <div>
      <PageHead
        kicker={t('STATUS · QUESTIONS')}
        title={t('{n} questions — the source of every number on this board').replace('{n}', String(qs.length))}
        sub={t('A "question" is something a real user would ask an AI. Editing these changes every number in the product. Items marked with a name-check belong to brand awareness probing, which is excluded from mention rate.')}
      />
    </div>
    <div class="row" style="flex:none">
      <button class="btn btn-ghost" onclick={() => window.showMethod()}>{t('Generation rules')}</button>
      <button class="btn btn-secondary" onclick={() => window.editQuestions()}>{t('Edit questions')}</button>
      <button class="btn btn-secondary" onclick={() => window.expandModal()}>{t('Mine topics')}</button>
      <button class="btn btn-primary" onclick={() => window.runAction('bootstrap')}>{t('AI add topics')}</button>
    </div>
  </div>

  {#if groups.length}
    <div class="gcards">
      {#each groups as g (g.group)}
        <div class="card elev gcard" class:on={group === g.group} title={g.note || ''}
             onclick={() => (group = group === g.group ? null : g.group)}>
          <div class="row gcard-top">
            <span class="gcard-name">{g.group}</span>
            <span class="gcard-kind" style="color:{KIND_COLOR[g.kind] || 'var(--t600)'}">{g.kind}</span>
            <span class="gcard-total">{t('{n} questions').replace('{n}', String(g.total))}</span>
          </div>
          <div class="gcard-rate" style="color:{g.mention_rate == null ? 'var(--t600)' : (g.mention_rate > 0 ? 'var(--a300)' : 'var(--accent)')}">
            {g.kind === '探测' ? '—' : (g.mention_rate == null ? t('Untested') : pct(g.mention_rate))}
          </div>
          <div class="gcard-sub">
            {#if g.kind === '探测'}
              {t('Name-check questions do not count toward mention rate')}
            {:else}
              {t('{n} sampled').replace('{n}', String(g.sampled))}{#if g.lost} · <span class="lost">{t('{n} lost').replace('{n}', String(g.lost))}</span>{/if}{#if g.no_content} · {t('{n} without content').replace('{n}', String(g.no_content))}{/if}
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}

  <div class="row sort-row">
    {#if group}
      <span class="tag tag-accent filter-chip" onclick={() => (group = null)}>{t('Only {g} ✕').replace('{g}', group)}</span>
      <span class="sort-note">{qs.length} / {all.length} {t('questions')}</span>
    {:else}
      <span class="sort-note">{t('Click a group card above to filter')}</span>
    {/if}
    <span class="sort-hint">
      {hasExpand ? t('Sorted by "rising demand + not mentioned + no content" — the top is your topic pool') : t('Sorted by "not mentioned + no content" — the top is your topic pool')}
    </span>
  </div>

  <div class="tbl">
    <table class="table">
      <thead><tr>
        <th>{t('Question')}</th><th style="width:70px">{t('Group')}</th><th style="width:70px">{t('Market')}</th>
        <th style="width:96px">{t('Your mention')}</th><th style="width:96px">{t('Diagnosis')}</th>
        <th style="width:100px">{t('Has content')}</th><th style="width:90px"></th>
      </tr></thead>
      <tbody>
        {#each qs as q, i (q.id)}
          {#if q.brand_probe && (i === 0 || !qs[i - 1].brand_probe)}
            <tr><td colspan="7" class="probe-sep">{t('Brand awareness · name-check probes (shows whether the brand gets repeated; excluded from mention rate and from topic ranking above)')}</td></tr>
          {/if}
          <tr>
            <td class="q-text">
              {q.text}{#if q.brand_probe} <span class="tag tag-dim probe-tag">{t('name-check')}</span>{:else}{@html window.demandTag(q.id)}{/if}
            </td>
            <td><span class="tag tag-neutral">{q.group}</span></td>
            <td class="mkt-cell">{mktName(q.market)}</td>
            <td><span class="tag {(q.mention || 0) > 0 ? 'pill-good' : 'pill-warn'}">{q.mention == null ? t('Not sampled') : pct(q.mention)}</span></td>
            <td>{#if q.brand_probe}<span class="dash">—</span>{:else}{@html window.diagTag(q.diagnosis)}{/if}</td>
            <td class="content-cell" class:done={q.content === '已成稿'}>
              {q.content}{#if pubMaps.pubQ[q.id]} <span class="tag tag-accent pub-tag" title={pubMaps.pubQ[q.id]}>{t('Published')}</span>{/if}
            </td>
            <td>
              <div class="row" style="gap:2px">
                <button class="btn btn-ghost sm" onclick={() => go('workbench', { wq: q.id })}>{t('Write')}</button>
                {#if pubMaps.qFile[q.id]}
                  <button class="btn btn-ghost sm pub-btn" title={t('Publish the draft for this question: {p}').replace('{p}', pubMaps.qFile[q.id])}
                          onclick={() => (publishRel = 'content/' + pubMaps.qFile[q.id])}>{t('Publish')}</button>
                {/if}
              </div>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>

{#if publishRel}
  <PublishDialog rel={publishRel} onclose={() => (publishRel = null)} />
{/if}

<style>
  .q-head { align-items: flex-end; justify-content: space-between; gap: 20px; }
  .gcards { display: grid; grid-template-columns: repeat(auto-fit, minmax(168px, 1fr)); gap: 10px; margin: 18px 0 14px; }
  .gcard { padding: 13px 14px; gap: 3px; cursor: pointer; }
  .gcard.on { box-shadow: 0 0 0 1px var(--a700); }
  .gcard-top { gap: 5px; }
  .gcard-name { font-size: 13.5px; font-weight: 500; }
  .gcard-kind { font-size: 10px; }
  .gcard-total { margin-left: auto; font-size: 11.5px; color: var(--t600); }
  .gcard-rate { font-size: 19px; font-weight: 500; }
  .gcard-sub { font-size: 10.5px; color: var(--t600); }
  .lost { color: var(--accent); }

  .sort-row { margin: 0 0 12px; font-size: 12px; color: var(--t500); }
  .filter-chip { cursor: pointer; }
  .sort-note { color: var(--t600); }
  .sort-hint { margin-left: auto; }

  .q-text { font-size: 13.5px; }
  .probe-sep { padding: 16px 12px 6px; font-size: 12px; color: var(--t500); }
  .probe-tag { font-size: 10px; }
  .dash { font-size: 12px; color: var(--t600); }
  .mkt-cell { font-size: 12.5px; color: var(--t500); }
  .content-cell { font-size: 12.5px; color: var(--t500); }
  .content-cell.done { color: var(--a300); }
  .pub-tag { font-size: 10px; }
  .sm { font-size: 12px; }
  .pub-btn { color: var(--a300); }

  @media (max-width: 640px) {
    .q-head { flex-direction: column; align-items: stretch; }
  }
</style>
