<script>
  import PageHead from '../components/PageHead.svelte'
  import SampleDialog from '../components/SampleDialog.svelte'
  import { api } from '../lib/api.js'
  import { project } from '../lib/stores/project.svelte.js'
  import { renderState } from '../lib/stores/render.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'

  // 迁自 ui.html:2857 vSamples。
  //
  // 旧版把数据和筛选状态放在全局 SMP / SMPF 里，靠 loadSamples() 手写刷新。
  // 这里改成组件内状态。但 sampleModal（仍在 legacy 里）保存后会调全局的
  // loadSamples() 和 load()，后者最终 bump renderTick——所以下面监听 tick
  // 重新拉数据，编辑样本后列表才会更新。

  const slug = $derived(project.data?.slug || '')
  // 复核弹窗现在由本组件持有，不再走 legacy 的 sampleModal
  let dialogKey = $state(null)

  let rows = $state([])
  let total = $state(0)
  let dates = $state([])
  let platforms = $state([])
  let ready = $state(false)
  const filter = $state({ date: '', platform: '', flag: '' })

  // 注意 manual 这里是「来源」列（人工采样得来），与「标记」列的 Manual（已人工核对）
  // 是两回事。共用一个 key 会让中文字典撞车，所以措辞上分开。
  const MODE = { api: 'API', manual: 'Hand-collected', extension: 'Extension' }

  let fetchSeq = 0

  async function fetchSamples() {
    if (!slug) return
    const mine = ++fetchSeq
    const q = new URLSearchParams({
      date: filter.date, platform: filter.platform, flag: filter.flag, limit: '300',
    })
    const r = await api(`/api/samples/${slug}?${q}`)
    // 连续改筛选时先发的可能后到：丢掉过期响应，否则下拉写着 09-20、
    // 表格里是 09-16 的行，顶部计数也按错的结果算。
    if (mine !== fetchSeq) return
    if (r && !r.error) {
      rows = r.rows || []
      total = r.total || 0
      dates = r.dates || []
      platforms = r.platforms || []
    }
    ready = true
  }

  // 依赖：项目变了、筛选变了、或外部数据变了（tick）都重新拉。
  // 结果写在 rows/total 等状态里，但它们不出现在这里，所以不会自激。
  $effect(() => {
    void project.data?.slug
    void filter.date; void filter.platform; void filter.flag
    void renderState.tick
    fetchSamples()
  })

  // 接口固定 limit=300 且没有翻页，这两个计数只覆盖当前这 300 条 —— 与全量
  // total 并排显示时必须说明，否则读起来是「全库只有 12 条要复核」。
  const review = $derived(rows.filter((r) => r.needs_review).length)
  const edited = $derived(rows.filter((r) => r.manual_override).length)
  const capped = $derived(rows.length >= 300)
</script>

<div class="page wide">
  <PageHead
    kicker={t('STATUS · SAMPLES')}
    title={t('Every AI answer\'s metadata, reviewable and correctable')}
    sub={t('Machine reading uses regex — brand-name collisions, negated context, and competitor aliases can all misfire. This is the only place to correct it: edits immediately recompute that day\'s metrics, corrected samples get marked manual, and re-sampling will not overwrite your verdict.')}
  />

  <div class="row filters">
    <label class="filt">{t('Date')}
      <select bind:value={filter.date}>
        <option value="">{t('All dates')}</option>
        {#each dates as d (d)}<option value={d}>{d}</option>{/each}
      </select>
    </label>
    <label class="filt">{t('Engine')}
      <select bind:value={filter.platform}>
        <option value="">{t('All engines')}</option>
        {#each platforms as p (p)}<option value={p}>{p}</option>{/each}
      </select>
    </label>
    <label class="filt">{t('Filter')}
      <select bind:value={filter.flag}>
        <option value="">{t('All samples')}</option>
        <option value="review">{t('Needs review only')}</option>
        <option value="edited">{t('Manually edited only')}</option>
      </select>
    </label>
    <span class="count">
      {t('{n} total').replace('{n}', String(total))}
      {#if capped}<span class="muted"> {t('(counting the first 300)')}</span>{/if}
      {#if review} · <span class="hl">{t('{n} need review').replace('{n}', String(review))}</span>{/if}
      {#if edited} · {t('{n} reviewed by hand').replace('{n}', String(edited))}{/if}
    </span>
  </div>

  <div class="tbl">
    <table class="table">
      <thead><tr>
        <th style="width:88px">{t('Date')}</th><th style="width:110px">{t('Engine')}</th>
        <th style="width:66px">{t('Source')}</th><th>{t('Question')}</th>
        <th style="width:74px">{t('Mention')}</th><th style="width:56px">{t('Rank')}</th>
        <th style="width:150px">{t('Competitors')}</th><th style="width:64px">{t('Citations')}</th>
        <th style="width:96px">{t('Flag')}</th><th style="width:60px"></th>
      </tr></thead>
      <tbody>
        {#each rows as r (r.key)}
          <tr class:review-row={r.needs_review}>
            <td class="c-date">{r.date}</td>
            <td class="c-plat">{r.platform_name || r.platform}</td>
            <td class="c-mode" title={(r.evidence_level || '') + (r.session_label ? ' · ' + r.session_label : '')}>
              {MODE[r.sample_mode] ? t(MODE[r.sample_mode]) : (r.sample_mode || '')}
              {#if r.session_mode && r.session_mode !== 'incognito'}
                <div class="c-sess" class:personal={r.session_mode === 'personal'}>
                  {r.session_mode === 'personal' ? t('Personal account') : t('Dedicated account')}
                </div>
              {/if}
            </td>
            <td class="c-q" title={r.question || ''}>{r.question || ''}</td>
            <td><span class="tag {r.brand_mentioned ? 'tag-accent' : 'tag-dim'}">{r.brand_mentioned ? t('Yes') : t('No')}</span></td>
            <td class="c-rank">{r.brand_rank || '—'}</td>
            <td class="c-comp" title={(r.competitors || []).join('、')}>{(r.competitors || []).join('、') || '—'}</td>
            <td class="c-cite">
              {r.citations || 0}{#if r.own_domain_cited} <span class="hl" title={t('Cited your site')}>·{t('own')}</span>{/if}
            </td>
            <td class="c-flags">
              {#if r.needs_review}
                <span class="tag tag-accent" title={(r.negative_cues || []).join('、') || t('Reading uncertain')}>{t('Needs review')}</span>
              {/if}
              {#if r.manual_override}<span class="tag tag-dim">{t('Manual')}</span>{/if}
            </td>
            <td><button class="btn btn-ghost view-btn" onclick={() => (dialogKey = r.key)}>{t('View')}</button></td>
          </tr>
        {:else}
          <tr><td colspan="10" class="muted empty">{ready ? t('No samples match the filter') : t('Loading…')}</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>

{#if dialogKey}
  <SampleDialog
    sampleKey={dialogKey}
    onclose={() => (dialogKey = null)}
    onchanged={() => { void renderState.tick; fetchSamples() }}
  />
{/if}

<style>
  .page.wide { max-width: 1360px; }
  .filters { gap: 14px; margin: 18px 0 12px; flex-wrap: wrap; }
  .filt { font-size: 12px; color: var(--t500); }
  .filt select {
    background: var(--deep); color: var(--text); border: 1px solid #3f424d;
    border-radius: 6px; padding: 4px 8px; font: inherit; font-size: 12.5px; margin-left: 4px;
  }
  .count { font-size: 12px; color: var(--t600); margin-left: auto; }
  .hl { color: var(--a300); }
  .review-row { background: rgba(145, 132, 217, .06); }
  .c-date { font-size: 12px; color: var(--t500); }
  .c-plat { font-size: 12.5px; }
  .c-mode { font-size: 11px; color: var(--t600); }
  .c-sess { font-size: 9.5px; color: var(--t700); }
  .c-sess.personal { color: var(--accent); }
  .c-q { font-size: 12.5px; max-width: 340px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .c-rank { font-size: 12.5px; color: var(--t400); }
  .c-comp { font-size: 11.5px; color: var(--t500); max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .c-cite { font-size: 12px; color: var(--t500); }
  .c-flags { font-size: 11px; }
  .view-btn { font-size: 11.5px; padding: 2px 7px; }
  .empty { padding: 16px; }
</style>
