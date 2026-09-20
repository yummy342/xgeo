<script>
  // 取代 ui.html:1755 的 chanOpen。
  // chanFitQs / distOf 是领域函数（哪道题适配哪个阵地、是否已铺），仍在 legacy 里。
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { esc } from '../lib/format.js'
  import { go } from '../lib/router.svelte.js'

  let { channel, onclose } = $props()

  const channels = $derived((project.data?.blueprint || {}).channels || [])
  const tasks = $derived(project.data?.tasks || [])

  // 该阵地名称出现在哪些任务标题里
  const related = $derived.by(() => {
    const stem = channel.name.split('（')[0].split(' / ')[0]
    return tasks.filter((x) => (x.title || '').indexOf(stem) >= 0)
  })

  const fits = $derived(channel.fits || [])

  const fitQuestions = $derived.by(() => {
    if (!fits.length) return { list: [], done: 0, total: 0 }
    const qs = window.chanFitQs ? window.chanFitQs(channel) : []
    const done = qs.filter((q) => window.distOf(q.id, channel.id)).length
    // 排序：已铺的排最后，缺口排前面
    const weight = (q) => window.distOf(q.id, channel.id) ? 3 : q.content === '已成稿' ? 0 : q.content === '缺口' ? 2 : 1
    const list = qs.slice().sort((a, b) => weight(a) - weight(b))
    return { list, done, total: qs.length }
  })

  function openQuestion(qid) {
    onclose?.()
    go('workbench', { wq: qid })
  }
</script>

<div class="modal" role="presentation">
  <div class="box">
    <h4>{channel.name}</h4>

    <div class="row meta">
      <span class="tag {channel.priority === 'P0' ? 'tag-accent' : channel.priority === 'P1' ? 'tag-neutral' : 'tag-dim'} pri">{channel.priority}</span>
      <span class="tag tag-outline">{channel.kind || ''}</span>
      <span class="tag {channel.covered ? 'pill-good' : 'tag-accent'} pri">{channel.covered ? t('✓ cited this round') : t('Not built')}</span>
      <span class="stat">
        {channel.national ? t('{n} citations site-wide').replace('{n}', channel.national.toLocaleString()) : ''}{channel.position ? ` · ${t('avg. citation position')} ${channel.position}` : ''}{channel.platforms ? ` · ${channel.platforms} ${t('surfaces')}` : ''}
      </span>
    </div>

    {#if channel.why}
      <p class="why">{@html esc(channel.why).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')}</p>
    {/if}

    <div class="lbl">{t('What to build (do every item)')}</div>
    <ul class="forms">
      {#each (channel.forms || []) as f (f)}
        <li>{f}</li>
      {:else}
        <li class="muted">{t('The blueprint gives no specific form')}</li>
      {/each}
    </ul>

    <div class="spec spec-row">
      <div><div class="k">{t('How much')}</div><div class="v">{channel.volume || '—'}</div></div>
      <div><div class="k">{t('Cadence')}</div><div class="v">{channel.cadence || '—'}</div></div>
      <div><div class="k">{t('Who')}</div><div class="v">{channel.owner || '—'}</div></div>
      <div><div class="k">{t('Related tasks')}</div><div class="v">{related.length ? related.map((x) => x.id).join('、') : '—'}</div></div>
    </div>

    {#if fits.length}
      <div class="lbl">
        {t('Content that fits here')}
        <span class="muted">（{t('serves')} {fits.join('/')} · {fitQuestions.total} {t('questions')} · {fitQuestions.done} {t('planted')}）</span>
      </div>
      {#each fitQuestions.list.slice(0, 6) as q (q.id)}
        {@const planted = window.distOf(q.id, channel.id)}
        <div class="row q-row" title={t('Open in the Workbench to write or edit this one')} onclick={() => openQuestion(q.id)}>
          <span class="q-text" class:planted>{q.text}</span>
          <span class="tag {q.content === '已成稿' ? 'pill-good' : 'tag-dim'} q-state">{q.content}</span>
          {#if planted}<span class="tag tag-outline q-state">{t('planted ✓')}</span>{/if}
        </div>
      {/each}
      {#if fitQuestions.total > 6}
        <div class="muted more">{t('…{n} total; the rest are filterable by group in the question bank').replace('{n}', String(fitQuestions.total))}</div>
      {/if}
    {:else}
      <p class="muted none">{t('This is an indexing or infrastructure channel — it does not host specific articles.')}</p>
    {/if}

    <p class="muted foot">
      {t('Content comes out of the Workbench per target question; deployment snippets for site-type channels live in Assets (with DEPLOY.md steps and acceptance criteria).')}
    </p>

    <div class="row actions">
      {#if related.length}
        <button class="btn btn-ghost tasks" onclick={() => { onclose?.(); go('plan') }}>{t('See related tasks →')}</button>
      {/if}
      <button class="btn btn-secondary" onclick={() => { onclose?.(); go('workbench') }}>{t('Go to Workbench')}</button>
      <button class="btn btn-primary" onclick={() => onclose?.()}>{t('Close')}</button>
    </div>
  </div>
</div>

<style>
  .meta { gap: 6px; margin-top: 6px; }
  .pri { font-size: 11px; }
  .stat { font-size: 11.5px; color: var(--t600); }
  .why { font-size: 13px; color: var(--t400); line-height: 1.6; margin: 10px 0 4px; }
  .lbl { font-size: 12px; color: var(--t600); margin: 10px 0 4px; }
  .forms { margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.8; }
  .spec-row { margin-top: 12px; }
  .q-row { gap: 8px; padding: 4px 0; font-size: 12.5px; cursor: pointer; box-shadow: inset 0 -1px 0 var(--line); }
  .q-text { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .q-text.planted { color: var(--t600); }
  .q-state { font-size: 10px; flex: none; }
  .more { font-size: 11px; padding-top: 4px; }
  .none { font-size: 11.5px; margin-top: 10px; }
  .foot { font-size: 11.5px; margin-top: 10px; }
  .actions { justify-content: flex-end; margin-top: 12px; gap: 9px; }
  .tasks { margin-right: auto; }
</style>
