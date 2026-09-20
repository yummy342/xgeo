<script>
  // 取代 ui.html:1665 的 addFact + saveFact。
  // 旧版从三个 input 里读值再 push 进现有 factcheck 数组整体覆盖；
  // 这里保留同样的语义（读现有数组 → 追加 → 整体写回），只是改用 bind:value。
  import { requestPost } from '../lib/api.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'
  import { project, loadProject } from '../lib/stores/project.svelte.js'

  let { prefill = '', onclose } = $props()

  const slug = $derived(project.data?.slug || '')

  let field = $state(prefill)
  let said = $state('')
  let truth = $state('')
  let state_ = $state('被说错')
  let busy = $state(false)

  const STATES = [
    ['被说错', 'Said it wrong'],
    ['缺失', 'Missing'],
    ['一致', 'Matches'],
  ]

  async function save() {
    busy = true
    const items = (project.data?.analytics?.factcheck || []).slice()
    items.push({
      field: field.trim(), said: said.trim(), truth: truth.trim(), state: state_,
    })
    await requestPost('/api/factcheck/' + slug, { items })
    busy = false
    toast(t('Recorded — the health score will update'))
    await loadProject(slug, true)
    onclose?.()
  }
</script>

<div class="modal" role="presentation">
  <div class="box">
    <h4>{t('Record a fact comparison')}</h4>

    <div class="field">
      <label>{t('Field (e.g. supported scale / founding date / price)')}</label>
      <input class="input" bind:value={field}>
    </div>
    <div class="field">
      <label>{t('What AI said (verbatim from a sample)')}</label>
      <input class="input" bind:value={said}>
    </div>
    <div class="field">
      <label>{t('Official claim')}</label>
      <input class="input" bind:value={truth}>
    </div>
    <div class="field">
      <label>{t('Status')}</label>
      <div class="seg">
        {#each STATES as [v, label] (v)}
          <label class="seg-opt"><input type="radio" bind:group={state_} value={v}>{t(label)}</label>
        {/each}
      </div>
    </div>

    <div class="row actions">
      <button class="btn btn-secondary" onclick={() => onclose?.()}>{t('Cancel')}</button>
      <button class="btn btn-primary" disabled={busy} onclick={save}>{t('Save')}</button>
    </div>
  </div>
</div>

<style>
  .actions { justify-content: flex-end; margin-top: 12px; }
</style>
