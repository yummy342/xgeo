<script>
  import { post } from '../lib/api.js'
  import { project, loadProject } from '../lib/stores/project.svelte.js'
import { runAction } from '../lib/jobs.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'

  // 取代 ui.html:1422 expandModal + 1453 expAddIdx + 1457 expAdd。
  //
  // 勾选状态旧版是从 DOM 读的（.expchk 的 checked + dataset），这里用 Set。
  // 「入库」这一动作的语义：把勾选的候选题批量加进问题库（/api/questions-add），
  // 不自动加题 —— 必须人工勾。

  let { onclose } = $props()

  const slug = $derived(project.data?.slug || '')
  const data = $derived(project.data?.expand || null)
  const cand = $derived((data?.terms || []).filter((x) => !x.in_bank))

  const GROUPS = ['推荐', '比较', '替代', '价格', '风险', '品牌验证', '场景']

  let picked = $state(new Set())
  let busy = $state(false)

  const grouped = $derived(
    GROUPS.map((g) => ({ g, items: cand.map((x, i) => ({ x, i })).filter(({ x }) => x.group === g) }))
      .filter((o) => o.items.length),
  )

  function toggle(i) {
    const next = new Set(picked)
    if (next.has(i)) next.delete(i)
    else next.add(i)
    picked = next
  }

  function mktName(m) {
    return m === 'cn' ? t('CN market') : m === 'global' ? t('Global market') : t('Both markets')
  }

  async function addAll(items) {
    if (!items.length) { toast(t('Tick the questions to add first'), 'err'); return }
    busy = true
    const r = await post('/api/questions-add', { slug, items })
    busy = false
    if (!r.ok) { toast(r.error || t('Save failed'), 'err'); return }
    toast(t('Added {n} questions').replace('{n}', String(r.added)))
    await loadProject(slug, true)
    onclose?.()
  }

  const pickedItems = $derived([...picked].map((i) => {
    const x = cand[i]
    return { text: x.question, group: x.group, market: x.market }
  }).filter((x) => x.text))
</script>

<div class="modal" role="presentation">
  <div class="box wide">
    <h4>{t('Mine topics · from real search demand')}</h4>
    <p class="muted intro">
      {t('Roots: brand + competitors + category. Sources: Baidu autocomplete (CN) + Google Suggest (global). Tick to add; nothing is added automatically.')}
      {#if data?.generated_at}
        <span class="stamp">{data.generated_at}</span>
      {/if}
      {#if data}<span class="stamp">{data.llm ? t('LLM rephrased') : t('Template rephrased')}</span>{/if}
    </p>

    {#if !data}
      <p class="muted">{t('No keyword mining data yet')}</p>
    {:else if !cand.length}
      <p class="muted">{t('All candidates are already in the bank — mine again to look for new terms.')}</p>
    {:else}
      <div class="list">
        {#each grouped as { g, items } (g)}
          <div class="grp">{g} · {items.length}</div>
          {#each items as { x, i } (x.question + i)}
            <label class="row item">
              <input type="checkbox" checked={picked.has(i)} onchange={() => toggle(i)}>
              <span class="body">
                <span class="q">{x.question}</span>
                <span class="meta">
                  {x.term} · {x.root} · {mktName(x.market)}{#if x.new} · <span class="hl">{t('new term')}</span>{/if}
                </span>
              </span>
            </label>
          {/each}
        {/each}
      </div>
    {/if}

    <div class="row actions">
      <button class="btn btn-ghost" onclick={() => { onclose?.(); runAction('expand') }}>{t('Mine again')}</button>
      <button class="btn btn-secondary" onclick={() => onclose?.()}>{t('Cancel')}</button>
      <button class="btn btn-primary" disabled={busy || !pickedItems.length} onclick={() => addAll(pickedItems)}>
        {t('Add to question bank')}{#if pickedItems.length} ({pickedItems.length}){/if}
      </button>
    </div>
  </div>
</div>

<style>
  .box.wide { max-width: 720px; }
  .intro { font-size: 12px; margin-top: 4px; }
  .stamp { margin-left: 6px; }
  .list { max-height: 440px; overflow: auto; margin-top: 6px; }
  .grp { font-size: 12px; color: var(--a300); margin: 12px 0 4px; }
  .item { gap: 8px; padding: 6px 8px; border-radius: 6px; cursor: pointer; box-shadow: inset 0 -1px 0 var(--line); align-items: flex-start; }
  .body { flex: 1; }
  .q { font-size: 13px; display: block; }
  .meta { display: block; font-size: 11px; color: var(--t600); margin-top: 2px; }
  .hl { color: var(--a300); }
  .actions { justify-content: flex-end; margin-top: 12px; gap: 9px; }
</style>
