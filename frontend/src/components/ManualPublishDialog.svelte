<script>
  import { post } from '../lib/api.js'
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'

  // 半自动发布：给没有自动发布通路的渠道（Reddit / 搜狐号 / 头条号 / 知乎 / CSDN /
  // 百家号 / 微博 / 什么值得买）备好内容，人复制粘贴发布，再回填公开链接。
  //
  // 与 PublishDialog 的分工：那个是「勾选一批渠道 → 服务端逐个外发」，渠道自带凭证；
  // 这个渠道**没有任何外发能力**，服务端只做组装（prepare），发布动作发生在人的浏览器里。
  // 所以两边不能共用一个交互：这里的核心是「复制」与「打开发布页」，不是勾选提交。
  //
  // 传 id 进来 = 回填模式（从发布记录里点「去回填」），不重新备好。

  let { rel = '', code = '', id = '', onclose, ondone } = $props()

  const slug = $derived(project.data?.slug || '')
  let payload = $state(null)
  let err = $state('')
  let url = $state('')
  let busy = $state(false)
  let previewEl = $state(null)

  $effect(() => {
    const s = slug, c = code
    if (!s || !c || id) return          // 回填模式不用备好
    let cancelled = false
    err = ''
    post(`/api/publish/${s}/prepare`, { platform: c, path: rel }).then((r) => {
      if (cancelled) return
      if (!r || !r.ok) { err = (r && r.error) || t('Prepare failed'); return }
      payload = r
    })
    return () => { cancelled = true }
  })

  // 只放行 http(s)：发布页地址来自注册表（数据），但它会被拼进 window.open ——
  // 数据写错一个 javascript: 就是执行。同 Publishing.svelte 的 safeUrl 口径。
  const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? u : '')

  async function copyText(text, okMsg) {
    try {
      await navigator.clipboard.writeText(text || '')
      toast(okMsg || t('Copied'))
      return true
    } catch {
      // 非安全上下文（自建纯 http 域名）没有 clipboard API：退回选中预览节点
      return selectAndCopy()
    }
  }

  async function copyRich() {
    const html = payload?.body || ''
    const plain = payload?.body_plain || stripTags(html)
    try {
      await navigator.clipboard.write([new ClipboardItem({
        'text/html': new Blob([html], { type: 'text/html' }),
        'text/plain': new Blob([plain], { type: 'text/plain' }),
      })])
      toast(t('Copied'))
      return true
    } catch {
      return selectAndCopy()
    }
  }

  function selectAndCopy() {
    if (!previewEl) { toast(t('Copy failed — select the text and copy it manually'), 'err'); return false }
    const r = document.createRange()
    r.selectNodeContents(previewEl)
    const sel = getSelection()
    sel.removeAllRanges()
    sel.addRange(r)
    const ok = document.execCommand('copy')
    toast(ok ? t('Copied') : t('Copy failed — select the text and copy it manually'), ok ? '' : 'err')
    return ok
  }

  const stripTags = (h) => (h || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()

  async function copyBodyAndOpen() {
    const isHtml = (payload?.copy_as || '') === 'html'
    const ok = isHtml ? await copyRich() : await copyText(payload?.body, t('Copied'))
    const u = safeUrl(payload?.publish_url)
    if (u) window.open(u, '_blank', 'noopener')
    else if (ok) toast(t('Publish page address is not confirmed yet — open the site yourself'), 'err')
  }

  async function mark(publish) {
    if (publish && !url.trim()) { toast(t('Fill in the public link you got from the channel'), 'err'); return }
    busy = true
    const r = await post(`/api/publish/${slug}/manual`, {
      platform: code, path: rel, id: payload?.id || id,
      url: url.trim(), cancel: !publish,
    })
    busy = false
    if (!r || !r.ok) { toast((r && r.error) || t('Failed'), 'err'); return }
    toast(publish ? t('Recorded as published') : t('Pending item discarded'))
    ondone?.()
    onclose?.()
  }
</script>

<div class="modal" role="presentation">
  <div class="box">
    <h4>{payload ? t('Prepared — paste it in and publish') : (id ? t('Fill in the public link') : t('Preparing…'))}</h4>

    {#if err}
      <p class="errline">{err}</p>
    {/if}

    {#if payload}
      <p class="muted sub">
        {payload.name} · {t('This one has no automatic publishing path — the tool prepares it, you publish it.')}
      </p>

      {#if payload.api_status === 'blocked' && payload.api_note}
        <p class="apinote">{t('Native API unavailable:')} {payload.api_note}</p>
      {/if}

      {#each payload.warnings || [] as w}
        <p class="warn">⚠ {w}</p>
      {/each}

      <ol class="steps">
        {#each payload.steps || [] as s}<li>{s}</li>{/each}
      </ol>

      {#if payload.title || payload.title_inline}
        <div class="field">
          <div class="flabel">
            <span>{t('Title')}{#if payload.title_max && payload.title_max !== 'tbd'}
              <span class="muted">（{payload.title.length}/{payload.title_max}）</span>{/if}</span>
            {#if payload.title && !payload.title_inline}
              <button class="btn btn-ghost mini" onclick={() => copyText(payload.title, t('Title copied'))}>{t('Copy title')}</button>
            {/if}
          </div>
          {#if payload.title_inline}
            <div class="muted tiny">{t('This channel has no separate title box — the title is already the first line of the body.')}</div>
          {:else}
            <div class="boxed">{payload.title}</div>
          {/if}
        </div>
      {/if}

      <div class="field">
        <div class="flabel">
          <span>{t('Body')}<span class="muted"> · {payload.body_form}</span></span>
          <button class="btn btn-ghost mini"
                  onclick={() => (payload.copy_as === 'html' ? copyRich() : copyText(payload.body))}>
            {t('Copy body')}
          </button>
        </div>
        {#if payload.copy_as === 'html'}
          <!-- 富文本渠道渲染预览：md2html 有损，粘贴前必须让人看一眼 -->
          <div class="preview" bind:this={previewEl}>{@html payload.body}</div>
        {:else}
          <textarea class="plain" readonly rows="7">{payload.body}</textarea>
        {/if}
      </div>

      {#if payload.tags_text}
        <div class="field">
          <div class="flabel">
            <span>{t('Tags')}</span>
            <button class="btn btn-ghost mini" onclick={() => copyText(payload.tags_text, t('Tags copied'))}>{t('Copy tags')}</button>
          </div>
          <div class="boxed small">{payload.tags_text}</div>
        </div>
      {/if}

      {#if payload.backlink}
        <p class="muted tiny">{t('The body already ends with a link back to your long-form copy:')} {payload.backlink}</p>
      {/if}

      {#if payload.editor_hint}
        <p class="hint">{payload.editor_hint}</p>
      {/if}

      <div class="row actions">
        <button class="btn btn-secondary" onclick={() => copyBodyAndOpen()}>
          {t('Copy body and open the publish page')}
        </button>
        {#if safeUrl(payload.publish_url)}
          <a class="btn btn-ghost" href={safeUrl(payload.publish_url)} target="_blank" rel="noreferrer">
            {t('Open publish page')}
          </a>
        {/if}
      </div>
    {/if}

    {#if id || payload}
      <div class="refill">
        <div class="flabel"><span>{t('Publish done? Put the public link here')}</span></div>
        <input class="urlin" type="url" bind:value={url}
               placeholder="https://…" disabled={busy} />
        {#if payload?.link_hint}<div class="muted tiny">{payload.link_hint}</div>{/if}
      </div>
      <div class="row actions">
        <button class="btn btn-ghost" disabled={busy} onclick={() => mark(false)}>{t('Discard this pending item')}</button>
        <button class="btn btn-secondary" onclick={() => onclose?.()}>{t('Later')}</button>
        <button class="btn btn-primary" disabled={busy} onclick={() => mark(true)}>{t('Recorded as published')}</button>
      </div>
    {:else}
      <div class="row actions">
        <button class="btn btn-secondary" onclick={() => onclose?.()}>{t('Close')}</button>
      </div>
    {/if}
  </div>
</div>

<style>
  .box { max-width: 640px; }
  .sub { font-size: 12px; margin-top: 4px; }
  .errline { color: var(--accent); font-size: 12.5px; }
  .apinote { font-size: 11.5px; color: var(--t500); background: rgba(145, 132, 217, .07);
             padding: 6px 8px; border-radius: 6px; }
  .warn { font-size: 12px; color: var(--accent); margin: 2px 0; }
  .steps { font-size: 12px; color: var(--t500); padding-left: 18px; margin: 6px 0 10px; }
  .field { margin-top: 10px; }
  .flabel { display: flex; justify-content: space-between; align-items: center;
            font-size: 12px; margin-bottom: 4px; }
  .mini { font-size: 11.5px; padding: 2px 8px; }
  .boxed { font-size: 13px; padding: 6px 8px; border-radius: 6px;
           background: rgba(145, 132, 217, .06); word-break: break-word; }
  .boxed.small { font-size: 12px; }
  .preview { max-height: 220px; overflow: auto; font-size: 13px; line-height: 1.55;
             padding: 8px 10px; border-radius: 6px; background: rgba(255, 255, 255, .03);
             box-shadow: inset 0 0 0 1px var(--line); }
  .plain { width: 100%; font-size: 12.5px; line-height: 1.5; font-family: inherit;
           background: rgba(255, 255, 255, .03); color: inherit;
           border: 0; border-radius: 6px; padding: 8px 10px; resize: vertical; }
  .hint { font-size: 12px; color: var(--t500); margin-top: 8px; }
  .tiny { font-size: 11px; }
  .refill { margin-top: 12px; }
  .urlin { width: 100%; font-size: 12.5px; padding: 6px 8px; border-radius: 6px;
           background: rgba(255, 255, 255, .04); color: inherit;
           border: 1px solid var(--line); }
  .actions { justify-content: flex-end; margin-top: 10px; gap: 9px; }
</style>
