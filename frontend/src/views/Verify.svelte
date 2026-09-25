<script>
  import PageHead from '../components/PageHead.svelte'
  import { pct } from '../lib/format.js'
  import { progBar } from '../lib/domain.js'
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'

  // 迁自 ui.html:2158 vVerify。
  // 市场筛选原本是全局 ST.vfMkt（配合 onclick="ST.vfMkt='x';render()"），
  // 这里下沉成组件内的 $state——它是这一页自己的筛选态，不该放全局。
  // progBar 仍在 legacy 里，返回 HTML 字符串，所以走 {@html}。

  const a = $derived(project.data?.analytics || {})
  const vh = $derived(project.data?.verify_history || [])
  const tasks = $derived(project.data?.tasks || [])

  let market = $state('all')
  const MARKETS = [['all', 'All'], ['cn', 'CN market'], ['global', 'Global market']]

  const qd = $derived((a.q_delta || []).filter(
    (x) => market === 'all' || x.market === market || x.market === 'both',
  ))
  const meas = $derived(qd.filter((x) => x.after != null))
  const up = $derived(meas.filter((x) => (x.after || 0) > (x.before || 0)))
  const down = $derived(meas.filter((x) => (x.after || 0) < (x.before || 0)))
  const last = $derived(vh.length ? vh[vh.length - 1] : null)
  const progTasks = $derived(
    tasks.filter((x) => x.progress).sort((x, y) => (x.priority || '').localeCompare(y.priority || '')),
  )

  function mktName(m) {
    return m === 'cn' ? t('CN market') : m === 'global' ? t('Global market') : t('Both markets')
  }
</script>

<div class="page narrow">
  <PageHead
    kicker={t('RESULTS · VERIFICATION')}
    title={t('Of what you did, what actually changed how AI talks')}
    sub={t('Two chains of evidence: automatic acceptance of tasks (re-crawl decides), and per-question before/after sampling. Attribution discipline: a single round of movement counts as an observation, not a cause.')}
  />

  <div class="verify-kpis">
    <div class="card elev vk">
      <div class="vk-l">{t('Questions that went up')}</div>
      <div class="vk-v up">{up.length}</div>
      <div class="vk-s">{qd.length ? t('Comparing {a} → {b}').replace('{a}', qd[0].dates[0]).replace('{b}', qd[0].dates[1]) : t('Needs two rounds of sampling')}</div>
    </div>
    <div class="card elev vk">
      <div class="vk-l">{t('Questions that went down')}</div>
      <div class="vk-v">{down.length}</div>
      <div class="vk-s">{t('A drop is not necessarily worse — sampling is noisy')}</div>
    </div>
    <div class="card elev vk">
      <div class="vk-l">{t('Task auto-verification')}</div>
      <div class="vk-v">{last ? last.pass : '—'}<span class="vk-unit"> {t('passed')}</span></div>
      <div class="vk-s">{last ? t('{f} failed · {m} need a human · {d}').replace('{f}', String(last.fail)).replace('{m}', String(last.manual)).replace('{d}', last.date) : t('Not run yet')}</div>
    </div>
  </div>

  <div class="row sec-head">
    <h4 class="sec-t">{t('Per-question before / after')}</h4>
    <span class="row" style="gap:4px;margin-left:12px">
      {#each MARKETS as [k, l] (k)}
        <button class="btn {market === k ? 'btn-secondary' : 'btn-ghost'} mkt-btn" onclick={() => (market = k)}>{t(l)}</button>
      {/each}
    </span>
  </div>

  <div class="tbl">
    <table class="table">
      <thead><tr>
        <th>{t('Question')}</th><th style="width:60px">{t('Market')}</th>
        <th style="width:170px">{t('Mention change')}</th><th style="width:110px">{t('Reading')}</th>
      </tr></thead>
      <tbody>
        {#each qd.filter((x) => x.before != null || x.after != null).slice(0, 16) as x (x.id || x.question)}
          {@const untested = x.after == null}
          {@const d = untested ? 0 : (x.after || 0) - (x.before || 0)}
          <tr>
            <td class="q-cell">{x.question}</td>
            <td class="mkt-cell">{mktName(x.market)}</td>
            <td>
              <span class="before">{x.before == null ? '—' : pct(x.before)}</span>
              <span class="muted">→</span>
              <span class="after" class:up={d > 0}>{x.after == null ? '—' : pct(x.after)}</span>
            </td>
            <td><span class="tag {!untested && d > 0 ? 'pill-good' : 'tag-dim'}">{untested ? t('Not measured') : d > 0 ? t('Up') : d < 0 ? t('Down') : t('Flat')}</span></td>
          </tr>
        {:else}
          <tr><td colspan="4" class="muted empty">
            {market === 'all' ? t('Needs at least two rounds of sampling') : t('No two-round comparison for this market yet')}
          </td></tr>
        {/each}
      </tbody>
    </table>
  </div>

  {#if progTasks.length}
    <h4 class="sec-t spaced">{t('Task-level before → after')}</h4>
    <p class="muted note">
      {t('First measurement is the snapshot taken at the task\'s first auto-verification (before); current is the latest (after). Whether the number moved is visible at a glance — no one has to take your word that it is done.')}
    </p>
    <div class="tbl">
      <table class="table">
        <thead><tr>
          <th style="width:44px"></th><th>{t('Task')}</th>
          <th style="width:320px">{t('Metric progress')}</th><th style="width:90px">{t('Status')}</th>
        </tr></thead>
        <tbody>
          {#each progTasks as task (task.id)}
            {@const done = task.status === 'done'}
            <tr>
              <td><span class="tag {task.priority === 'P0' ? 'tag-accent' : 'tag-dim'}">{task.priority}</span></td>
              <td class="task-cell">{task.id} · {task.title}</td>
              <td>{@html progBar(task.progress, task.progress_first)}</td>
              <td><span class="tag {done ? 'pill-good' : 'tag-dim'}">{done ? t('Verified') : t('Not met')}</span></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}

  {#if vh.length}
    <h4 class="sec-t spaced">{t('Verification history')}</h4>
    <div class="tbl">
      <table class="table">
        <thead><tr>
          <th style="width:110px">{t('Date')}</th><th style="width:80px">{t('Passed')}</th>
          <th style="width:80px">{t('Not met')}</th><th style="width:80px">{t('Needs a human')}</th>
          <th>{t('Notes')}</th>
        </tr></thead>
        <tbody>
          {#each vh.slice(-8).reverse() as v (v.key)}
            <tr>
              <td class="date-cell">{v.date}</td>
              <td class="pass-cell">{v.pass}</td>
              <td>{v.fail}</td>
              <td>{v.manual}</td>
              <td class="note-cell">{t('Decided automatically after re-crawling; regressions go straight back to the action plan')}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<style>
  .verify-kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 22px 0 18px; }
  .vk { padding: 15px; gap: 3px; }
  .vk-l { font-size: 11.5px; color: var(--t500); }
  .vk-v { font-size: 27px; font-weight: 500; }
  .vk-v.up { color: var(--accent); }
  .vk-unit { font-size: 14px; color: var(--t600); }
  .vk-s { font-size: 11px; color: var(--t600); }

  .sec-head { margin: 20px 0 8px; }
  .sec-t { font-size: 16px; margin: 0; }
  .sec-t.spaced { margin: 28px 0 8px; }
  .mkt-btn { font-size: 12px; padding: 3px 10px; }
  .note { font-size: 12px; margin-bottom: 8px; }

  .q-cell { font-size: 13.5px; }
  .mkt-cell { font-size: 12px; color: var(--t500); }
  .before { color: var(--t400); }
  .after { color: var(--t400); }
  .after.up { color: var(--a400); }
  .empty { font-size: 12.5px; }
  .task-cell { font-size: 13px; }
  .date-cell { font-size: 13px; }
  .pass-cell { color: var(--a400); }
  .note-cell { font-size: 12.5px; color: var(--t500); }

  @media (max-width: 640px) {
    .verify-kpis { grid-template-columns: 1fr; }
  }
</style>
