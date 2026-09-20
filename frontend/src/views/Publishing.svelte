<script>
  import PageHead from '../components/PageHead.svelte'
  import PendingDialog from '../components/PendingDialog.svelte'
  import PublishConfigDialog from '../components/PublishConfigDialog.svelte'
  import PublishDialog from '../components/PublishDialog.svelte'
  import { api } from '../lib/api.js'
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'

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

  const pubs = $derived((pub && pub.publishers) || [])
  const recs = $derived(((pub && pub.records) || []).slice().reverse())
  const pend = $derived(contentPub.filter((f) => !(f.published || []).length))
  const ready = $derived(pubs.filter((x) => !x.missing.length).length)

  $effect(() => {
    void project.data?.slug
    if (!slug) return
    api('/api/publish/' + slug).then((r) => {
      pub = (r && !r.error) ? r : null
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
      <div class="pk-v">{contentPub.length}<span class="pk-u"> / {contentPub.length - pend.length} {t('sent')}</span></div>
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
            <span class="chan-state" class:ok={!x.missing.length}>
              {x.missing.length ? t('Missing {l}').replace('{l}', x.missing.join(', ')) : t('Ready')}
            </span>
            <button class="btn {x.missing.length ? 'btn-secondary' : 'btn-ghost'} chan-btn" onclick={() => (configTarget = x)}>{t('Configure')}</button>
          </div>
        {/each}
      </div>
    {/if}
  {/each}

  <div class="muted why">
    {@html t('Why there is no Weibo / Toutiao / Xiaohongshu / Bilibili / Sohu / LinkedIn / Facebook / Instagram: these platforms have no official publishing API available to individuals (or require business review, with tokens expiring constantly), and cookie-driven posting violates their terms and breaks quickly. <b>Better to not integrate than to fake an integration.</b> To cover those channels: publish by hand and tick them off under the Workbench distribution list, or bridge through the custom webhook to your own tooling.')}
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
                  <span class="tag tag-accent res">{t('Success')}</span>
                {:else}
                  <span class="tag tag-dim res" title={r.error || ''}>{t('Failed')}</span>
                {/if}
              </td>
              <td class="url-cell">
                {#if r.url}
                  <a href={r.url} target="_blank" class="url">{r.url}</a>
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
