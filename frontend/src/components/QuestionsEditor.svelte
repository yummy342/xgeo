<script>
  // 取代 ui.html:1401 editQuestions + 1411 saveQuestions。
  // 每行一题的纯文本编辑：`编号|分组|市场|问题`。
  // 旧版保存前重新 GET 一次配置（拿到的可能已经不是刚才编辑时那份），
  // 这里同样以最新配置为基底，只替换 questions 字段。
  import { api, requestPost } from '../lib/api.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'
  import { project, loadProject } from '../lib/stores/project.svelte.js'

  let { onclose } = $props()

  const slug = $derived(project.data?.slug || '')

  let text = $state('')
  let loaded = $state(false)
  let busy = $state(false)

  $effect(() => {
    const s = slug
    if (!s) return
    let cancelled = false
    api('/api/config/' + s).then((cfg) => {
      if (cancelled) return
      text = (cfg?.questions || []).map((q) => `${q.id}|${q.group}|${q.market}|${q.text}`).join('\n')
      loaded = true
    })
    return () => { cancelled = true }
  })

  function parse(line) {
    const m = line.split('|')
    if (m.length < 4 || !m[3].trim()) return null
    const market = m[2].trim()
    return {
      id: m[0].trim(),
      group: m[1].trim() || '推荐',
      market: ['cn', 'global', 'both'].includes(market) ? market : 'cn',
      text: m.slice(3).join('|').trim(),
    }
  }

  async function save() {
    busy = true
    const cfg = await api('/api/config/' + slug)
    const qs = text.split('\n').map(parse).filter(Boolean)
    cfg.questions = qs
    if (cfg.bootstrap) cfg.bootstrap.needs_review = false
    await requestPost('/api/config/' + slug, cfg)
    busy = false
    toast(t('Saved {n} questions').replace('{n}', String(qs.length)))
    await loadProject(slug, true)
    onclose?.()
  }
</script>

<div class="modal" role="presentation">
  <div class="box">
    <h4>{t('Edit question bank')}</h4>
    <p class="muted hint">
      {t('One question per line:')} <code>{t('id|group|market(cn/global/both)|question')}</code>. {t('Re-run sampling for changes to take effect.')}
    </p>
    {#if loaded}
      <textarea class="input" rows="18" bind:value={text}></textarea>
    {:else}
      <p class="soft">{t('Loading…')}</p>
    {/if}
    <div class="row actions">
      <button class="btn btn-secondary" onclick={() => onclose?.()}>{t('Cancel')}</button>
      <button class="btn btn-primary" disabled={busy || !loaded} onclick={save}>{t('Save')}</button>
    </div>
  </div>
</div>

<style>
  .hint { font-size: 12px; }
  .actions { justify-content: flex-end; margin-top: 12px; }
</style>
