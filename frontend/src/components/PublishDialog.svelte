<script>
  import { api, post } from '../lib/api.js'
  import { go } from '../lib/router.svelte.js'
  import { project, loadProject } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'
  import { safeUrl } from '../lib/url.js'
  import ManualPublishDialog from './ManualPublishDialog.svelte'

  // 取代 ui.html:2103 pubModal + 2130 doPublishSel。
  //
  // 旧版勾选状态从 DOM 读（document.querySelectorAll('.pub-ch:checked')），
  // 发布进度往 #pubprog 里 appendChild；这里都是响应式状态。
  // 上次勾选的渠道组合仍记在 localStorage（同一批文章通常发同一组渠道）。
  //
  // 渠道分两类，交互根本不同，不能挤在一个勾选列表里：
  //   api  服务端有外发能力（带凭证），勾选后统一提交 —— 就是下面这个串行循环
  //   semi 服务端没有外发能力（平台规则不允许），只能备好内容、由人复制粘贴发布
  //        → 交给 ManualPublishDialog，不进 picked、不进循环、不参与「立即发布」

  let { rel: relProp = '', onclose } = $props()

  const slug = $derived(project.data?.slug || '')
  // 工作台不传 rel 时，取当前成稿
  const rel = $derived(relProp || '')

  let pubs = $state([])
  let records = $state([])
  let picked = $state([])
  let progress = $state([])
  let busy = $state(false)
  // 直发。默认关着：外发是收不回来的动作，默认值应该是保守的那一侧。
  // 但必须给出口——只建草稿的话，稿子会停在渠道后台等人去点，
  // 而那个「人」不存在（三篇文章在 Drafts 里躺了三天）。
  let direct = $state(false)
  // 正在走半自动流程的渠道码；非空时盖一个 ManualPublishDialog
  let manual = $state('')

  const storeKey = $derived('pubSel:' + slug)
  const pathOf = (x) => x.path || ((x.paths || []).includes('semi') ? 'semi' : 'api')
  const autos = $derived(pubs.filter((x) => pathOf(x) === 'api'))
  const semis = $derived(pubs.filter((x) => pathOf(x) === 'semi'))

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
        // 只恢复自动渠道：半自动渠道不进勾选集合，混进来会让「发布到已选」错判
        picked = saved.filter((c) => pubs.some(
          (x) => x.code === c && !x.missing.length && pathOf(x) === 'api'))
      } catch { picked = [] }
    })
    return () => { cancelled = true }
  })

  const readyOf = (code) => !((pubs.find((x) => x.code === code) || {}).missing || []).length

  function lastDone(code) {
    // 排除「已备好（prepared）」：它的记录也是 ok:true，拿来标「✓ sent」会把
    // 「备好了还没贴」说成发出去了。两条路都要排 —— 之前只给半自动那列传了
    // onlyPublished，自动那列没传，于是「先按半自动备好、后来补齐凭证转回自动」
    // 的渠道（reddit/公众号）会显示成已发出。
    const hits = records.filter((r) => r.path === rel && r.ok && r.platform === code
      && r.state !== 'prepared')
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
    const ask = direct
      ? t('Publish "{rel}" to {n} channels: {names}\n\nThese go public immediately. Confirm?')
      : t('Publish "{rel}" to {n} channels: {names}\n\nWeChat, WordPress and dev.to only create drafts — they go public after you confirm in their consoles. Confirm?')
    if (!confirm(ask.replace('{rel}', rel).replace('{n}', String(picked.length)).replace('{names}', names.join(', ')))) return

    busy = true
    progress = picked.map((c, i) => ({ name: names[i], state: 'doing', text: t('publishing…') }))

    let okN = 0
    const next = [...progress]
    for (let i = 0; i < picked.length; i++) {
      const r = await post('/api/publish/' + slug, { platform: picked[i], path: rel, published: direct })
      if (r.ok) {
        okN++
        // 调用成功 ≠ 对外可见。dev.to 没直发时只建草稿，回的是 ok:true，
        // 这里必须按渠道报回的 state 显示，否则又把草稿说成已发布。
        next[i] = { name: names[i], state: 'ok', draft: r.state === 'draft',
                    text: t('published'), url: r.url || '', note: r.note || '' }
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

    {#if autos.length}
      <div class="ghead">{t('Automatic channels')}
        <span class="muted note">{t('Tick them and the server publishes for you.')}</span>
      </div>
      {#each autos as x (x.code)}
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
    {/if}

    {#if semis.length}
      <div class="ghead">{t('Semi-automatic channels')}
        <span class="muted note">{t('Platform rules forbid auto-posting. The tool prepares the content and opens the page; you publish it.')}</span>
      </div>
      {#each semis as x (x.code)}
        {@const done = lastDone(x.code)}
        <div class="row chan semi">
          <span class="cname">
            {x.name}<span class="muted note">{x.note}</span>
          </span>
          {#if done}
            <span class="done" title={done.url || ''}>{t('✓ sent {d}').replace('{d}', (done.at || '').slice(5, 10))}</span>
          {/if}
          <button class="btn btn-ghost cfg" onclick={() => (manual = x.code)}>{t('Prepare & copy')}</button>
        </div>
      {/each}
    {/if}

    {#if progress.length}
      <div class="progress">
        {#each progress as p (p.name)}
          <div class="pline" class:ok={p.state === 'ok'} class:fail={p.state === 'fail'}>
            {#if p.state === 'ok'}
              ✓ {p.name} {p.draft ? t('Draft — confirm it in the channel console') : t('published')}
              {#if safeUrl(p.url)} <a href={safeUrl(p.url)} target="_blank" class="plink">{p.url.slice(0, 50)}</a>{:else if p.url} <span class="plink">{p.url.slice(0, 50)}</span>{:else} {p.note}{/if}
            {:else if p.state === 'fail'}
              ✗ {p.name} {t('failed:')} {p.text}
            {:else}
              → {p.name} {p.text}
            {/if}
          </div>
        {/each}
      </div>
    {/if}

    {#if autos.length}
      <label class="direct">
        <input type="checkbox" class="chk" bind:checked={direct} />
        <span>{t('Publish immediately, skip the draft step')}
          <span class="muted note">{t('Channels that support it go public as soon as this returns — no console visit afterwards.')}</span>
        </span>
      </label>
    {/if}

    <div class="row actions">
      <button class="btn btn-ghost cfg" onclick={() => { onclose?.(); go('publishing') }}>{t('Channel config')}</button>
      <button class="btn btn-secondary" onclick={() => onclose?.()}>{t('Close')}</button>
      {#if autos.length}
        <button class="btn btn-primary" disabled={busy} onclick={publishSelected}>{t('Publish to selected')}</button>
      {/if}
    </div>
  </div>
</div>

{#if manual}
  <ManualPublishDialog rel={rel} code={manual}
                       onclose={() => (manual = '')}
                       ondone={() => loadProject(slug, true)} />
{/if}

<style>
  .sub { font-size: 12px; margin-top: 4px; }
  .ghead { font-size: 11.5px; color: var(--t600); margin: 12px 0 2px;
           text-transform: uppercase; letter-spacing: .04em; }
  .ghead .note { text-transform: none; letter-spacing: 0; }
  .chan { gap: 9px; padding: 7px 0; box-shadow: inset 0 -1px 0 var(--line); cursor: pointer; }
  .chan.disabled { cursor: default; opacity: .55; }
  .chan.semi { cursor: default; }
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
  .direct { display: flex; align-items: flex-start; gap: 8px; margin-top: 10px;
            font-size: 12.5px; line-height: 1.5; cursor: pointer; }
</style>
