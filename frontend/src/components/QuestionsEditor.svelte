<script>
  import { api, requestPost } from '../lib/api.js'
  import { project, loadProject } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'

  // 取代 ui.html:1401 editQuestions + 1411 saveQuestions。
  // 每行一题的纯文本编辑：`编号|分组|市场|问题`。
  // 旧版保存前重新 GET 一次配置（拿到的可能已经不是刚才编辑时那份），
  // 这里同样以最新配置为基底，只替换 questions 字段。

  let { onclose } = $props()

  const slug = $derived(project.data?.slug || '')

  let text = $state('')
  let loaded = $state(false)
  let busy = $state(false)
  // 读失败时不能给出空编辑器：用户一点保存就把整个题库覆盖成空
  let err = $state(null)

  $effect(() => {
    const s = slug
    if (!s) return
    let cancelled = false
    api('/api/config/' + s).then((cfg) => {
      if (cancelled) return
      if (cfg?.error) { err = cfg.error; return }
      text = (cfg.questions || []).map((q) => `${q.id}|${q.group}|${q.market}|${q.text}`).join('\n')
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
    // 以最新配置为基底是必要的，但读失败时拿到的是 {error}——拿它当基底会把
    // 残缺对象写进 geo.json，等于抹掉别人的字段。
    if (cfg?.error) {
      busy = false
      toast(cfg.error, 'err')
      return
    }
    // 逐行解析，**畸形行必须拦下来**：原来 filter(Boolean) 把少一个 `|`、或正文为空
    // 的行直接丢掉，然后整段覆盖写回 —— 一道题就这么永久消失，而 toast 只说
    // 「已保存 N 题」。空行不算畸形（粘贴常带尾随空行）。
    const rows = text.split('\n').map((l, i) => [i + 1, l]).filter(([, l]) => l.trim())
    const bad = rows.filter(([, l]) => !parse(l)).map(([n]) => n)
    if (bad.length) {
      busy = false
      toast(t('Line {n} is not a valid question (needs 4 fields) — nothing was saved')
        .replace('{n}', String(bad[0])), 'err')
      return
    }
    const qs = rows.map(([, l]) => parse(l))
    cfg.questions = qs
    if (cfg.bootstrap) cfg.bootstrap.needs_review = false
    try {
      await requestPost('/api/config/' + slug, cfg)
    } catch (e) {
      busy = false          // 失败别把按钮永久禁掉：整份题库的编辑会取不回来
      return
    }
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
    {#if err}
      <p class="err">{err}</p>
    {:else if loaded}
      <textarea class="input" rows="18" bind:value={text}></textarea>
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
