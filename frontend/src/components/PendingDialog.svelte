<script>
  import { hasPublished, isPrepared } from '../lib/publishstate.js'
  import { safeUrl } from '../lib/url.js'
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'

  // 取代 ui.html:2084 pendPubModal。逐篇成稿的发布状态与再发布入口。
  // 点「发布」时切到 PublishDialog，由父组件持有那个弹窗的状态。

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
                {#if isPrepared(p)}
                  <!-- 备好 ≠ 发布：这条只是内容备好了，等人去贴 -->
                  · {p.platform_name} {(p.at || '').slice(0, 10)} <span class="prep">{t('Prepared — not published yet')}</span>
                {:else}
                  ✓ {p.platform_name} {(p.at || '').slice(0, 10)}
                  <!-- 这里的 url 可能是人工回填的（用户输入）或 webhook 端点回的，
                       必须有守卫：不带守卫的话一条 javascript: 在这就变成可点的链接。
                       非 http(s) 一律当文本显示。 -->
                  {#if safeUrl(p.url)}
                    <a href={safeUrl(p.url)} target="_blank" class="link">{p.url.slice(0, 40)}</a>
                  {:else if p.url}
                    <span class="link">{p.url.slice(0, 40)}</span>
                  {/if}
                {/if}
              </div>
            {/each}
          </div>
          <button class="btn {hasPublished(f.published) ? 'btn-ghost' : 'btn-primary'} go"
                  onclick={() => { onclose?.(); onpublish?.('content/' + f.path) }}>
            {hasPublished(f.published) ? t('Publish again') : t('Publish')}
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
  .prep { color: var(--a300); }
  .link { color: var(--a300); }
  .go { flex: none; font-size: 12px; }
  .actions { justify-content: flex-end; margin-top: 12px; }
</style>
