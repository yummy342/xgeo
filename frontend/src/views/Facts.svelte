<script>
  // 迁自 ui.html:1797 vFacts。旧版依赖全局 FACT_CARDS 缓存（供 factModal 用），
  // 这里改成局部派生——编辑弹窗仍走 legacy 的 window.factModal(i)，
  // 它读的是旧缓存，所以下面仍然同步一份到 window.FACT_CARDS。
  //
  // 注意：模板里不要再套 esc()。旧代码在字符串拼接时必须手工转义，
  // Svelte 的 {expr} 已经自动转义，再套一层会显示成 &amp;lt; 之类。
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import PageHead from '../components/PageHead.svelte'

  const f = $derived(project.data?.facts_struct || {})
  const fc = $derived(project.data?.analytics?.factcheck || [])
  const slug = $derived(project.data?.slug || '')

  function aiOf(field) {
    const m = fc.find((x) => (x.field || '') && ((x.field || '').indexOf(field) >= 0 || field.indexOf(x.field) >= 0))
    return m
      ? { txt: m.said || t('(missing)'), state: m.state }
      : { txt: t('Not compared — log it under Gap Diagnosis · Fact deviations'), state: null }
  }

  const cards = $derived.by(() => {
    const base = [{ field: t('One-line positioning'), value: f.definition || t('(not filled in)') }]
      .concat((f.numbers || []).map((n) => ({
        field: n.fact,
        value: n.value + (n.source ? ` (${n.source})` : ''),
      })))
    const out = base.map((c) => ({ ...c, ai: aiOf(c.field) }))
    // 旧代码把这份数据挂在全局供 factModal 使用
    window.FACT_CARDS = out
    return out
  })
</script>

<div class="page narrow">
  <PageHead
    kicker={t('DIAGNOSIS · BRAND FACTS')}
    title={t('Write down how you want AI to describe you — once, here')}
    sub={t('The single source of truth for the whole board: workbench drafts pull facts from here, and llms.txt and JSON-LD are generated from it. Change this and everything downstream follows.')}
  />

  <p class="muted hint">
    {@html t('Each card is one official claim. <b>Click a card</b> to log how AI currently phrases it (fact consistency is only measurable once compared, and the health score needs it), or edit the source file to change the claim. Then hit Regenerate below to sync llms.txt and structured data.')}
  </p>

  <div class="grid grid-2 facts-grid">
    {#each cards as c, i (c.field)}
      <div class="card elev fact-card" title={t('Click to log a comparison / edit the claim')} onclick={() => window.factModal(i)}>
        <div class="row fact-top">
          <span class="fact-field">{c.field}</span>
          {#if c.ai.state}
            <span class="tag {c.ai.state === '一致' ? 'pill-good' : 'tag-accent'}">{c.ai.state}</span>
          {:else}
            <span class="tag tag-dim">{t('Not compared')}</span>
          {/if}
        </div>
        <div class="fact-value">{c.value}</div>
        <div class="fact-ai">{t('AI currently says:')} {c.ai.txt}</div>
      </div>
    {:else}
      <div class="muted">{t('No parseable content in the fact cards yet')}</div>
    {/each}
  </div>

  <div class="row" style="margin-top:22px">
    <button class="btn btn-primary" onclick={() => window.runAction('generate', { '--asset': 'llms,jsonld,snippets' })}>
      {t('Regenerate llms.txt and structured data')}
    </button>
    <a class="btn btn-secondary" target="_blank" href="/files/{slug}/assets/llms.txt">{t('View llms.txt')}</a>
    <button class="btn btn-secondary" onclick={() => window.editFactsSrc()}>{t('Edit source file')}</button>
  </div>

  <p class="muted discipline">
    {t('Discipline: the one-line positioning must be identical word-for-word in four places — homepage above the fold, about page, JSON-LD description, and llms.txt. See DEPLOY.md in the assets directory for where the generated files go.')}
  </p>
</div>

<style>
  .hint { font-size: 12.5px; margin-top: 10px; }
  .facts-grid { margin-top: 16px; }
  .fact-card { padding: 16px; gap: 7px; cursor: pointer; }
  .fact-top { justify-content: space-between; align-items: center; flex-wrap: nowrap; }
  .fact-field { font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: var(--t600); }
  .fact-value { font-size: 14px; line-height: 1.55; }
  .fact-ai { font-size: 11.5px; color: var(--t600); line-height: 1.45; }
  .discipline { font-size: 12px; margin-top: 14px; }
</style>
