<script>
  import ChannelDialog from '../components/ChannelDialog.svelte'
  import PublishDialog from '../components/PublishDialog.svelte'
  import { api, post, request } from '../lib/api.js'
  import { demandSort, demandTag, diagTag } from '../lib/domain.js'
  import { go } from '../lib/router.svelte.js'
  import { pct } from '../lib/format.js'
  import {loadProject, project} from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { toast } from '../lib/stores/toast.svelte.js'
  import { ui } from '../lib/stores/ui.svelte.js'

  // 迁自 ui.html:1971 vWorkbench。
  //
  // 这是整仓最该换掉的一处：旧版把编辑内容挂在全局 WB 上，textarea 用
  // oninput="WB.text=this.value" 手工镜像，每次 render() 都用字符串重建整个
  // textarea——文本能保住，但焦点和光标会丢（元素被换掉了）。
  // 换 bind:value 后 textarea 不再重建。

  let openChan = $state(null)
  let publishRel = $state(null)

  const slug = $derived(project.data?.slug || '')
  const a = $derived(project.data?.analytics || {})
  const D = $derived(project.data || {})
  const facts = $derived((project.data?.facts_struct || {}).numbers || [])
  const lint = $derived(project.data?.lint || {})

  let qid = $state(null)
  let q = $state(null)
  let sources = $state([])
  let curIdx = $state(-1)
  let text = $state('')
  let check = $state(null)
  let miss = $state(null)
  let filter = $state('')
  let busy = $state(false)

  const cur = $derived(curIdx >= 0 ? sources[curIdx] : null)
  const stat = $derived(q ? (a.questions || []).find((x) => x.id === q.id) : null)

  const fitChs = $derived(q
    ? ((project.data?.blueprint || {}).channels || [])
        .filter((c) => (c.fits || []).includes(q.group) && (q.market === 'both' || c.market === q.market))
        .sort((x, y) => (x.priority || '').localeCompare(y.priority || ''))
    : [])

  const pickList = $derived.by(() => {
    const f = filter.toLowerCase()
    const list = (a.questions || []).filter((x) => !x.brand_probe && (!f || x.text.toLowerCase().includes(f)))
    return demandSort(list)
  })

  // 跳转传参：go('workbench', { wq: qid })
  $effect(() => {
    const wq = ui.wq
    if (!wq) return
    ui.wq = null
    loadQuestion(wq)
  })

  // 换题时先发的响应可能后到：那时 qid 是 B，sources 却是 A 的文件，
  // 选中并保存就把 A 的正文写进 B。
  let qSeq = 0

  async function loadQuestion(id) {
    busy = true
    const mine = ++qSeq
    const w = await api(`/api/workbench/${slug}?qid=${encodeURIComponent(id || '')}`)
    if (mine !== qSeq) return
    qid = id
    sources = w.sources || []
    q = w.question
    curIdx = -1
    text = ''
    check = null
    miss = (id && !q && !w.error) ? id : null
    busy = false
    if (sources.length) await loadFile(0)
  }

  // 请求序号：在底稿之间快速切换时，先发的响应可能后到。那时高亮的是
  // 「成稿」而正文却是「大纲」，点保存会把大纲内容写进成稿文件。
  let loadSeq = 0

  async function loadFile(i) {
    curIdx = i
    const s = sources[i]
    busy = true
    const mine = ++loadSeq
    const r = s.kind === 'content'
      ? await api(`/api/content/${slug}?path=${encodeURIComponent(s.path)}`)
      : await api(`/api/asset/${slug}?path=${encodeURIComponent(s.path)}`)
    if (mine !== loadSeq) return
    // 读失败不能当成空内容：编辑器会显示成空的，一点保存就把原文件覆盖成空。
    // 这种情况下干脆不选中任何来源，保存按钮自然失效。
    if (r.error) {
      toast(r.error, 'err')
      curIdx = -1
      text = ''
      check = null
      busy = false
      return
    }
    const body = r.text || ''
    const ck = await post('/api/precheck', { text: body })
    if (mine !== loadSeq) return      // 预检是第二次往返，回来时可能又切走了
    text = body
    check = (ck && ck.error) ? null : ck
    busy = false
  }

  async function runCheck() {
    const ck = await post('/api/precheck', { text })
    check = (ck && ck.error) ? null : ck
    toast(t('Pre-check updated'))
  }

  async function save() {
    if (!cur) { toast(t('Nothing to save'), 'err'); return }
    if (cur.kind === 'content') await request(`/api/content/${slug}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: cur.path, text }),
    })
    else await request(`/api/asset/${slug}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: cur.path, text }),
    })
    toast(t('Saved'))
  }

  async function publish() {
    if (!q) { toast(t('No target question'), 'err'); return }
    if (cur && cur.kind === 'draft' && lint.total) {
      if (!confirm(t('The draft risk check has {n} items awaiting human verification (high risk: {h}). Confirmed the facts?')
        .replace('{n}', String(lint.total)).replace('{h}', String(lint.high)))) return
    }
    let body = text
    if (body.indexOf(q.id) < 0) body = `<!-- 目标问题 ${q.id} -->\n\n` + body
    const r = await post(`/api/content/${slug}`, { path: `${q.id}-成稿.md`, text: body })
    if (!r.ok) { toast(t('Publish failed: {e}').replace('{e}', r.error || ''), 'err'); return }
    toast(t('Published as final draft'))
    await loadProject(slug, true)
  }

  async function toggleDist(chId, on, ev) {
    // 元素必须**在 await 之前**取出来：事件分发一结束 `currentTarget` 就置 null，
    // 而下面的回滚靠它 —— 原来读 ev.currentTarget 恒为 null，于是勾撤不回去，
    // 界面显示已铺、库里没有（正是这段注释想修的那个 bug）。`target` 不受影响。
    const el = ev && ev.target
    const r = await post('/api/distribution/' + slug, { qid: q.id, channel: chId, on })
    if (r.ok) {
      if (project.data) project.data.distribution = r.distribution
      toast(on ? t('Marked as planted ✓') : t('Mark removed'))
    } else {
      // 失败要把勾撤回去：checked={distDone(...)} 不是双向绑定，表达式值一直是
      // false，Svelte 只在「值变了」时才写 DOM —— 用户手动勾上的那个勾会留在
      // 界面上，看起来已铺，库里没有。
      if (el) el.checked = !on
      toast(t('Failed: {e}').replace('{e}', r.error || ''), 'err')
    }
  }

  function distDone(chId) {
    return !!(((project.data?.distribution || {})[q.id] || {})[chId])
  }

  function reset() {
    qid = null; q = null; sources = []; curIdx = -1; text = ''; check = null; miss = null
  }
</script>

<div class="page wb-page">
  <div class="row crumbs">
    <button class="btn btn-ghost crumb-btn" onclick={() => go('plan')}>{t('← Action plan')}</button><span>/</span>
    <span>{q ? `${q.id} · ${q.text}` : t('Pick a question')}</span>
    {#if q}
      <button class="btn btn-ghost crumb-btn reset-btn" onclick={reset}>{t('Change question →')}</button>
    {/if}
  </div>

  {#if q}
    <div class="wb3">
      <div class="wb-col">
        <div class="card elev side-card">
          <div class="side-k">{t('What this task solves')}</div>
          <div class="side-q">{q.text}</div>
          <div class="side-stat">
            {#if stat}
              {t('You currently mention')} {stat.mention == null ? t('Not sampled') : pct(stat.mention)} · {stat.samples} {t('samples')} · {t('content')} {stat.content}
            {/if}
          </div>
        </div>

        <div class="card elev side-card">
          <div class="side-k">{t('Required extraction blocks (measured lift)')}</div>
          {#each (check ? check.checks.slice(2) : []) as c (c.t)}
            <div class="row block-row">
              <span class="dot" style="background:{c.ok ? 'var(--accent)' : '#595d6c'}"></span>
              <span class="block-name">{c.t}</span><span class="block-lift">{c.lift}</span>
            </div>
          {:else}
            <div class="muted side-empty">{t('Load a draft to see this')}</div>
          {/each}
        </div>

        <div class="card elev side-card">
          <div class="side-k">{t('Draw from the fact base')}</div>
          <div class="side-facts">
            {facts.slice(0, 4).map((n) => `${n.fact} ${n.value}`).join(' · ') || t('The fact base is empty')}
          </div>
          <button class="btn btn-ghost self-start" onclick={() => go('facts')}>{t('Open Brand Facts →')}</button>
        </div>
      </div>

      <div class="card elev editor">
        <div class="row editor-bar">
          {#each sources as s, i (s.path)}
            <button class="btn {curIdx === i ? 'btn-primary' : 'btn-ghost'} sm" onclick={() => loadFile(i)}>
              {t({ content: 'Final draft', draft: 'AI draft', outline: 'Outline' }[s.kind] || s.kind)}
            </button>
          {:else}
            <span class="muted editor-empty">{t('No draft yet — run "Generate assets" to produce an outline')}</span>
          {/each}
          <span class="editor-actions">
            <button class="btn btn-ghost sm" onclick={runCheck} disabled={busy}>{t('Re-check')}</button>
            <button class="btn btn-secondary sm" onclick={save} disabled={busy}>{t('Save')}</button>
            {#if cur && cur.kind !== 'content'}
              <button class="btn btn-primary sm" onclick={publish}>{t('Publish as final')}</button>
            {/if}
            {#if cur && cur.kind === 'content'}
              <button class="btn btn-primary sm" onclick={() => (publishRel = 'content/' + cur.path)}>{t('Publish to channels…')}</button>
            {/if}
          </span>
        </div>
        <textarea id="wbtext" class="input wb-text" bind:value={text}></textarea>
      </div>

      <div class="wb-col">
        <div class="card elev side-card">
          <div class="side-k">{t('CITABILITY PRE-CHECK')}</div>
          <div class="grade-row">
            <span class="grade">{check ? check.grade : '—'}</span>
            <span class="grade-sub">{check ? `${check.wc} ${t('words')} · ${check.h2} ${t('sections')}` : ''}</span>
          </div>
          {#each (check ? check.checks.slice(0, 2) : []) as c (c.t)}
            <div class="row block-row">
              <span class="dot" style="background:{c.ok ? 'var(--accent)' : '#595d6c'}"></span>
              <span>{c.t}</span>
            </div>
          {/each}
        </div>

        {#if cur && cur.kind === 'draft' && lint.total}
          <div class="card lint-card">
            <div class="lint-k">{t('DRAFT RISK')}</div>
            <div class="lint-body">
              {t('This batch has')} <b>{lint.total}</b> {t('items awaiting human verification (high risk: {h}).').replace('{h}', String(lint.high))}
              {t('AI invents competitor names and figures to fill tables — check every line before publishing. Details in _lint.json under Assets.')}
            </div>
          </div>
        {/if}

        <div class="card elev side-card">
          <div class="side-k">{t('AFTER PUBLISHING (MANUAL)')}</div>
          <div class="after-body">
            {@html t('① Publish to the site or the matching channel<br>② Submit for indexing (Baidu / Bing / Quark)<br>③ The next sampling round rechecks this question<br>④ Compare before/after under Verification')}
          </div>
        </div>

        <div class="card elev side-card">
          <div class="side-k">{t('Distribution list · where this piece should go')}</div>
          <div class="muted dist-note">
            {t('Channels matching this question\'s group ({g}) and market. Tick them off as you plant — the Channel Map tallies along.')}
          </div>
          {#each fitChs as c (c.id)}
            <label class="row dist-row">
              <input type="checkbox" class="dist-ch" checked={distDone(c.id)} onchange={(e) => toggleDist(c.id, e.currentTarget.checked, e)}>
              <span class="dist-name" class:done={distDone(c.id)}>{c.name.split('（')[0]}</span>
              <span class="tag {c.priority === 'P0' ? 'tag-accent' : 'tag-dim'} pri">{c.priority}</span>
              <span class="tag tag-outline pri" role="button" tabindex="0"
                    onclick={(e) => { e.preventDefault(); openChan = c }}
                    onkeydown={(e) => { if (e.key === 'Enter') openChan = c }}>{t('details')}</span>
            </label>
          {:else}
            <span class="muted side-empty">{t('No matching channel for this group')}</span>
          {/each}
        </div>
      </div>
    </div>
  {:else}
    <div class="card elev picker">
      <div class="pick-t">{t('Pick a question and write right here')}</div>
      {#if miss}
        <div class="pick-miss">{t('{q} is not in the question bank — pick another below').replace('{q}', miss)}</div>
      {/if}
      <p class="soft pick-sub">
        {t('Below is the topic pool, sorted by "most worth writing" — unmentioned, contentless questions first. Click any row to start, with the question\'s existing draft, brand facts and pre-check loaded.')}
      </p>
      <input class="input pick-search" placeholder={t('Search questions…')} bind:value={filter}>
      <div id="wbpick" class="pick-list">
        {#each pickList as item (item.id)}
          <div class="row pick-row" onclick={() => go('workbench', { wq: item.id })}>
            <!-- item.text 必须走自动转义：题目来自 bootstrap / expand 的 LLM 生成
                 和 /api/questions-add，含 HTML 就在看板源里执行。demandTag 内部
                 自己 esc，单独给它 {@html}。 -->
            <span class="pick-q">{item.text}{@html demandTag(item.id)}</span>
            {@html diagTag(item.diagnosis)}
            <span class="pick-state" class:done={item.content === '已成稿'}>{item.content}</span>
            <span class="muted pick-mkt">{item.market === 'cn' ? t('CN market') : item.market === 'global' ? t('Global market') : t('Both markets')}</span>
          </div>
        {:else}
          <div class="muted side-empty">{t('No matching questions')}</div>
        {/each}
      </div>
      <div class="muted pick-foot">
        {t('Need full metrics (mention rate, group, market)?')}
        <span class="pick-link" role="button" tabindex="0" onclick={() => go('questions')}
              onkeydown={(e) => { if (e.key === 'Enter') go('questions') }}>{t('Open the question bank →')}</span>
      </div>
    </div>
  {/if}
</div>

{#if openChan}
  <ChannelDialog channel={openChan} onclose={() => (openChan = null)} />
{/if}

{#if publishRel}
  <PublishDialog rel={publishRel} onclose={() => (publishRel = null)} />
{/if}

<style>
  .wb-page { padding: 28px 36px 60px; }
  .crumbs { font-size: 12px; color: var(--t600); margin-bottom: 14px; }
  .crumb-btn { font-size: 12px; padding: 0; }
  .reset-btn { margin-left: 8px; }

  .wb-col { display: flex; flex-direction: column; gap: 12px; }
  .side-card { padding: 14px; gap: 8px; }
  .side-k { font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: var(--t600); }
  .side-q { font-size: 13.5px; line-height: 1.5; }
  .side-stat { font-size: 11.5px; color: var(--t500); }
  .side-empty { font-size: 12px; }
  .side-facts { font-size: 12.5px; color: var(--t400); line-height: 1.55; }
  .self-start { align-self: flex-start; font-size: 12px; }

  .block-row { gap: 8px; font-size: 12.5px; }
  .block-name { flex: 1; }
  .block-lift { font-size: 11px; color: var(--t600); }

  .editor { padding: 0; overflow: hidden; }
  .editor-bar { padding: 11px 14px; box-shadow: inset 0 -1px 0 var(--divider); }
  .editor-empty { font-size: 12px; }
  .editor-actions { margin-left: auto; display: flex; gap: 9px; flex-wrap: wrap; }
  .sm { font-size: 12px; }
  /* 编辑区：旧版靠 oninput 镜像 + 整块重建，这里 bind:value，元素不再被替换 */
  .wb-text { border: 0; border-radius: 0; min-height: 480px; }

  .grade-row { display: flex; align-items: baseline; gap: 8px; }
  .grade { font-size: 34px; font-weight: 500; color: var(--accent); }
  .grade-sub { font-size: 12px; color: var(--t500); }

  .lint-card { padding: 12px 14px; box-shadow: 0 0 0 1px var(--a700); gap: 5px; }
  .lint-k { font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: var(--accent); }
  .lint-body { font-size: 12.5px; color: var(--t400); line-height: 1.5; }

  .after-body { font-size: 12.5px; color: var(--t400); line-height: 1.6; }

  .dist-note { font-size: 11px; }
  .dist-row { gap: 8px; padding: 4px 0; font-size: 12.5px; cursor: pointer; box-shadow: inset 0 -1px 0 var(--line); }
  .dist-ch { width: auto; }
  .dist-name { flex: 1; }
  .dist-name.done { color: var(--t600); text-decoration: line-through; }
  .pri { font-size: 10px; }

  .picker { padding: 22px 24px; max-width: 820px; gap: 10px; }
  .pick-t { font-size: 15px; font-weight: 500; }
  .pick-miss { font-size: 13px; color: var(--a300); padding: 10px 12px; border-radius: var(--r-md); background: var(--deep); }
  .pick-sub { font-size: 13px; margin: 0; }
  .pick-search { max-width: 340px; }
  .pick-list { max-height: 440px; overflow: auto; }
  .pick-row { gap: 10px; padding: 9px 10px; border-radius: var(--r-md); cursor: pointer; box-shadow: inset 0 -1px 0 var(--line); }
  .pick-row:hover { background: var(--deep); }
  .pick-q { flex: 1; font-size: 13px; }
  .pick-state { font-size: 11.5px; color: var(--t600); flex: none; }
  .pick-state.done { color: var(--a300); }
  .pick-mkt { font-size: 11px; flex: none; }
  .pick-foot { font-size: 11.5px; }
  .pick-link { color: var(--a300); cursor: pointer; }

  @media (max-width: 640px) {
    .wb-page { padding: 18px 16px 48px; }
  }
</style>
