<script>
  // 取代 ui.html:1922 的 taskModal。
  //
  // 「去内容工作台」那步仍是 legacy 的 wbFromTask —— 它是领域逻辑
  // （从任务标题/资产推断该写哪道题，见 taskWbTarget），不属于渲染层。
  import { t } from '../lib/i18n/index.svelte.js'
  import { go } from '../lib/router.svelte.js'

  let { task, onclose } = $props()

  const acc = $derived(task.acceptance || {})
  const ev = $derived((task.evidence || []).slice(-3).reverse())
  const affected = $derived(task.affected || [])

  const RISK = { low: 'low risk', watch: 'needs watching', high: 'high risk' }
  const RESULT = { pass: '✓ passed', fail: '✗ not met', manual: 'needs a human' }

  function mktName(m) {
    return m === 'cn' ? t('CN market') : m === 'global' ? t('Global market') : t('Both markets')
  }

  function toWorkbench() {
    onclose?.()
    window.wbFromTask?.(task.id)
  }
</script>

<div class="modal" role="presentation">
  <div class="box">
    <h4>{task.id} · {task.title}</h4>

    <div class="row meta">
      <span class="tag {task.priority === 'P0' ? 'tag-accent' : 'tag-neutral'} pri">{task.priority}</span>
      <span class="tag tag-outline">{task.package}</span>
      {#if task.risk}
        <span class="tag {task.risk === 'high' ? 'tag-accent' : 'tag-dim'} pri">{t(RISK[task.risk])}</span>
      {/if}
      <span class="who">
        {t('Owner')}: {task.owner} · {t('Effort')} {task.effort} · {t('Window')} {task.window || '—'} · {mktName(task.market)}
      </span>
    </div>

    <div class="lbl">{t('Why this is here')}</div>
    <div class="body soft">{task.why || '—'}</div>

    <div class="lbl">{t('What to do, concretely')}</div>
    <div class="body">{task.action || '—'}</div>

    <div class="lbl">
      {t('What counts as done')}（{acc.type === 'auto'
        ? t('automatic — re-crawl / re-sample decides, not a person saying so')
        : t('manual acceptance')}）
    </div>
    <div class="body">
      {acc.desc || '—'}
      {#if acc.check}
        <div class="muted checker">{t('Checker')}: <code>{acc.check}</code></div>
      {/if}
    </div>

    {@html window.progBar(task.progress, task.progress_first)}

    {#if affected.length}
      <div class="lbl">{t('Affected pages ({n})').replace('{n}', String(affected.length))}</div>
      <div class="affected">
        {#each affected.slice(0, 20) as u (u)}
          <div class="ellipsis">{u}</div>
        {/each}
        {#if affected.length > 20}
          <div class="muted">{t('…{n} total').replace('{n}', String(affected.length))}</div>
        {/if}
      </div>
    {/if}

    {#if ev.length}
      <div class="lbl">{t('Recent verification records')}</div>
      {#each ev as e (e.at)}
        <div class="ev">
          {(e.at || '').slice(0, 16).replace('T', ' ')} · {t(RESULT[e.result] || e.result || '')} · {e.note || ''}
        </div>
      {/each}
    {/if}

    <div class="row actions">
      {#if task.package === '内容矩阵'}
        <button class="btn btn-secondary wb" onclick={toWorkbench}>{t('Go to Workbench')}</button>
      {/if}
      <button class="btn btn-primary" onclick={() => onclose?.()}>{t('Close')}</button>
    </div>
  </div>
</div>

<style>
  .meta { gap: 6px; margin-top: 6px; }
  .pri { font-size: 11px; }
  .who { font-size: 11.5px; color: var(--t600); }
  .lbl { font-size: 12px; color: var(--t600); margin: 12px 0 3px; }
  .body { font-size: 13px; line-height: 1.6; }
  .body.soft { color: var(--t400); }
  .checker { font-size: 11.5px; margin-top: 2px; }
  .affected { max-height: 120px; overflow: auto; font-size: 11.5px; line-height: 1.7; color: var(--t500); }
  .ellipsis { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ev { font-size: 11.5px; color: var(--t500); padding: 2px 0; }
  .actions { justify-content: flex-end; margin-top: 14px; }
  .wb { margin-right: auto; }
</style>
