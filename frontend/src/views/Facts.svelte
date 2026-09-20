<script>
  // 迁自 ui.html:1797 vFacts。弹窗全部改成了组件
  // （FactCardDialog / FactsSourceDialog / AddFactDialog），
  // 所以不再需要往 window.FACT_CARDS 同步缓存。
  //
  // 注意：模板里不要再套 esc()。旧代码在字符串拼接时必须手工转义，
  // Svelte 的 {expr} 已经自动转义，再套一层会显示成 &amp;lt; 之类。
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import PageHead from '../components/PageHead.svelte'
  import FactCardDialog from '../components/FactCardDialog.svelte'
  import FactsSourceDialog from '../components/FactsSourceDialog.svelte'
  import AddFactDialog from '../components/AddFactDialog.svelte'

  const f = $derived(project.data?.facts_struct || {})
  const fc = $derived(project.data?.analytics?.factcheck || [])
  const slug = $derived(project.data?.slug || '')

  // 三个弹窗都归本组件管，不再走 legacy 的 factModal / editFactsSrc / addFact
  let cardIdx = $state(null)
  let showSource = $state(false)
  let addPrefill = $state(null)

  function aiOf(field) {
    const m = fc.find((x) => (x.field || '') && ((x.field || '').indexOf(field) >= 0 || field.indexOf(x.field) >= 0))
    return m
      ? { txt: m.said || t('(missing)'), state: m.state }
      : { txt: t('Not compared — log it under Gap Diagnosis · Fact deviations'), state: null }
  }

  // 一句话定位这条卡的「字段名」是数据标识，不是显示文案。
  // 它要和 factcheck 记录里的 field 逐字匹配（历史数据存的是中文），
  // 也要原样写回（AddFactDialog 的 prefill 用它）。翻译它会让同一份数据
  // 被语言切成两半：英文 locale 下匹配不上、显示「未比对」，新记录又写成
  // 另一个 key。所以这里固定用中文标识，只在渲染时翻译。
  const POSITIONING = '一句话定位'

  const cards = $derived.by(() => {
    const base = [{
      field: POSITIONING,
      label: t('One-line positioning'),
      value: f.definition || t('(not filled in)'),
    }].concat((f.numbers || []).map((n) => ({
      field: n.fact,
      label: n.fact,          // 数字事实的字段名本身就是数据，照原样显示
      value: n.value + (n.source ? ` (${n.source})` : ''),
    })))
    return base.map((c) => ({ ...c, ai: aiOf(c.field) }))
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
      <div class="card elev fact-card" title={t('Click to log a comparison / edit the claim')} onclick={() => (cardIdx = i)}>
        <div class="row fact-top">
          <span class="fact-field">{c.label}</span>
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
    <button class="btn btn-secondary" onclick={() => (showSource = true)}>{t('Edit source file')}</button>
  </div>

  <p class="muted discipline">
    {t('Discipline: the one-line positioning must be identical word-for-word in four places — homepage above the fold, about page, JSON-LD description, and llms.txt. See DEPLOY.md in the assets directory for where the generated files go.')}
  </p>
</div>

{#if cardIdx != null && cards[cardIdx]}
  <FactCardDialog
    card={cards[cardIdx]}
    onclose={() => (cardIdx = null)}
    oneditSource={() => (showSource = true)}
    onaddFact={(field) => (addPrefill = field)}
  />
{/if}

{#if showSource}
  <FactsSourceDialog
    onclose={() => (showSource = false)}
    onchanged={() => window.load(slug, true)}
  />
{/if}

{#if addPrefill != null}
  <AddFactDialog prefill={addPrefill} onclose={() => (addPrefill = null)} />
{/if}

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
