<script>
  import { api, requestPost } from '../lib/api.js'
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'

  // 取代 ui.html:2532 editConfig + saveCfg。
  //
  // 旧 saveCfg 有两个毛病：保存失败时 toast 的是硬编码的 '失败'，把服务端的
  // r.error 丢掉了；以及它重新 GET 一次配置再改。这里直接拿调用方已有的配置
  // 做副本，保存走 requestPost（错误文案由它统一弹）。

  let { onclose, onchanged } = $props()

  const slug = $derived(project.data?.slug || '')

  let loaded = $state(false)
  let busy = $state(false)
  let name = $state('')
  let aliases = $state('')
  let comps = $state('')
  let market = $state('cn')

  // 保留原始配置的其余字段（competitors 的 aliases、bootstrap 等），只改编辑的几项
  let cfg = $state(null)

  $effect(() => {
    const s = slug
    if (!s) return
    let cancelled = false
    api('/api/config/' + s).then((r) => {
      if (cancelled) return
      cfg = r || {}
      const b = cfg.brand || {}
      name = b.name || ''
      aliases = (b.aliases || []).join('、')
      comps = (cfg.competitors || []).map((c) => c.name).join('、')
      market = cfg.market || 'cn'
      loaded = true
    })
    return () => { cancelled = true }
  })

  const MARKETS = [['cn', 'CN engines'], ['global', 'Global engines'], ['both', 'Both']]

  function split(v) {
    return v.split(/[、,，]/).map((s) => s.trim()).filter(Boolean)
  }

  async function save() {
    busy = true
    const next = { ...cfg }
    next.brand = { ...(cfg.brand || {}) }
    next.brand.name = name.trim()
    next.brand.aliases = split(aliases)

    // 竞品：同名保留原对象（别名等字段不丢），新名字补一个默认结构
    const old = {}
    for (const c of (cfg.competitors || [])) old[c.name] = c
    next.competitors = split(comps).map((n) => old[n] || {
      name: n, aliases: [], market: next.market === 'global' ? 'global' : 'cn',
    })

    next.market = market
    if (next.bootstrap) next.bootstrap.needs_review = false

    await requestPost('/api/config/' + slug, next)
    busy = false
    toast(t('Saved'))
    onchanged?.()
    onclose?.()
  }
</script>

<div class="modal" role="presentation">
  <div class="box">
    <h4>{t('Brand configuration')}</h4>

    {#if !loaded}
      <p class="soft">{t('Loading…')}</p>
    {:else}
      <div class="field">
        <label>{t('Brand name')}</label>
        <input class="input" bind:value={name}>
      </div>
      <div class="field">
        <label>{t('Aliases (comma separated — missing one undercounts mentions)')}</label>
        <input class="input" bind:value={aliases}>
      </div>
      <div class="field">
        <label>{t('Competitors (comma separated — they are the denominator of the ranking metric)')}</label>
        <input class="input" bind:value={comps}>
      </div>
      <div class="field">
        <label>{t('Market')}</label>
        <div class="seg">
          {#each MARKETS as [m, label] (m)}
            <label class="seg-opt"><input type="radio" bind:group={market} value={m}>{t(label)}</label>
          {/each}
        </div>
      </div>

      <div class="row actions">
        <button class="btn btn-secondary" onclick={() => onclose?.()}>{t('Cancel')}</button>
        <button class="btn btn-primary" disabled={busy} onclick={save}>{t('Save')}</button>
      </div>
    {/if}
  </div>
</div>

<style>
  .actions { justify-content: flex-end; margin-top: 12px; }
</style>
