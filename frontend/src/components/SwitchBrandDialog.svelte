<script>
  import { api } from '../lib/api.js'
  import { go } from '../lib/router.svelte.js'
  import { loadProject } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { ui } from '../lib/stores/ui.svelte.js'

  // 取代 ui.html:2512 的 switchModal。
  // 切换项目的实际动作收在这里：旧 switchProject 要手工清六个全局缓存，
  // 现在组件各自持有状态，只需要清跨视图的 engSel 再加载新项目。

  let { currentSlug, onclose } = $props()

  let list = $state([])
  let busy = $state(false)

  $effect(() => {
    api('/api/projects').then((r) => { list = Array.isArray(r) ? r : [] })
  })

  async function pick(slug) {
    if (slug === currentSlug || busy) return
    busy = true
    ui.engSel = null
    await loadProject(slug)
    busy = false
    onclose?.()
    go('overview')
  }

  function addBrand() {
    onclose?.()
    go('onboard', { obStep: 1 })
  }
</script>

<div class="modal" role="presentation">
  <div class="box">
    <h4>{t('Switch brand')}</h4>
    <div class="list">
      {#each list as p (p.slug)}
        <div class="row brand-row" class:current={p.slug === currentSlug}
             onclick={() => pick(p.slug)}>
          <span class="name">
            {p.name}
            {#if p.slug === currentSlug}<span class="tag tag-accent cur">{t('current')}</span>{/if}
          </span>
          <span class="muted site">{(p.site || '').replace(/^https?:\/\//, '')}</span>
          <span class="muted score">{t('Audit')} {p.avg_score == null ? '—' : p.avg_score}</span>
        </div>
      {:else}
        <p class="soft">{t('No projects yet')}</p>
      {/each}
    </div>
    <div class="row actions">
      <button class="btn btn-secondary" onclick={addBrand}>{t('+ Add a brand')}</button>
      <button class="btn btn-primary" onclick={() => onclose?.()}>{t('Close')}</button>
    </div>
  </div>
</div>

<style>
  .list { margin-top: 8px; }
  .brand-row { gap: 10px; padding: 10px 8px; cursor: pointer; border-radius: var(--r-md); box-shadow: inset 0 -1px 0 var(--line); }
  .brand-row:hover { background: var(--deep); }
  .brand-row.current { cursor: default; }
  .name { flex: 1; font-size: 13.5px; }
  .cur { font-size: 10px; }
  .site { font-size: 11.5px; }
  .score { font-size: 11.5px; width: 70px; text-align: right; }
  .actions { justify-content: flex-end; margin-top: 12px; }
</style>
