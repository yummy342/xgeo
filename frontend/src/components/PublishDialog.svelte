<script>
  import { api, post } from '../lib/api.js'
  import { go } from '../lib/router.svelte.js'
  import { project, loadProject } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'

  // 取代 ui.html:2103 pubModal + 2130 doPublishSel。
  //
  // 旧版勾选状态从 DOM 读（document.querySelectorAll('.pub-ch:checked')），
  // 发布进度往 #pubprog 里 appendChild；这里都是响应式状态。
  // 上次勾选的渠道组合仍记在 localStorage（同一批文章通常发同一组渠道）。

  let { rel: relProp = '', onclose } = $props()

  const slug = $derived(project.data?.slug || '')
  // 工作台不传 rel 时，取当前成稿
  const rel = $derived(relProp || '')

  let pubs = $state([])
  let records = $state([])
  let picked = $state([])
  let progress = $state([])
  let busy = $state(false)

  const storeKey = $derived('pubSel:' + slug)

  $effect(() => {
    const s = slug
    if (!s) return
    let cancelled = false
    api('/api/publish/' + s).then((r) => {
      if (cancelled) return
      pubs = (r && r.publishers) || []
      records = (r && r.records) || []
      try {
        const saved = JSON.parse(localStorage.getItem('pubSel:' + s) || '[]')
        picked = saved.filter((c) => pubs.some((x) => x.code === c && !x.missing.length))
      } catch { picked = [] }
    })
    return () => { cancelled = true }
  })

  const readyOf = (code) => !((pubs.find((x) => x.code === code) || {}).missing || []).length

  function lastDone(code) {
    const hits = records.filter((r) => r.path === rel && r.ok && r.platform === code)
    return hits[hits.length - 1]
  }

  function toggle(code) {
    if (!readyOf(code)) return
    picked = picked.includes(code) ? picked.filter((c) => c !== code) : [...picked, code]
  }

  async function publishSelected() {
    if (!picked.length) { toast(t('Pick at least one channel first'), 'err'); return }
    try { localStorage.setItem(storeKey, JSON.stringify(picked)) } catch { /* 忽略 */ }

    const names = picked.map((c) => (pubs.find((x) => x.code === c) || {}).name || c)
    if (!confirm(t('Publish "{rel}" to {n} channels: {names}\n\nWeChat and WordPress only create drafts. Confirm?')
      .replace('{rel}', rel).replace('{n}', String(picked.length)).replace('{names}', names.join(', ')))) return

    busy = true
    progress = picked.map((c, i) => ({ name: names[i], state: 'doing', text: t('publishing…') }))

    let okN = 0
    const next = [...progress]
    for (let i = 0; i < picked.length; i++) {
      const r = await post('/api/publish/' + slug, { platform: picked[i], path: rel })
      if (r.ok) {
        okN++
        next[i] = { name: names[i], state: 'ok', text: t('published'), url: r.url || '', note: r.note || '' }
      } else {
        next[i] = { name: names[i], state: 'fail', text: r.error || '' }
      }
      progress = [...next]
    }
    busy = false
    toast(okN === picked.length
      ? t('Published to {n} channels').replace('{n}', String(okN))
      : t('{ok}/{n} channels succeeded — see the dialog for details').replace('{ok}', String(okN)).replace('{n}', String(picked.length)),
      okN === picked.length ? '' : 'err')
    // 刷新 content_pub，让计划页/问题库的发布状态同步；弹窗保留结果明细
    await loadProject(slug, true)
  }
</script>

<div class="modal" role="presentation">
  <div class="box">
    <h4>{t('Publish to channels')}</h4>
    <p class="muted sub">
      {t('File: {rel}. Tick the channels to publish this one article; WeChat and WordPress only create drafts, and go public after you confirm in their consoles.')
        .replace('{rel}', rel)}
    </p>

    {#each pubs as x (x.code)}
      {@const ok = !(x.missing || []).length}
      {@const done = lastDone(x.code)}
      <div class="row chan" class:disabled={!ok} class:picked={picked.includes(x.code)}
           role="button" tabindex="0"
           onclick={() => toggle(x.code)}
           onkeydown={(e) => { if (e.key === 'Enter') toggle(x.code) }}>
        <input type="checkbox" class="chk" checked={picked.includes(x.code)} disabled={!ok}
               onchange={() => toggle(x.code)} onclick={(e) => e.stopPropagation()}>
        <span class="cname">
          {x.name}<span class="muted note">{x.note}</span>
        </span>
        {#if done}
          <span class="done" title={done.url || ''}>{t('✓ sent {d}').replace('{d}', (done.at || '').slice(5, 10))}</span>
        {/if}
        {#if !ok}
          <button class="btn btn-ghost cfg" onclick={(e) => { e.stopPropagation(); onclose?.(); go('publishing') }}>
            {t('Missing credentials · configure')}
          </button>
        {/if}
      </div>
    {/each}

    {#if progress.length}
      <div class="progress">
        {#each progress as p (p.name)}
          <div class="pline" class:ok={p.state === 'ok'} class:fail={p.state === 'fail'}>
            {#if p.state === 'ok'}
              ✓ {p.name} {t('published')}
              {#if p.url} <a href={p.url} target="_blank" class="plink">{p.url.slice(0, 50)}</a>{:else} {p.note}{/if}
            {:else if p.state === 'fail'}
              ✗ {p.name} {t('failed:')} {p.text}
            {:else}
              → {p.name} {p.text}
            {/if}
          </div>
        {/each}
      </div>
    {/if}

    <div class="row actions">
      <button class="btn btn-ghost cfg" onclick={() => { onclose?.(); go('publishing') }}>{t('Channel config')}</button>
      <button class="btn btn-secondary" onclick={() => onclose?.()}>{t('Close')}</button>
      <button class="btn btn-primary" disabled={busy} onclick={publishSelected}>{t('Publish to selected')}</button>
    </div>
  </div>
</div>

<style>
  .sub { font-size: 12px; margin-top: 4px; }
  .chan { gap: 9px; padding: 7px 0; box-shadow: inset 0 -1px 0 var(--line); cursor: pointer; }
  .chan.disabled { cursor: default; opacity: .55; }
  .chan.picked { background: rgba(145, 132, 217, .06); }
  .chk { accent-color: var(--accent); }
  .cname { flex: 1; font-size: 13px; }
  .note { font-size: 11px; margin-left: 6px; }
  .done { font-size: 11px; color: var(--a300); }
  .cfg { font-size: 11.5px; padding: 2px 8px; }
  .progress { margin-top: 8px; }
  .pline { font-size: 12px; padding: 3px 0; color: var(--t400); }
  .pline.ok { color: var(--t400); }
  .pline.fail { color: var(--accent); }
  .plink { color: var(--a300); }
  .actions { justify-content: flex-end; margin-top: 12px; gap: 9px; }
</style>
