<script>
  // 取代 ui.html:2897 的 sampleModal。
  //
  // 旧版是往 #modal 注入 HTML 字符串，字段值靠 $('#sm-men').value 读回来，
  // 保存后还要靠 `SMP = null; loadSamples()` 这个全局缓存链去刷新列表——
  // 那条链在 B6 里被误删过，复核功能实际是坏的。
  // 现在表单用 bind:value，保存后直接回调父组件重新取数。
  import { api, post } from '../lib/api.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'
  import { project } from '../lib/stores/project.svelte.js'

  let { sampleKey, onclose, onchanged } = $props()

  const slug = $derived(project.data?.slug || '')
  const own = $derived(
    ((project.data?.brand && project.data.brand.site) || '')
      .replace(/^https?:\/\//, '').replace(/^www\./, '').split('/')[0],
  )

  let data = $state(null)
  let loadError = $state('')
  let busy = $state(false)

  // 表单字段
  let mentioned = $state(false)
  let rank = $state(0)
  let comps = $state('')
  let note = $state('')

  $effect(() => {
    const key = sampleKey
    if (!key) return
    let cancelled = false
    api(`/api/sample/${slug}?key=${encodeURIComponent(key)}`).then((r) => {
      if (cancelled) return
      if (!r || r.error) { loadError = t('Failed to load'); return }
      data = r
      const a = r.analysis || {}
      mentioned = !!a.brand_mentioned
      rank = a.brand_rank || 0
      comps = (a.competitors_mentioned || []).join('、')
      note = r.review_note || ''
    })
    return () => { cancelled = true }
  })

  const cites = $derived(data?.citations || [])
  const analysis = $derived(data?.analysis || {})

  // 源站构成：这条答案的引用来自哪些域名、各占多少
  const domains = $derived.by(() => {
    const dom = {}
    for (const c of cites) {
      try {
        const h = new URL(c.url).hostname.replace(/^www\./, '')
        dom[h] = (dom[h] || 0) + 1
      } catch { /* 坏 URL 跳过 */ }
    }
    return Object.entries(dom).sort((a, b) => b[1] - a[1])
  })

  function isMine(host) {
    return !!own && (host === own || host.endsWith('.' + own))
  }

  async function save(clearReview) {
    busy = true
    const patch = {
      brand_mentioned: mentioned,
      brand_rank: parseInt(String(rank), 10) || 0,
      competitors_mentioned: comps.split(/[、,，]/).map((s) => s.trim()).filter(Boolean),
      review_note: note.trim(),
    }
    if (clearReview) patch.needs_review = false
    const r = await post('/api/sample/' + slug, { key: sampleKey, patch })
    busy = false
    if (!r.ok) { toast(r.error || t('Save failed'), 'err'); return }
    toast(t('Saved — that day\'s metrics were recomputed'))
    onchanged?.()
    onclose?.()
  }

  async function remove() {
    if (!confirm(t('Delete this sample? That day\'s metrics will be recomputed, and this cannot be undone.'))) return
    busy = true
    const r = await post('/api/sample/' + slug, { key: sampleKey, patch: { delete: true } })
    busy = false
    if (!r.ok) { toast(r.error || t('Delete failed'), 'err'); return }
    toast(t('Deleted — metrics recomputed'))
    onchanged?.()
    onclose?.()
  }
</script>

<div class="modal" role="presentation">
  <div class="box">
    {#if loadError}
      <p class="soft">{loadError}</p>
    {:else if !data}
      <p class="soft">{t('Loading…')}</p>
    {:else}
      <h4 class="q">{data.question || ''}</h4>
      <div class="row meta">
        <span class="tag tag-outline">{data.platform_name || data.platform}</span>
        <span class="tag tag-dim">{data.date || ''}</span>
        <span class="tag tag-dim">{data.evidence_level || ''}</span>
        {#if data.session_label}
          <span class="tag tag-outline" title={t('Sampling environment — samples from different environments should not be averaged together')}>{data.session_label}</span>
        {/if}
        {#if data.manual_override}<span class="tag tag-accent">{t('Reviewed by hand')}</span>{/if}
        <span class="info">{data.terminal || ''} · {data.sample_mode || ''} · {(data.answer || '').length} {t('chars')}</span>
      </div>

      <div class="label">{t('Verbatim answer')}</div>
      <div class="answer">{data.answer || ''}</div>

      {#if cites.length}
        <div class="label">{t('Citations ({n}) · source makeup').replace('{n}', String(cites.length))}</div>
        <div class="row dom-row">
          {#each domains as [h, n] (h)}
            <span class="tag {isMine(h) ? 'tag-accent' : 'tag-dim'} dom-tag" title={isMine(h) ? t('your site') : ''}>
              {h} ×{n} · {Math.round(n / cites.length * 100)}%
            </span>
          {/each}
        </div>
        <div class="cites">
          {#each cites as c (c.url)}
            <div class="cite">
              <a href={c.url} target="_blank" class="cite-url">{c.url}</a>
              <span class="cite-title">{c.title || ''}</span>
            </div>
          {/each}
        </div>
      {/if}

      <div class="label review-label">{t('Manual review (saving recomputes the day\'s metrics immediately)')}</div>
      <div class="row fields">
        <label class="small">{t('Brand mentioned')}
          <select bind:value={mentioned} class="minisel">
            <option value={true}>{t('Yes')}</option>
            <option value={false}>{t('No')}</option>
          </select>
        </label>
        <label class="small">{t('Rank')}
          <input type="number" class="input rank-input" bind:value={rank}>
        </label>
        <label class="small comp-label">{t('Competitors (comma separated)')}
          <input class="input" bind:value={comps}>
        </label>
      </div>
      <div class="field note-field">
        <label>{t('Review note')}</label>
        <input class="input" bind:value={note} placeholder={t('e.g. brand name collided with another word, not actually mentioned')}>
      </div>
      {#if (analysis.negative_cues || []).length}
        <div class="small neg">{t('Negative cue words: {l} — judge by hand whether it is really negative').replace('{l}', analysis.negative_cues.join(', '))}</div>
      {/if}

      <div class="row actions">
        <button class="btn btn-ghost del" disabled={busy} onclick={remove}>{t('Delete this sample')}</button>
        {#if data.needs_review}
          <button class="btn btn-secondary" disabled={busy} onclick={() => save(true)}>{t('Mark as reviewed')}</button>
        {/if}
        <button class="btn btn-secondary" onclick={() => onclose?.()}>{t('Cancel')}</button>
        <button class="btn btn-primary" disabled={busy} onclick={() => save(false)}>{t('Save')}</button>
      </div>
    {/if}
  </div>
</div>

<style>
  .box { max-width: 720px; }
  .q { font-size: 16px; }
  .meta { gap: 6px; margin-top: 6px; flex-wrap: wrap; }
  .info { font-size: 11.5px; color: var(--t600); }
  .label { font-size: 12px; color: var(--t600); margin: 12px 0 3px; }
  .review-label { margin: 14px 0 4px; }
  .answer {
    max-height: 210px; overflow: auto; background: var(--deep); border-radius: 8px;
    padding: 10px 12px; font-size: 12.5px; line-height: 1.65;
    white-space: pre-wrap; color: var(--t400);
  }
  .dom-row { gap: 5px; flex-wrap: wrap; margin-bottom: 6px; }
  .dom-tag { font-size: 11px; }
  .cites { max-height: 110px; overflow: auto; font-size: 11.5px; line-height: 1.7; }
  .cite { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cite-url { color: var(--a300); }
  .cite-title { color: var(--t600); }
  .fields { gap: 8px; flex-wrap: wrap; }
  .small { font-size: 12px; }
  .minisel {
    background: var(--deep); color: var(--text); border: 1px solid #3f424d;
    border-radius: 6px; padding: 4px 8px; font: inherit; margin-left: 4px;
  }
  .rank-input { width: 64px; display: inline-block; padding: 4px 8px; }
  .comp-label { flex: 1; min-width: 220px; }
  .note-field { margin-top: 8px; }
  .neg { color: var(--a300); margin-top: 4px; }
  .actions { justify-content: flex-end; margin-top: 14px; gap: 9px; }
  .del { margin-right: auto; color: var(--t500); }
</style>
