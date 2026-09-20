<script>
  import PageHead from '../components/PageHead.svelte'
  import { api, requestPost } from '../lib/api.js'
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'
  import { ui } from '../lib/stores/ui.svelte.js'

  // 迁自 ui.html:2799 vAssets。
  //
  // 旧版是 async 视图（在渲染路径里 fetch），而且 asOpen() 拿完数据后直接
  // 操作 DOM（$('#asview').innerHTML = ...），textarea 的值靠 oninput 手动
  // 镜像回全局 AS.text。这里都换成组件状态：数据在 $effect 里取，编辑用
  // bind:value——不再需要手工同步。

  const slug = $derived(project.data?.slug || '')
  const lint = $derived(project.data?.lint || {})

  // 每个分组的去处说明：首行是去向，次行是注意事项。
  const DEST = {
    '根目录': ['① Upload to the site root', 'Once uploaded it is reachable at your-domain/llms.txt; do not put it under /static/'],
    jsonld: ['② Paste into the page <head>', 'This is not a .json file to upload — wrap the content in <script type="application/ld+json"> and put it in the page'],
    snippets: ['③ Paste into the page template', 'Put the definition block below the hero tagline; the FAQ block\'s answers must be visible in the static HTML'],
    outlines: ['④ Not uploaded · for the content team', 'Writing outlines — draft from these skeletons in the Workbench'],
    drafts: ['⑤ Not uploaded · verify first', 'AI drafts. They must pass the risk check and be verified by a human before publishing'],
    internal: ['Notes and index · not uploaded', 'DEPLOY.md is the deployment checklist for developers, with acceptance criteria per step'],
  }
  const GROUP_LABEL = { '根目录': 'llms.txt' }
  const ORDER = ['根目录', 'jsonld', 'snippets', 'internal', 'outlines', 'drafts']
  const INTERNAL = { 'DEPLOY.md': 1, 'index.json': 1, '_lint.json': 1 }

  let tree = $state([])
  let treeLoaded = $state(false)
  let cur = $state(null)
  let text = $state('')
  let loadingText = $state(false)

  const groups = $derived.by(() => {
    const out = {}
    for (const a of tree) {
      const fn = a.path.split('/').pop()
      const key = INTERNAL[fn] ? 'internal' : a.group
      ;(out[key] = out[key] || []).push(a)
    }
    return out
  })

  $effect(() => {
    void project.data?.slug
    if (!slug) return
    api('/api/assets/' + slug).then((r) => {
      tree = Array.isArray(r) ? r : []
      treeLoaded = true
    })
  })

  // 从站点体检等处跳来时（assetSel）直接打开指定文件。
  //
  // 必须等 tree 到位再消费：视图是 {#key route.name} 重新挂载的，这两个
  // $effect 会连续跑，若不等就会拿空 tree 去 some()，判false 却已经把
  // assetSel 清掉了——那个入口等于从来不起作用。旧代码是把 api 请求 await
  // 完之后才检查 ST.assetSel，所以没有这个问题。
  let handledSel = null
  $effect(() => {
    const p = ui.assetSel
    if (!p || p === handledSel || !treeLoaded) return
    handledSel = p
    ui.assetSel = null
    if (tree.some((a) => a.path === p)) open(p)
  })

  // 请求序号：连点两个文件时，先发的响应可能后到。不挡住的话，
  // 编辑器头部显示的是 B、内容却是 A 的，按保存就把 A 写进了 B。
  let openSeq = 0

  async function open(path) {
    cur = path
    loadingText = true
    const mine = ++openSeq
    const r = await api(`/api/asset/${slug}?path=${encodeURIComponent(path)}`)
    if (mine !== openSeq) return      // 已被更晚的点击取代，丢弃这次结果
    // 读失败不能当成空内容：编辑器会显示成空的，一点保存就把原文件覆盖成空。
    // 退回到「没选文件」的状态，编辑器连同保存按钮一起消失。
    if (r.error) {
      toast(r.error, 'err')
      cur = null
      text = ''
      loadingText = false
      return
    }
    text = r.text || ''
    loadingText = false
  }

  async function save() {
    if (!cur) return
    await requestPost('/api/asset/' + slug, { path: cur, text })
    toast(t('Saved'))
  }

  function destOf(path) {
    const grp = path.indexOf('/') >= 0 ? path.split('/')[0] : '根目录'
    const fn = path.split('/').pop()
    return DEST[INTERNAL[fn] ? 'internal' : grp] || ['', '']
  }

  async function copyText() {
    try {
      await navigator.clipboard.writeText(text)
      toast(t('Copied'))
    } catch {
      toast(t('Copy failed'), 'err')
    }
  }
</script>

<div class="page">
  <PageHead
    kicker={t('ACTION · ASSETS')}
    title={t('Generated, deployable artifacts')}
    sub={t('Only llms.txt actually goes to the site root; JSON-LD goes into the head, HTML snippets into the template, and outlines and drafts never touch the site. Full steps and acceptance criteria are in DEPLOY.md.')}
  />

  {#if lint.total}
    <div class="card lint-warn">
      <div class="lint-t">
        {t('AI draft risk check:')} <b>{lint.total}</b> {t('items need human verification (high risk: {n}).').replace('{n}', String(lint.high))}
        {t('Do not publish before verifying — details in drafts/_lint.json.')}
      </div>
    </div>
  {/if}

  <div class="assets-layout">
    <div class="card elev tree">
      {#if tree.length}
        {#each ORDER.filter((g) => groups[g]) as g (g)}
          <div class="tree-grp">
            <span>{GROUP_LABEL[g] || g}</span>
            <span class="tree-dest">{(DEST[g] || [''])[0].replace(/^[①②③④⑤]\s*/, '')}</span>
          </div>
          {#each groups[g] as a (a.path)}
            <button class="navit tree-item" class:on={cur === a.path} onclick={() => open(a.path)}>
              <span class="mark"></span>
              <span class="tree-name">{a.path.split('/').pop()}</span>
              <span class="bdg">{(a.size / 1024).toFixed(1)}k</span>
            </button>
          {/each}
        {/each}
      {:else}
        <div class="muted empty">{t('No assets yet — run "Generate assets" under Settings')}</div>
      {/if}
    </div>

    <div class="card elev viewer">
      {#if !cur}
        <div class="muted hint">{t('Pick a file to view. Each file states at the top where it goes.')}</div>
      {:else}
        {@const d = destOf(cur)}
        <div class="card destbox">
          <div class="dest-t">{t(d[0])}</div>
          <div class="dest-s">{t(d[1])}</div>
        </div>
        <div class="row viewer-bar">
          <b class="viewer-path">{cur}</b>
          <span style="flex:1"></span>
          <button class="btn btn-ghost sm" onclick={copyText}>{t('Copy')}</button>
          <button class="btn btn-primary sm" onclick={save}>{t('Save changes')}</button>
        </div>
        {#if loadingText}
          <div class="muted hint">{t('Loading…')}</div>
        {:else}
          <textarea class="input" rows="20" bind:value={text}></textarea>
        {/if}
      {/if}
    </div>
  </div>
</div>

<style>
  .lint-warn { margin: 16px 0 0; box-shadow: 0 0 0 1px var(--a700); padding: 12px 16px; }
  .lint-t { font-size: 13px; color: var(--t400); }

  .assets-layout {
    display: grid; grid-template-columns: 300px 1fr; gap: 16px;
    margin-top: 18px; align-items: start;
  }
  .tree { padding: 12px; max-height: 560px; overflow: auto; }
  .tree-grp {
    font-size: 10px; letter-spacing: .08em; text-transform: uppercase; color: var(--t600);
    margin: 10px 4px 4px; display: flex; justify-content: space-between;
  }
  .tree-dest { color: var(--accent); text-transform: none; letter-spacing: 0; }
  .tree-item { font-size: 12.5px; }
  .tree-name { flex: 1; text-align: left; }
  .empty { font-size: 12.5px; padding: 8px; }

  .viewer { padding: 16px; min-height: 300px; }
  .hint { font-size: 13px; }
  .destbox { padding: 11px 14px; box-shadow: 0 0 0 1px var(--a700); margin-bottom: 12px; gap: 3px; }
  .dest-t { font-size: 12.5px; font-weight: 500; }
  .dest-s { font-size: 11.5px; color: var(--t500); }
  .viewer-bar { margin-bottom: 8px; }
  .viewer-path { font-size: 13px; }
  .sm { font-size: 12px; }

  @media (max-width: 640px) {
    .assets-layout { grid-template-columns: 1fr; }
  }
</style>
