<script>
  import PageHead from '../components/PageHead.svelte'
  import ManualPublishDialog from '../components/ManualPublishDialog.svelte'
  import PendingDialog from '../components/PendingDialog.svelte'
  import PublishConfigDialog from '../components/PublishConfigDialog.svelte'
  import PublishDialog from '../components/PublishDialog.svelte'
  import { api } from '../lib/api.js'
  import { hasPublished, isPrepared, stateOf as stateOfRecords } from '../lib/publishstate.js'
  import { safeUrl } from '../lib/url.js'
  import { loadProject, project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'

  // 迁自 ui.html:2317 vPublishing。
  //
  // 旧版是 async 视图：在渲染路径里 `if(!PUB) PUB = await api(...)`。
  // 这里改成 $effect 取数，渠道弹窗改成组件（自己收 props），不再往全局挂。

  let pendingOpen = $state(false)
  let publishRel = $state(null)
  let configTarget = $state(null)

  const D = $derived(project.data || {})
  const slug = $derived(D.slug || '')
  const contentPub = $derived(D.content_pub || [])

  let pub = $state(null)

  // 发布记录里的 url 是渠道响应直接落库的：webhook 端点可以回 `javascript:...`，
  // 绑到 href 上点一下就执行。守卫收在 lib/url.js（三处渲染共用）。
  const pubs = $derived((pub && pub.publishers) || [])
  const recs = $derived(((pub && pub.records) || []).slice().reverse())
  const pend = $derived(contentPub.filter((f) => !hasPublished(f.published)))
  // 「可用」= 至少有一条通路：半自动渠道无需凭证，也算可用
  const ready = $derived(pubs.filter((x) => x.path === 'semi' || !x.missing.length).length)

  // 「已发布」取渠道侧的可见性，不是我们自己的调用是否成功 —— 判据收在
  // lib/publishstate.js（四处共用，理由见那个文件）。
  const stateOf = (f) => stateOfRecords(f.published)
  const pubCount = $derived(contentPub.filter((f) => stateOf(f) === 'published').length)
  const draftCount = $derived(contentPub.filter((f) => stateOf(f) === 'draft').length)
  const prepCount = $derived(contentPub.filter((f) => stateOf(f) === 'prepared').length)
  // 半自动渠道的去回填入口：带 id 的那条记录
  let manualRec = $state(null)

  $effect(() => {
    void project.data?.slug
    if (!slug) return
    api('/api/publish/' + slug).then((r) => {
      // 失败不能静默成空态：页面会显示「Channels ready 0/0 · 还没有发布记录」，
      // 把「接口挂了」讲成「你还没发过文章」，用户既不知道出了事也没有重试入口。
      if (r && r.error) { toast.error(r.error); pub = null; return }
      pub = r || null
    })
  })

  const GROUPS = [
    ['general', 'General · long-form home', 'Where the full article lives, and the back-link source that social channels point at. Publish here first.'],
    ['cn', 'CN market', 'Connected where an official API is actually available'],
    ['global', 'Global market', 'Social channels post title + summary + back-link; long-form goes to the general channel first'],
  ]
</script>

<div class="page wide">
  <PageHead
    kicker={t('ACCOUNT · PUBLISHING')}
    title={t('Send final drafts to your own channels')}
    sub={t('Credentials go in .env (gitignored). <b>Publishing is always a manual click — there is no auto-publish.</b> WeChat and WordPress only create drafts; they go public once you confirm in their own consoles.')}
  />

  <div class="pub-kpis">
    <div class="card elev pk">
      <div class="pk-l">{t('Channels ready')}</div>
      <div class="pk-v" class:ok={ready}>{ready}<span class="pk-u"> / {pubs.length}</span></div>
    </div>
    <div class="card elev pk">
      <div class="pk-l">{t('Drafts / published')}</div>
      <div class="pk-v">{contentPub.length}<span class="pk-u"> / {pubCount} {t('published')}</span>
        {#if draftCount}<span class="pk-u draft-n"> · {draftCount} {t('Draft')}</span>{/if}
        {#if prepCount}<span class="pk-u prep-n"> · {prepCount} {t('Prepared')}</span>{/if}
      </div>
    </div>
    <div class="card elev pk clickable" onclick={() => (pendingOpen = true)} title={t('Open the pending list')}>
      <div class="pk-l">{t('Pending')}</div>
      <div class="pk-v" class:pend={pend.length}>{pend.length}<span class="pk-link"> {t('list →')}</span></div>
    </div>
  </div>

  {#each GROUPS as [mk, label, hint] (mk)}
    {@const list = pubs.map((x, i) => ({ x, i })).filter(({ x }) => (x.market || 'general') === mk)}
    {#if list.length}
      <h4 class="grp-h">{t(label)}<span class="grp-hint"> · {t(hint)}</span></h4>
      <div class="card elev grp-card">
        {#each list as { x, i } (x.code)}
          <div class="row chan-row">
            <span class="dot" style="background:{x.missing.length ? '#595d6c' : 'var(--a400)'}"></span>
            <span class="chan-main">
              {x.name}
              <div class="muted chan-note">{x.note}</div>
            </span>
            <span class="tag tag-dim path">{x.path === 'semi' ? t('Semi-automatic') : t('Automatic')}</span>
            {#if x.path === 'semi'}
              <!-- 半自动渠道不要凭证，「Missing X」对它没意义；要说明的是它的原生 API 通不通 -->
              <span class="chan-state" title={x.semi?.api?.note || ''}>
                {#if x.semi?.api?.status === 'blocked'}
                  {t('No automatic path — prepare and publish yourself')}
                {:else if x.missing.length}
                  <!-- 双路渠道（Reddit/公众号）凭证或 cfg 缺才会落到这；说「待核实」
                       是把真因盖掉 —— 这两个恰恰最可能补齐后改走自动通路 -->
                  {t('Fell back to semi — missing {l}').replace('{l}', x.missing.join(', '))}
                {:else}
                  {t('Native API unverified')}
                {/if}
              </span>
            {:else}
              <span class="chan-state" class:ok={!x.missing.length}>
                {x.missing.length ? t('Missing {l}').replace('{l}', x.missing.join(', ')) : t('Ready')}
              </span>
            {/if}
            <button class="btn {x.missing.length ? 'btn-secondary' : 'btn-ghost'} chan-btn" onclick={() => (configTarget = x)}>{t('Configure')}</button>
          </div>
        {/each}
      </div>
    {/if}
  {/each}

  <div class="muted why">
    {@html t('Why some channels are semi-automatic: their rules forbid an app from posting on your behalf. Weibo requires OAuth2 user authorisation for its publishing API, bans apps that sync to multiple platforms, and states outright that an app must not share information to your account without an explicit choice. So the tool prepares the title, body, tags and back-link, opens the official publishing page, and <b>you click publish</b>. That is not a compromise — it is the only form those platforms allow. <b>We still never simulate a logged-in session to post.</b> You will find the one-click prepare-and-copy flow in the per-article publish dialog.')}
  </div>

  <h4 class="grp-h">
    {t('Publish history')}{#if recs.length}<span class="grp-hint"> · {t('{n} records').replace('{n}', String(recs.length))}</span>{/if}
  </h4>
  {#if recs.length}
    <div class="tbl">
      <table class="table">
        <thead><tr>
          <th style="width:130px">{t('Time')}</th><th style="width:130px">{t('Publisher')}</th>
          <th>{t('Content')}</th><th style="width:70px">{t('Result')}</th><th style="width:220px">{t('Destination')}</th>
        </tr></thead>
        <tbody>
          {#each recs.slice(0, 50) as r (r.at + r.path)}
            <tr>
              <td class="t-cell">{(r.at || '').slice(0, 16).replace('T', ' ')}</td>
              <td class="c-cell">{r.platform_name}</td>
              <td class="ct-cell" title={r.path || ''}>{r.title || r.path || ''}</td>
              <td>
                {#if r.ok}
                  {#if isPrepared(r)}
                    <span class="tag tag-dim res" title={r.note || ''}>{t('Prepared')}</span>
                    <button class="btn btn-ghost mini"
                            onclick={() => (manualRec = { code: r.platform, path: r.path, id: r.id })}>
                      {t('Fill in')}
                    </button>
                  {:else if r.state === 'draft'}
                    <span class="tag tag-dim res" title={r.note || ''}>{t('Draft')}</span>
                  {:else}
                    <span class="tag tag-accent res">{t('Success')}</span>
                  {/if}
                {:else}
                  <span class="tag tag-dim res" title={r.error || ''}>{t('Failed')}</span>
                {/if}
              </td>
              <td class="url-cell">
                {#if safeUrl(r.url)}
                  <a href={safeUrl(r.url)} target="_blank" rel="noreferrer" class="url">{r.url}</a>
                {:else if r.url}
                  <!-- 非 http(s) 的 url 只当文本显示：webhook 端点返回的 url 是
                       直接落库的，`javascript:...` 绑到 href 上点一下就执行。 -->
                  <span class="url">{r.url}</span>
                {:else}
                  <span class="muted">{r.note || r.error || '—'}</span>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else}
    <div class="muted empty">{t('No publish records yet — publish your first piece from Action Plan → draft publishing, or the Workbench.')}</div>
  {/if}
</div>

{#if pendingOpen}
  <PendingDialog onclose={() => (pendingOpen = false)} onpublish={(rel) => (publishRel = rel)} />
{/if}

{#if publishRel}
  <PublishDialog rel={publishRel} onclose={() => (publishRel = null)} />
{/if}

{#if manualRec}
  <ManualPublishDialog rel={manualRec.path} code={manualRec.code} id={manualRec.id}
                       onclose={() => (manualRec = null)}
                       ondone={async () => {
                         // 两处都要刷：pub 供记录表，project.data 供 KPI/待发布清单
                         // （contentPub 全部派生自 project.data）。只刷 pub 的话，
                         // 回填成功后顶部还写着「N 已备好」、清单里还写「尚未发布」。
                         const r = await api('/api/publish/' + slug)
                         if (r && !r.error) pub = r
                         await loadProject(slug, true)
                       }} />
{/if}

{#if configTarget}
  <PublishConfigDialog
    publisher={configTarget}
    onclose={() => (configTarget = null)}
    onchanged={() => { configTarget = null; api('/api/publish/' + slug).then((r) => { if (r && !r.error) { pub = r } }) }}
  />
{/if}

<style>
  .page.wide { max-width: 1080px; }
  .pub-kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 22px 0 16px; }
  .pk { padding: 15px; gap: 3px; }
  .pk.clickable { cursor: pointer; }
  .pk-l { font-size: 11.5px; color: var(--t500); }
  .pk-v { font-size: 26px; font-weight: 500; }
  .pk-v.ok { color: var(--accent); }
  .pk-v.pend { color: var(--a300); }
  .pk-u { font-size: 13px; color: var(--t600); }
  .pk-u.prep-n { color: var(--a300); }
  .pk-link { font-size: 12px; color: var(--a300); }

  .grp-h { font-size: 16px; margin: 20px 0 6px; }
  .grp-hint { font-size: 11.5px; color: var(--t600); font-weight: 400; }
  .grp-card { padding: 6px 18px; }
  .chan-row { padding: 11px 0; box-shadow: inset 0 -1px 0 var(--line); }
  .chan-main { flex: 1; font-size: 13.5px; }
  .chan-note { font-size: 11.5px; margin-top: 1px; }
  .chan-state { font-size: 11.5px; color: var(--t600); }
  .chan-state.ok { color: var(--a300); }
  .chan-btn { font-size: 12px; padding: 3px 10px; }
  .tag.path { font-size: 10.5px; margin-right: 8px; }
  .mini { font-size: 11px; padding: 1px 7px; margin-left: 6px; }

  .why { font-size: 11.5px; margin-top: 10px; line-height: 1.7; }

  .t-cell { font-size: 12px; color: var(--t500); }
  .c-cell { font-size: 12.5px; }
  .ct-cell { font-size: 12.5px; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .res { font-size: 10.5px; }
  .url-cell { font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .url { color: var(--a300); }
  .empty { font-size: 12.5px; }

  @media (max-width: 640px) {
    .pub-kpis { grid-template-columns: 1fr; }
  }
</style>
