<script>
  // 取代 ui.html:2084 pendPubModal。逐篇成稿的发布状态与再发布入口。
  // 点「发布」时切到 PublishDialog，由父组件持有那个弹窗的状态。
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'

  let { onclose, onpublish } = $props()

  const items = $derived(project.data?.content_pub || [])
</script>

<div class="modal" role="presentation">
  <div class="box">
    <h4>{t('Draft publishing status')}</h4>
    <p class="muted sub">
      {t('Publish each draft one by one; published ones show channel and link. Editing a draft means republishing for the channel copy to update.')}
    </p>

    <div class="list">
      {#each items as f (f.path)}
        <div class="row item">
          <div class="info">
            <div class="title" title={f.path}>{f.title}</div>
            <div class="meta">
              {f.path}{#if (f.qids || []).length} · {t('serves')} {(f.qids || []).join('/')}{/if}
            </div>
            {#each (f.published || []) as p (p.platform + p.at)}
              <div class="pub">
                ✓ {p.platform_name} {(p.at || '').slice(0, 10)}
                {#if p.url}<a href={p.url} target="_blank" class="link">{p.url.slice(0, 40)}</a>{/if}
              </div>
            {/each}
          </div>
          <button class="btn {(f.published || []).length ? 'btn-ghost' : 'btn-primary'} go"
                  onclick={() => { onclose?.(); onpublish?.('content/' + f.path) }}>
            {(f.published || []).length ? t('Publish again') : t('Publish')}
          </button>
        </div>
      {:else}
        <div class="muted">{t('No drafts yet — write one in the Workbench first')}</div>
      {/each}
    </div>

    <div class="row actions">
      <button class="btn btn-secondary" onclick={() => onclose?.()}>{t('Close')}</button>
    </div>
  </div>
</div>

<style>
  .sub { font-size: 12px; margin-top: 4px; }
  .list { max-height: 340px; overflow: auto; }
  .item { padding: 9px 0; box-shadow: inset 0 -1px 0 var(--line); align-items: flex-start; }
  .info { flex: 1; min-width: 0; }
  .title { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .meta { font-size: 11px; color: var(--t600); }
  .pub { font-size: 11px; color: var(--t500); }
  .link { color: var(--a300); }
  .go { flex: none; font-size: 12px; }
  .actions { justify-content: flex-end; margin-top: 12px; }
</style>
