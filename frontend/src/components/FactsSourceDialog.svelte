<script>
  import { api, requestPost } from '../lib/api.js'
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'

  // 取代 ui.html:1838 的 editFactsSrc + saveFactsSrc。
  // 旧版把 textarea 的值在保存时用 $('#factsrc').value 读回来，这里 bind:value。

  let { onclose, onchanged } = $props()

  const slug = $derived(project.data?.slug || '')
  let text = $state('')
  let loaded = $state(false)
  let busy = $state(false)
  // 读失败时不能给出空编辑器：用户一点保存就把 facts.md 覆盖成空文件
  let err = $state(null)

  $effect(() => {
    const s = slug
    if (!s) return
    let cancelled = false
    api('/api/facts/' + s).then((r) => {
      if (cancelled) return
      if (r?.error) { err = r.error; return }
      text = r.text || ''
      loaded = true
    })
    return () => { cancelled = true }
  })

  async function save() {
    busy = true
    await requestPost('/api/facts/' + slug, { text })
    busy = false
    toast(t('Saved'))
    onchanged?.()
    onclose?.()
  }
</script>

<div class="modal" role="presentation">
  <div class="box">
    <h4>{t('Brand facts · source file')}</h4>
    <p class="muted hint">
      {t('Markdown. Tag each fact with an evidence grade A–E; anything without a source is marked "to confirm" — do not invent one. After saving, hit Regenerate to sync it into the assets.')}
    </p>
    {#if err}
      <p class="err">{err}</p>
    {:else if loaded}
      <textarea class="input" rows="20" bind:value={text}></textarea>
    {:else}
      <p class="soft">{t('Loading…')}</p>
    {/if}
    <div class="row actions">
      <button class="btn btn-secondary" onclick={() => onclose?.()}>{t('Cancel')}</button>
      <button class="btn btn-primary" disabled={busy || !loaded || !!err} onclick={save}>{t('Save')}</button>
    </div>
  </div>
</div>

<style>
  .hint { font-size: 12px; }
  .err { font-size: 13px; color: #d55; }
  .actions { justify-content: flex-end; margin-top: 12px; }
</style>
