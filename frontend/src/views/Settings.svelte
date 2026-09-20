<script>
  import BrandConfigDialog from '../components/BrandConfigDialog.svelte'
  import KeyDialog from '../components/KeyDialog.svelte'
  import PageHead from '../components/PageHead.svelte'
  import { actions } from '../lib/stores/project.svelte.js'
  import { api } from '../lib/api.js'
  import { go } from '../lib/router.svelte.js'
  import { jobs } from '../lib/stores/jobs.svelte.js'
import { jobLog, loadJobLog, runAction, setMonitor, statusLabel, stopJob } from '../lib/jobs.svelte.js'
  import { loadProject } from '../lib/stores/project.svelte.js'
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { ui } from '../lib/stores/ui.svelte.js'

  // 迁自 ui.html:2371 vSettings。17 个视图里最大的一个，也是最后一个。
  //
  // 旧版在渲染路径里做三件事：异步取 KEYS/PROJECTS/SET_CFG、以及一个裸
  // setTimeout 去回填上一个任务的日志（ui.html:2378）。前两件收进 $effect，
  // 第三件本来就是「任务结束后刷新日志」，也归 $effect——渲染函数不再有副作用。
  // 密钥与品牌配置弹窗都已改成组件，自己收 props，不再往全局挂。

  let openKey = $state(null)
  let showConfig = $state(false)

  // 旧 switchProject 要手工清 KEYS / PROJECTS / SET_CFG / PUB / AS / WB 六个全局
  // 缓存，再 load + 跳转。现在这些缓存都由各自组件持有，切项目时它们随
  // {#key route.name} 与 project.data 变化自然重建，只剩跨视图的 engSel 要清。
  async function switchProject(slug) {
    ui.engSel = null
    await loadProject(slug)
    go('overview')
  }

  const D = $derived(project.data || {})
  const slug = $derived(D.slug || '')
  const market = $derived(D.market || 'cn')

  let keys = $state([])
  let projects = $state([])
  let cfg = $state(null)

  const mon = $derived((cfg && cfg.monitor) || {})
  const monCur = $derived(mon.every_days || 0)
  const running = $derived(jobs.running)

  const ACTS = ['crawl', 'audit', 'bootstrap', 'sample', 'sample-sheet', 'plan', 'blueprint',
    'generate', 'lint', 'report', 'deliverables', 'verify', 'deliver']

  // 引擎与密钥面板的派生数据
  const keyInfo = $derived.by(() => {
    const KI = keys.map((k, i) => ({ ...k, i }))
    const apiK = KI.filter((k) => k.env)
    const man = KI.filter((k) => !k.env)
    const inMkt = (k) => market === 'both' || k.market === market
    const need = apiK.filter(inMkt).sort((a, b) => (b.search ? 1 : 0) - (a.search ? 1 : 0))
    const skip = apiK.filter((k) => !inMkt(k))
    const done = need.filter((k) => k.ok === true).length
    return { need, skip, man: man.filter(inMkt), done }
  })

  $effect(() => {
    void project.data?.slug
    api('/api/keys').then((r) => {
      keys = Array.isArray(r) ? r : []
    })
    api('/api/projects').then((r) => {
      projects = Array.isArray(r) ? r : []
    })
  })

  $effect(() => {
    void project.data?.slug
    if (!slug) return
    api('/api/config/' + slug).then((r) => {
      cfg = r || null
    })
  })

  // 兜底：任务已结束但页面还停在旧日志上时，把它显示出来。
  // 旧代码把这段写成渲染路径里的裸 setTimeout，每次重渲染都会重跑一次。
  $effect(() => {
    if (jobs.lastJob && !jobs.running && loadJobLog) {
      const id = jobs.lastJob
      queueMicrotask(() => loadJobLog(id))
    }
  })

  function mktName(m) {
    return m === 'cn' ? t('CN market') : m === 'global' ? t('Global market') : t('Both markets')
  }
</script>

<div class="page wide">
  <PageHead
    kicker={t('Settings')}
    title={t('Every setting in one place, grouped by what changing it affects')}
    sub={t('Sampling and runs are configuration, not daily navigation — day to day you only need the four main sections.')}
  />

  <h4 class="sec">{t('Brand and project')}</h4>
  <div class="tbl">
    <table class="table">
      <thead><tr>
        <th>{t('Brand')}</th><th style="width:210px">{t('Domain')}</th>
        <th style="width:110px">{t('Audit average')}</th><th style="width:90px">{t('Tasks')}</th><th style="width:80px"></th>
      </tr></thead>
      <tbody>
        {#each projects as p (p.slug)}
          <tr>
            <td>
              <span class="brand-name">{p.name}</span>
              {#if p.slug === slug}<span class="tag tag-accent current">{t('current')}</span>{/if}
            </td>
            <td class="cell-dim">{(p.site || '').replace('https://', '')}</td>
            <td class="cell-soft">{p.avg_score == null ? '—' : p.avg_score}</td>
            <td class="cell-soft">{p.tasks_total || '—'}</td>
            <td>
              <button class="btn btn-ghost sm" onclick={() => switchProject(p.slug)}>
                {p.slug === slug ? t('Refresh') : t('Open')}
              </button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
  <div class="row brand-actions">
    <button class="btn btn-primary" onclick={() => go('onboard', { obStep: 1 })}>{t('+ Add a brand')}</button>
    <button class="btn btn-secondary" onclick={() => (showConfig = true)}>{t('Edit current brand config')}</button>
  </div>

  <div class="settings-grid">
    <div class="card elev panel">
      <div>
        <div class="panel-t">{t('Engines and keys')}</div>
        <div class="panel-s">{t('Keys are written to .env in the project root and take effect immediately. <b>One working engine is enough to start sampling</b>; more engines widen coverage.')}</div>
      </div>
      <div class="key-progress" class:ok={keyInfo.done}>
        {t('Recommended: {d}/{n} ready').replace('{d}', String(keyInfo.done)).replace('{n}', String(keyInfo.need.length))}{#if !keyInfo.done}{t(' — start with the "preferred · searches" ones')}{/if}
      </div>

      <div class="grp-label">{t('Recommended · used by this project ({m})').replace('{m}', mktName(market))}</div>
      {#each keyInfo.need as k (k.code)}
        <div class="key-row">
          <span class="dot" style="background:{k.ok === true ? 'var(--a400)' : '#3f424d'}"></span>
          <span class="key-label" title={k.note || ''}>
            {k.label}<span class="muted key-mkt">{mktName(k.market)}</span>
            {#if k.search}
              <span class="tag tag-outline key-tag" title={t('Searches natively and returns citations — the highest-quality sampling evidence')}>{t('preferred · searches')}</span>
            {:else}
              <span class="muted key-tag-dim" title={t('API does not search; it measures brand awareness inside the model\'s parametric knowledge — still a valid metric')}>{t('optional · no search')}</span>
            {/if}
          </span>
          <span class="key-state">
            {k.ok === true ? t('Configured') + (k.key_tail ? ` ····${k.key_tail}` : '') : k.env}
          </span>
          <button class="btn {k.ok === true ? 'btn-ghost' : 'btn-secondary'} key-btn" onclick={() => (openKey = k)}>
            {k.ok === true ? t('Change') : t('Configure')}
          </button>
        </div>
      {/each}

      {#if keyInfo.skip.length}
        <div class="grp-label" title={t('This project targets {m}, so these belong to the other market').replace('{m}', mktName(market))}>{t('Optional · not used by this project')}</div>
        {#each keyInfo.skip as k (k.code)}
          <div class="key-row dim">
            <span class="dot" style="background:{k.ok === true ? 'var(--a400)' : '#3f424d'}"></span>
            <span class="key-label">{k.label}<span class="muted key-mkt">{mktName(k.market)}</span></span>
            <span class="key-state">{t('Not needed for this project')}</span>
            <button class="btn btn-ghost key-btn" onclick={() => (openKey = k)}>{t('Configure anyway')}</button>
          </div>
        {/each}
      {/if}

      <div class="grp-label">{t('No configuration needed · no public API, use the weekly manual sheet')}</div>
      {#each keyInfo.man as k (k.code)}
        <div class="key-row dim">
          <span class="dot" style="background:#3f424d"></span>
          <span class="key-label">{k.label}<span class="muted key-mkt">{mktName(k.market)}</span></span>
          <span class="key-state">{t('Manual sampling · no key')}</span>
        </div>
      {/each}
      <div class="row manual-row">
        <span class="muted manual-note">{t('These engines have no API but the most real users — run a manual sheet weekly (incognito), and once imported they count with the same basis as API samples.')}</span>
        <button class="btn btn-ghost sm" disabled={running} onclick={() => runAction('sample-sheet')}>{t('Generate weekly sheet')}</button>
      </div>
    </div>

    <div class="card elev panel">
      <div>
        <div class="panel-t">{t('Run tasks')}</div>
        <div class="panel-s">{t('Runs as a background subprocess; it finishes even if you close the page. One task per project at a time.')}</div>
      </div>
      <div class="row btn-row">
        <button class="btn btn-primary sm" disabled={running} onclick={() => runAction('autopilot')}>{t('✦ Full automatic run')}</button>
        <button class="btn btn-primary sm" disabled={running} onclick={() => runAction('serve')}>{t('▶ Run full cycle')}</button>
      </div>
      <div class="row btn-row">
        {#each ACTS as x (x)}
          <button class="btn btn-secondary act-btn" disabled={running} onclick={() => runAction(x)}>
            {(actions.map[x] || {}).label || x}
          </button>
        {/each}
      </div>
      <div class="row sched-row">
        <span class="sched-label">{t('Recurring run')}</span>
        {#each [0, 7, 14, 30] as dd (dd)}
          <button class="btn {monCur === dd ? 'btn-secondary' : 'btn-ghost'} sched-btn" onclick={() => setMonitor(dd)}>
            {dd ? t('every {d}d').replace('{d}', String(dd)) : t('Off')}
          </button>
        {/each}
        {#if monCur}
          <span class="muted sched-note">{t('next {d} · runs a full cycle when the dashboard is up and it comes due').replace('{d}', mon.next_run || '')}</span>
        {/if}
      </div>
      <div class="row job-row">
        <div id="jobstat" class="jobstat">
          {#if jobLog.label}
            <span class="job-name">{jobLog.label}</span>
            <span class="job-state" class:on={running}>{statusLabel(jobLog.status)}</span>
          {:else}
            <span class="muted">{t('No task has been started yet')}</span>
          {/if}
        </div>
        {#if running}
          <button class="btn btn-secondary sm" onclick={() => stopJob()}>{t('Stop task')}</button>
        {/if}
      </div>
      <pre class="log joblog" id="joblog">{jobLog.text}</pre>
    </div>
  </div>

  <div class="row pub-link">
    {t('Publishing channels (GitHub / WordPress / WeChat / Webhook) now have their own page →')}
    <button class="btn btn-ghost pub-btn" onclick={() => go('publishing')}>{t('Open publishing')}</button>
  </div>
  <p class="muted foot">
    {t('Teams and permissions: this is a single-machine, self-hosted build with no account system; the service binds 127.0.0.1 only. Multi-user access needs your own reverse proxy and authentication.')}
  </p>
</div>

{#if openKey}
  <KeyDialog
    entry={openKey}
    onclose={() => (openKey = null)}
    onchanged={() => { openKey = null; api('/api/keys').then((r) => { keys = Array.isArray(r) ? r : [] }) }}
  />
{/if}

{#if showConfig}
  <BrandConfigDialog
    onclose={() => (showConfig = false)}
    onchanged={() => loadProject(slug, true)}
  />
{/if}

<style>
  .page.wide { max-width: 1180px; }
  .sec { font-size: 16px; margin: 28px 0 10px; }
  .brand-name { font-size: 13.5px; }
  .current { font-size: 10px; }
  .cell-dim { font-size: 12.5px; color: var(--t500); }
  .cell-soft { font-size: 13px; color: var(--t400); }
  .sm { font-size: 12px; }
  .brand-actions { margin-top: 10px; }

  .settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 26px; }
  .panel { padding: 18px; gap: 8px; }
  .panel-t { font-size: 15px; font-weight: 500; }
  .panel-s { font-size: 11.5px; color: var(--t600); }

  .key-progress { font-size: 12px; color: var(--t400); margin-top: 2px; }
  .key-progress.ok { color: var(--t400); }
  .key-progress:not(.ok) { color: var(--a300); }
  .grp-label { font-size: 11px; letter-spacing: .08em; color: var(--t600); margin-top: 8px; }
  .key-row { display: flex; align-items: center; gap: 9px; padding: 5px 0; box-shadow: inset 0 -1px 0 var(--line); }
  .key-row.dim { opacity: .55; }
  .key-label { flex: 1; font-size: 13px; }
  .key-mkt { font-size: 11px; margin-left: 6px; }
  .key-tag { font-size: 10px; margin-left: 4px; }
  .key-tag-dim { font-size: 10.5px; margin-left: 4px; }
  .key-state { font-size: 11.5px; color: var(--t600); }
  .key-btn { font-size: 12px; padding: 2px 8px; }
  .manual-row { margin-top: 6px; }
  .manual-note { font-size: 11.5px; flex: 1; }

  .btn-row { gap: 6px; }
  .act-btn { font-size: 11.5px; padding: 4px 9px; }
  .sched-row { gap: 6px; align-items: center; padding-top: 4px; box-shadow: inset 0 1px 0 var(--line); }
  .sched-label { font-size: 12px; color: var(--t500); }
  .sched-btn { font-size: 11.5px; padding: 3px 9px; }
  .sched-note { font-size: 11.5px; }
  .job-row { gap: 6px; }
  .jobstat { font-size: 12.5px; flex: 1; display: flex; gap: 8px; align-items: center; }
  .job-name { color: var(--t300); }
  .job-state { font-size: 11.5px; color: var(--t500); }
  .job-state.on { color: var(--accent); }
  .joblog { max-height: 260px; }

  .pub-link { margin-top: 14px; font-size: 12.5px; color: var(--t500); }
  .pub-btn { font-size: 12.5px; color: var(--a300); }
  .foot { font-size: 12px; margin-top: 16px; }

  @media (max-width: 640px) {
    .settings-grid { grid-template-columns: 1fr; }
  }
</style>
