<script>
  // 取代 ui.html:2297 editSheet + 2308 importSheet。
  //
  // 无公开 API 的引擎靠人工查：导出采样表 → 逐题把答案原文粘进 ```answer 块
  // → 导入。这个弹窗就是「粘贴 + 导入」那一步。
  import { requestPost } from '../lib/api.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'
  import { project, loadProject } from '../lib/stores/project.svelte.js'

  let { name, onclose } = $props()

  const slug = $derived(project.data?.slug || '')

  let text = $state('')
  let loaded = $state(false)
  let busy = $state(false)

  $effect(() => {
    const s = slug
    const n = name
    if (!s || !n) return
    let cancelled = false
    // 采样表是 work/ 下的静态文件，走 /files/ 而不是 JSON API
    fetch(`/files/${s}/samples/${encodeURIComponent(n)}`)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((txt) => { if (!cancelled) { text = txt; loaded = true } })
      .catch(() => { if (!cancelled) toast(t('The sampling sheet does not exist'), 'err') })
    return () => { cancelled = true }
  })

  async function importIt() {
    busy = true
    await requestPost('/api/sample-import', { slug, file: name, text })
    busy = false
    toast(t('Imported'))
    await loadProject(slug, true)
    onclose?.()
  }
</script>

<div class="modal" role="presentation">
  <div class="box">
    <h4>{name}</h4>
    <p class="muted hint">
      {t('Paste each answer into an ```answer block; a question left blank is skipped, not counted as "not mentioned".')}
    </p>
    {#if loaded}
      <textarea class="input" rows="18" bind:value={text}></textarea>
    {:else}
      <p class="soft">{t('Loading…')}</p>
    {/if}
    <div class="row actions">
      <button class="btn btn-secondary" onclick={() => onclose?.()}>{t('Cancel')}</button>
      <button class="btn btn-primary" disabled={busy || !loaded} onclick={importIt}>{t('Save and import')}</button>
    </div>
  </div>
</div>

<style>
  .hint { font-size: 12px; }
  .actions { justify-content: flex-end; margin-top: 12px; }
</style>
