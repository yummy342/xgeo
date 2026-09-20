<script>
  import { project } from '../lib/stores/project.svelte.js'
  import { requestPost } from '../lib/api.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'

  // 取代 ui.html:2466 editPub + 2486 savePub。
  //
  // 保存分两段：先写凭据（/api/keys → .env），再写渠道配置
  // （/api/publishcfg → geo.json.publishing）。旧版从 DOM 读值
  // （.pub-env / .pub-cfg 的 dataset），这里都是响应式状态。
  // 凭据留空即保持不变——这一点在 label 里写明。

  let { publisher, onclose, onchanged } = $props()

  const slug = $derived(project.data?.slug || '')

  const guide = $derived(publisher.guide || {})
  const missing = $derived(publisher.missing || [])

  // env 变量名 → 输入值；cfg key → 输入值
  let envVals = $state({})
  let cfgVals = $state({})
  let busy = $state(false)

  $effect(() => {
    const init = {}
    for (const c of (publisher.cfg || [])) init[c.key] = c.value || ''
    cfgVals = init
    envVals = {}
  })

  async function save() {
    busy = true

    const updates = {}
    for (const [k, v] of Object.entries(envVals)) {
      const trimmed = (v || '').trim()
      if (trimmed) updates[k] = trimmed
    }
    if (Object.keys(updates).length) {
      try {
        await requestPost('/api/keys', { updates })
      } catch {
        busy = false
        return
      }
    }

    if ((publisher.cfg || []).length) {
      const cfg = {}
      for (const c of publisher.cfg) cfg[c.key] = (cfgVals[c.key] || '').trim()
      try {
        await requestPost('/api/publishcfg/' + slug, { platform: publisher.code, cfg })
      } catch {
        busy = false
        return
      }
    }

    busy = false
    toast(t('Saved'))
    onchanged?.()
    onclose?.()
  }
</script>

<div class="modal" role="presentation">
  <div class="box">
    <h4>{publisher.name}</h4>
    <p class="muted note">{publisher.note}</p>

    {#if (guide.steps || []).length}
      <div class="guide">
        <div class="row guide-head">
          <span class="guide-t">{t('How to get these credentials')}</span>
          {#if guide.url}
            <a href={guide.url} target="_blank" class="guide-link">{t('Open the signup page ↗')}</a>
          {/if}
        </div>
        {#each guide.steps as step, n (step)}
          <div class="guide-step">
            <span class="guide-n">{n + 1}.</span><span>{step}</span>
          </div>
        {/each}
      </div>
    {/if}

    {#each (publisher.env || []) as e (e)}
      <div class="field">
        <label>{e}{missing.includes(e) ? '' : t(' (configured — leave blank to keep)')}</label>
        <input class="input" type="password" autocomplete="off"
               value={envVals[e] || ''}
               oninput={(ev) => { envVals = { ...envVals, [e]: ev.currentTarget.value } }}
               placeholder={missing.includes(e) ? t('Required') : t('Leave blank to keep')}>
      </div>
    {/each}

    {#each (publisher.cfg || []) as c (c.key)}
      <div class="field">
        <label>{c.key}</label>
        <input class="input" value={cfgVals[c.key] || ''}
               oninput={(ev) => { cfgVals = { ...cfgVals, [c.key]: ev.currentTarget.value } }}
               placeholder={c.hint}>
      </div>
    {/each}

    <div class="row actions">
      <button class="btn btn-secondary" onclick={() => onclose?.()}>{t('Cancel')}</button>
      <button class="btn btn-primary" disabled={busy} onclick={save}>{t('Save')}</button>
    </div>
  </div>
</div>

<style>
  .note { font-size: 12px; margin-top: 4px; }
  .guide { background: var(--deep); border-radius: var(--r-md); padding: 11px 14px; margin-top: 10px; }
  .guide-head { margin-bottom: 5px; }
  .guide-t { font-size: 11px; letter-spacing: .08em; color: var(--t600); flex: 1; }
  .guide-link { font-size: 11.5px; color: var(--a300); }
  .guide-step { display: flex; gap: 8px; padding: 3px 0; font-size: 12px; line-height: 1.55; color: var(--t400); }
  .guide-n { color: var(--a300); flex: none; }
  .actions { justify-content: flex-end; margin-top: 12px; }
</style>
