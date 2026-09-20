<script>
  // 迁自 ui.html:1853 vPlan。
  // progBar 仍在 legacy 里（返回一段 HTML 字符串），所以这里用 {@html}。
  import { project, loadProject } from '../lib/stores/project.svelte.js'
  import { post } from '../lib/api.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'
  import PageHead from '../components/PageHead.svelte'
  import TaskDialog from '../components/TaskDialog.svelte'
  import PendingDialog from '../components/PendingDialog.svelte'
  import PublishDialog from '../components/PublishDialog.svelte'

  // 任务详情与状态改动的入口都收到这里，不再走 legacy 的 taskModal / setTask
  let openTask = $state(null)
  let pendingOpen = $state(false)
  let publishRel = $state(null)

  async function setStatus(id, status) {
    const r = await post('/api/task', { slug: project.data?.slug, id, status })
    if (!r.ok) { toast(r.error || t('Failed'), 'err'); return }
    await loadProject(project.data.slug, true)
  }

  const ts = $derived(project.data?.tasks || [])
  const deliveries = $derived(project.data?.deliveries || [])
  const slug = $derived(project.data?.slug || '')
  const contentPub = $derived(project.data?.content_pub || [])

  const STATUS = ['todo', 'doing', 'blocked', 'done']
  const RISK = { low: 'low risk', watch: 'needs watching', high: 'high risk' }
  const RISK_TIP = {
    low: 'Low-risk quick win: purely additive, reversible at any time',
    watch: 'Content change to watch: recheck on days 7/14/28 after publishing',
    high: 'High-risk technical change: back up, ship in small batches, keep a rollback',
  }

  const cnt = (s) => ts.filter((x) => x.status === s).length

  const sorted = $derived(ts.slice().sort(
    (a, b) => ((a.status === 'done') - (b.status === 'done')) || a.priority.localeCompare(b.priority),
  ))

  const pub = $derived(contentPub.filter((f) => (f.published || []).length))
  const pend = $derived(contentPub.filter((f) => !(f.published || []).length))
</script>

<div class="page">
  <div class="row plan-head">
    <div>
      <PageHead
        kicker={t('ACTION · PLAN')}
        title={t('{n} tasks, all derived from the gaps above').replace('{n}', String(ts.length))}
        sub={t('Every task carries its source, the role that owns it, and how it gets verified. Ones marked automatic are judged by the next round of sampling and re-crawling — no manual bookkeeping.')}
      />
    </div>
    <div class="row" style="flex:none">
      {#if deliveries.length}
        <a class="btn btn-secondary" href="/files/{slug}/delivery/{deliveries[0]}/03-工单表.csv">{t('Export CSV')}</a>
      {/if}
      <button class="btn btn-primary" onclick={() => window.runAction('verify')}>{t('Auto-verify')}</button>
    </div>
  </div>

  <div class="plan-kpis">
    {#each [['To do', cnt('todo'), ''], ['In progress', cnt('doing'), ''], ['Blocked', cnt('blocked'), ''], ['Done', cnt('done'), 'color:var(--accent)']] as [l, v, st]}
      <div class="card elev kpi">
        <div class="kpi-l">{t(l)}</div>
        <div class="kpi-v" style={st}>{v}</div>
      </div>
    {/each}
  </div>

  {#if contentPub.length}
    <div class="card elev pubcard">
      <div class="row">
        <div style="flex:1">
          <span class="pub-t">{t('Draft publishing')}</span>
          <span class="pub-n">
            {t('{n} drafts').replace('{n}', String(contentPub.length))} ·
            {t('published')} {pub.length} ·
            <span style="color:{pend.length ? 'var(--a300)' : 'var(--t500)'}">{t('pending')} {pend.length}</span>
          </span>
          <div class="pub-note">
            {t('Writing the content is only half of it — nothing that never goes out gets seen by any engine. Publishing is always your click; WeChat and WordPress only create drafts.')}
          </div>
        </div>
        {#if pend.length}
          <button class="btn btn-primary pub-btn" onclick={() => (pendingOpen = true)}>{t('Pending list →')}</button>
        {:else}
          <span class="tag tag-dim" style="flex:none">{t('All published')}</span>
        {/if}
      </div>
    </div>
  {/if}

  <div class="tbl">
    <table class="table">
      <thead><tr>
        <th style="width:44px"></th><th>{t('Task')}</th><th style="width:110px">{t('Source')}</th>
        <th style="width:80px">{t('Effort')}</th><th style="width:90px">{t('Owner')}</th>
        <th style="width:170px">{t('Status')}</th><th style="width:66px"></th>
      </tr></thead>
      <tbody>
        {#each sorted as task (task.id)}
          <tr>
            <td><span class="tag {task.priority === 'P0' ? 'tag-accent' : task.priority === 'P1' ? 'tag-neutral' : 'tag-dim'}">{task.priority}</span></td>
            <td>
              <div class="task-t" title={t('Click for details: why, how, and what counts as done')} onclick={() => (openTask = task)}>
                {task.id} · {task.title} <span class="task-more">{t('details')}</span>
              </div>
              <div class="task-sub">
                {t('Acceptance')} ({(task.acceptance || {}).type === 'auto' ? t('automatic') : t('manual')}): {(task.acceptance || {}).desc || ''}{#if task.risk} · <span style="color:{task.risk === 'high' ? 'var(--a300)' : 'var(--t600)'}" title={t(RISK_TIP[task.risk] || '')}>{t(RISK[task.risk] || '')}</span>{/if}
              </div>
              {@html window.progBar(task.progress, task.progress_first)}
            </td>
            <td class="cell-dim">{task.package}</td>
            <td class="cell-soft">{task.effort}</td>
            <td class="cell-soft">{task.owner}</td>
            <td>
              <div class="row" style="gap:4px">
                {#each STATUS as s (s)}
                  <button
                    class="btn {task.status === s ? 'btn-primary' : 'btn-ghost'} status-btn"
                    onclick={() => setStatus(task.id, s)}
                  >{t({ todo: 'To do', doing: 'In progress', blocked: 'Blocked', done: 'Done' }[s])}</button>
                {/each}
              </div>
            </td>
            <td>
              <div class="row" style="gap:4px">
                {#if task.package === '内容矩阵'}
                  <button class="btn btn-ghost row-btn" title={t('Jump straight to the question this task most needs written')} onclick={() => window.wbFromTask(task.id)}>{t('Open')}</button>
                  <button class="btn btn-ghost row-btn pub-open" title={t('Draft publish status and per-article publishing')} onclick={() => (pendingOpen = true)}>{t('Publish')}</button>
                {/if}
              </div>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>

{#if openTask}
  <TaskDialog task={openTask} onclose={() => (openTask = null)} />
{/if}

{#if pendingOpen}
  <PendingDialog onclose={() => (pendingOpen = false)} onpublish={(rel) => (publishRel = rel)} />
{/if}

{#if publishRel}
  <PublishDialog rel={publishRel} onclose={() => (publishRel = null)} />
{/if}

<style>
  .plan-head { align-items: flex-end; justify-content: space-between; gap: 20px; }
  .plan-kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 22px 0 12px; }
  .kpi { padding: 14px; gap: 2px; }
  .kpi-l { font-size: 11.5px; color: var(--t500); }
  .kpi-v { font-size: 26px; font-weight: 500; }

  .pubcard { padding: 14px 16px; margin-bottom: 16px; }
  .pub-t { font-size: 14px; font-weight: 500; }
  .pub-n { font-size: 12px; color: var(--t500); margin-left: 10px; }
  .pub-note { font-size: 11px; color: var(--t600); margin-top: 2px; }
  .pub-btn { flex: none; font-size: 12px; }

  .task-t { font-size: 13.5px; cursor: pointer; }
  .task-more { color: var(--a300); font-size: 11px; }
  .task-sub { font-size: 11px; color: var(--t600); }
  .cell-dim { font-size: 12px; color: var(--t500); }
  .cell-soft { font-size: 12.5px; color: var(--t400); }
  .status-btn { font-size: 11px; padding: 2px 7px; }
  .row-btn { font-size: 12px; }
  .pub-open { color: var(--a300); }

  @media (max-width: 640px) {
    .plan-kpis { grid-template-columns: repeat(2, 1fr); }
  }
</style>
