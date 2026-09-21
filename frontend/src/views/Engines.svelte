<script>
  import PageHead from '../components/PageHead.svelte'
  import { api } from '../lib/api.js'
  import { distRows } from '../lib/domain.js'
  import { go } from '../lib/router.svelte.js'
  import { pct } from '../lib/format.js'
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'
  import { ui } from '../lib/stores/ui.svelte.js'

  // 迁自 ui.html:1223 vEngines。
  // 旧版是 async 视图：`if(!KEYS) KEYS = await api('/api/keys')` 写在渲染路径里。
  // 这里改成 $effect 取数，结果留在组件内，不再往全局挂。
  // engSel 保持跨视图传参（竞品页点引擎标签会设它再跳过来）。

  const D = $derived(project.data || {})
  const a = $derived(D.analytics || {})
  const engs = $derived(a.engines || [])
  const slug = $derived(D.slug || '')

  let keys = $state([])

  const manual = $derived(keys.filter((k) => k.ok !== true && !engs.some((e) => e.platform === k.code)))
  const sel = $derived(ui.engSel || (engs[0] || {}).platform)
  const e = $derived(engs.find((x) => x.platform === sel))
  const ex = $derived(e && e.example)
  const brand = $derived(D.brand?.name || '')
  const own = $derived((D.brand?.site || '').replace(/^https?:\/\//, '').split('/')[0].replace(/^www\./, ''))

  // 样本原文里把品牌名加下划线高亮。旧代码拼字符串，这里保持同样的三段拼接，
  // 由 {excerptBefore}/{brand}/{excerptAfter} 分别渲染——Svelte 自动转义。
  const excerptParts = $derived.by(() => {
    if (!ex) return null
    const raw = ex.excerpt || ''
    if (ex.brand_pos >= 0) {
      // 用后端返回的 hit_text（实际命中的那个名字）算长度：命中的可能是别名，
      // 按 brand.length 切会吞掉或多留几个字符，而这段是标着 verbatim 的引文。
      const hit = ex.hit_text || brand
      return {
        before: raw.slice(0, ex.brand_pos),
        hit,
        after: raw.slice(ex.brand_pos + hit.length),
      }
    }
    return { before: raw, hit: '', after: '' }
  })

  const allDist = $derived(a.brand_dist
    && (((a.brand_dist.cn || []).length) || ((a.brand_dist.global || []).length)))

  function mktName(m) {
    return m === 'cn' ? t('CN market') : m === 'global' ? t('Global market') : t('Both markets')
  }

  $effect(() => {
    void project.data?.slug
    api('/api/keys').then((r) => {
      // 失败静默成空数组 → 「未覆盖引擎」那几行整片消失，看起来像是全覆盖了。
      if (r && r.error) { toast.error(r.error); keys = []; return }
      keys = Array.isArray(r) ? r : []
    })
  })

  function isMine(d) {
    return d === own || d.endsWith('.' + own)
  }
</script>

<div class="page">
  <PageHead
    kicker={t('STATUS · ENGINES')}
    title={t('The gap between engines is a gap in which sources they prefer')}
    sub={t('See what each engine cites — that is your build list. API and web-app results differ; search status is labeled per row.')}
  />

  <div class="tbl">
    <table class="table eng-table">
      <thead><tr>
        <th style="width:140px">{t('Engine')}</th><th style="width:70px">{t('Samples')}</th>
        <th style="width:90px">{t('Mention')}</th><th style="width:90px">{t('Rank')}</th>
        <th style="width:120px">{t('Cite share')}</th><th style="width:220px">{t('Actually cites')}</th>
        <th>{t('Verdict')}</th>
      </tr></thead>
      <tbody>
        {#each engs as x (x.platform)}
          <tr class="eng-row" onclick={() => { ui.engSel = x.platform }}>
            <td>
              <span class="eng-name" class:sel={x.platform === sel}>{x.label}</span>
              <div class="eng-sub">
                {mktName(x.market)} · {x.searched ? t('search') : t('parametric knowledge')}{x.avg_ms ? ` · ${t('median')} ${(x.avg_ms / 1000).toFixed(1)}s/${t('question')}` : ''}
              </div>
            </td>
            <td class="cell-soft">{x.samples}</td>
            <td><span class="tag {(x.mention || 0) > 0 ? 'pill-good' : 'pill-warn'}">{pct(x.mention)}</span></td>
            <td class="cell-soft">{x.pos_median == null ? '—' : x.pos_median}</td>
            <td class="cell-soft">
              {pct(x.cite_share)}<span class="muted cite-count"> {x.cite_counts[0]}/{x.cite_counts[1]}</span>
            </td>
            <td class="cell-dim">{(x.top_sources || []).join(' / ') || '—'}</td>
            <td class="cell-soft">
              {#if x.neg_n}
                <span class="tag tag-accent neg-tag" title={t('Samples hit negative cue words near the brand — review them in the sample replay')}>{t('suspected negative')} {x.neg_n}</span>
              {/if}
              {x.verdict}
            </td>
          </tr>
        {/each}
        {#each manual as k (k.code)}
          <tr class="manual-row">
            <td>
              <span class="eng-name">{k.label}</span>
              <div class="eng-sub">{mktName(k.market)} · {k.ok === false ? t('missing API key') : t('manual sampling only')}</div>
            </td>
            <td class="cell-dim">0</td>
            <td><span class="tag tag-dim">{t('Not sampled')}</span></td>
            <td class="cell-dim">—</td>
            <td class="cell-dim">—</td>
            <td class="cell-dim">{k.ok === false ? t('Auto-samples once {e} is configured').replace('{e}', k.env) : t('Export a manual sheet and fill it in question by question')}</td>
            <td>
              <button class="btn btn-ghost sm" onclick={() => go(k.ok === false ? 'settings' : 'report')}>
                {k.ok === false ? t('Configure') : t('Sampling sheet')}
              </button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  <p class="muted table-foot">{t('Grey rows are engines not yet covered — those are where the largest real user volume sits (web and app), so the metric gap is measured against them.')}</p>

  {#if e}
    <div class="eng-detail">
      <div class="card elev panel">
        <div class="panel-t">{t('Sample replay · {l}').replace('{l}', e.label)}</div>
        <div class="panel-s">
          {ex ? t('Question: "{q}" · {d} · verbatim sample').replace('{q}', ex.question).replace('{d}', ex.date) : t('No samples this round')}
        </div>
        {#if excerptParts}
          <div class="excerpt">
            {excerptParts.before}{#if excerptParts.hit}<span class="uln">{excerptParts.hit}</span>{/if}{excerptParts.after}…
          </div>
          <div class="row ex-tags">
            <span class="tag tag-neutral">{ex.mentioned ? t('Mentioned · rank {r}').replace('{r}', String(ex.rank || '—')) : t('Not mentioned')}</span>
            <span class="tag tag-neutral">{ex.n_cites} {t('citation sources')}{ex.own_cited ? t(', including your domain') : t(', none from you')}</span>
            {#if (ex.negative_cues || []).length}
              <span class="tag tag-accent" title={t('Cue words: {l}').replace('{l}', ex.negative_cues.join(', '))}>{t('Suspected negative · review')}</span>
            {/if}
            <span class="tag tag-outline ex-cta" role="button" tabindex="0"
                  onclick={(ev) => { ev.stopPropagation(); go('gaps', { gapTab: 'fact' }) }}
                  onkeydown={(ev) => { if (ev.key === 'Enter') go('gaps', { gapTab: 'fact' }) }}>{t('Got it wrong? Log a fact deviation')}</span>
          </div>
        {/if}
      </div>

      <div class="card elev panel">
        <div class="panel-t">{t('Who this engine mentions')}</div>
        <div class="panel-s">{t('Share of unprompted samples mentioning each brand (⭑ = you).')}</div>
        {@html distRows(e.brand_dist, D.brand?.name)}
        <button class="btn btn-ghost self-start" onclick={() => go('competitors')}>{t('Full market in Competitors →')}</button>
      </div>

      <div class="card elev panel">
        <div class="panel-t">{t('What this engine cites most')}</div>
        <div class="panel-s">{t('Each one is a slot that could have been you.')}</div>
        {#each (e.top_sources || []) as d (d)}
          <div class="src-row">
            <span class="dot" style="background:{isMine(d) ? 'var(--a400)' : '#595d6c'}"></span>
            <span class="src-name">{d}{#if isMine(d)} <span class="tag pill-good you-tag">{t('you')}</span>{/if}</span>
          </div>
        {:else}
          <div class="muted panel-s">{t('This engine returned no citation sources this round (it may not search)')}</div>
        {/each}
        <button class="btn btn-ghost self-start" onclick={() => go('channels')}>{t('All channels in Channel Map →')}</button>
      </div>
    </div>
  {/if}

  {#if allDist}
    <h4 class="dist-h">{t('All engines · brand mention distribution')}</h4>
    <p class="muted dist-s">
      {t('Share of unprompted samples mentioning each brand (aliases merged). Scope: only you and configured competitors — a brand you have not configured will not appear, so the fuller the competitor list the truer the distribution. Add them under Settings → edit brand config.')}
    </p>
    <div class="dist-grid">
      {#each [['cn', t('CN market')], ['global', t('Global market')]] as [m, l] (m)}
        {@const list = (a.brand_dist || {})[m] || []}
        {#if list.length}
          {@const ns = ((a.competitors || {}).sample_ns || {})[m] || 0}
          <div class="card elev panel">
            <div class="dist-t">{l}<span class="muted dist-ns"> · {t('denominator {n} unprompted samples').replace('{n}', String(ns))}</span></div>
            {@html distRows(list, D.brand?.name)}
          </div>
        {/if}
      {/each}
    </div>
  {/if}
</div>

<style>
  .eng-table { margin-top: 22px; }
  .eng-row { cursor: pointer; }
  .eng-name { font-size: 14px; }
  .eng-name.sel { color: var(--a300); }
  .eng-sub { font-size: 10.5px; color: var(--t600); }
  .manual-row { opacity: .65; }
  .cell-soft { font-size: 13px; color: var(--t400); }
  .cell-dim { font-size: 12.5px; color: var(--t600); }
  .cite-count { font-size: 10.5px; }
  .neg-tag { cursor: help; }
  .sm { font-size: 12px; }
  .table-foot { font-size: 12px; margin-top: 8px; }

  .eng-detail { display: grid; grid-template-columns: 1.1fr .95fr .95fr; gap: 14px; margin-top: 26px; }
  .panel { padding: 18px; }
  .panel-t { font-size: 15px; font-weight: 500; }
  .panel-s { font-size: 11.5px; color: var(--t600); margin-bottom: 8px; }
  .excerpt { padding: 13px; border-radius: var(--r-md); background: var(--deep); font-size: 13px; line-height: 1.65; color: #cfd3e5; }
  .ex-tags { margin-top: 10px; font-size: 11.5px; }
  .ex-cta { cursor: pointer; }
  .self-start { align-self: flex-start; margin-top: 8px; }

  .src-row { display: flex; align-items: center; gap: 10px; padding: 9px 0; box-shadow: inset 0 -1px 0 var(--line); }
  .src-name { flex: 1; font-size: 13px; }
  .you-tag { font-size: 10px; }

  .dist-h { font-size: 16px; margin: 28px 0 6px; }
  .dist-s { font-size: 12px; margin-bottom: 10px; }
  .dist-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .dist-t { font-size: 13.5px; font-weight: 500; margin-bottom: 6px; }
  .dist-ns { font-size: 11px; font-weight: 400; }

  @media (max-width: 640px) {
    .eng-detail, .dist-grid { grid-template-columns: 1fr; }
  }
</style>
