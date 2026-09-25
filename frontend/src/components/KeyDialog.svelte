<script>
  import { requestPost } from '../lib/api.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'

  // 取代 ui.html:2556 editKey + saveKey。
  //
  // 旧版从 $('#k-key') 读值，保存失败时只 toast('失败：'+error)；
  // 这里走 requestPost，错误文案由它统一弹出。

  let { entry, onclose, onchanged } = $props()

  let keyVal = $state('')
  let modelVal = $state(entry.model_set ? entry.model : '')
  let busy = $state(false)

  const configured = $derived(entry.ok === true)

  async function save(clear = false) {
    const updates = {}
    if (clear) {
      updates[entry.env] = ''
    } else {
      const v = keyVal.trim()
      if (v) updates[entry.env] = v
    }
    if (entry.model_env && !clear) {
      const m = modelVal.trim()
      if (m !== (entry.model_set ? entry.model : '')) updates[entry.model_env] = m
    }
    if (!Object.keys(updates).length) { onclose?.(); return }

    busy = true
    try {
      await requestPost('/api/keys', { updates })
    } catch (e) {
      busy = false
      return
    }
    busy = false
    toast(t('Written to .env'))
    onchanged?.()
    onclose?.()
  }

  function clearKey() {
    if (!confirm(t('Remove {v} from .env?').replace('{v}', entry.env))) return
    save(true)
  }
</script>

<div class="modal" role="presentation">
  <div class="box">
    <h4>{entry.label}</h4>
    {#if entry.note}<p class="muted note">{entry.note}</p>{/if}

    <div class="field">
      <label>
        {t('API Key')}（{entry.env}{#if configured}，{t('already configured')}{#if entry.key_tail}，{t('ends with')} {entry.key_tail}{/if}{/if}）
      </label>
      <input class="input" type="password" autocomplete="off" bind:value={keyVal}
             placeholder={configured
               ? t('Leave blank to keep the current key')
               : t('Paste the API key')}>
    </div>

    {#if entry.model_env}
      <div class="field">
        <label>{t('Model')}（{entry.model_env}，{t('leave blank for the default')}）</label>
        <input class="input" bind:value={modelVal} placeholder={entry.model}>
      </div>
    {/if}

    <div class="row actions">
      {#if configured}
        <button class="btn btn-ghost clear" disabled={busy} onclick={clearKey}>{t('Clear key')}</button>
      {/if}
      <button class="btn btn-secondary" onclick={() => onclose?.()}>{t('Cancel')}</button>
      <button class="btn btn-primary" disabled={busy} onclick={() => save(false)}>{t('Save')}</button>
    </div>
  </div>
</div>

<style>
  .note { font-size: 12px; margin: 4px 0 0; }
  .actions { justify-content: flex-end; margin-top: 12px; gap: 9px; }
  .clear { margin-right: auto; }
</style>
