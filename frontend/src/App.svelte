<script>
  import Assets from './views/Assets.svelte'
  import Channels from './views/Channels.svelte'
  import Competitors from './views/Competitors.svelte'
  import Engines from './views/Engines.svelte'
  import Facts from './views/Facts.svelte'
  import Gaps from './views/Gaps.svelte'
  import Onboard from './views/Onboard.svelte'
  import Overview from './views/Overview.svelte'
  import Plan from './views/Plan.svelte'
  import Publishing from './views/Publishing.svelte'
  import Questions from './views/Questions.svelte'
  import Report from './views/Report.svelte'
  import Samples from './views/Samples.svelte'
  import Settings from './views/Settings.svelte'
  import Sidebar from './components/Sidebar.svelte'
  import SiteAudit from './views/SiteAudit.svelte'
  import Toast from './components/Toast.svelte'
  import Verify from './views/Verify.svelte'
  import Workbench from './views/Workbench.svelte'
  import { onMount } from 'svelte'
  import { t } from './lib/i18n/index.svelte.js'
  import { route, routeFromHash, syncHash } from './lib/router.svelte.js'
  import {
    project, projects, loadActions, loadProjects, loadProject, clearProject,
  } from './lib/stores/project.svelte.js'
  import { ui } from './lib/stores/ui.svelte.js'
  import { resumeJob } from './lib/jobs.svelte.js'

  // 17 个视图全部迁完，这里已经没有 fallback 分支——路由表就是全部。
  // 迁移期的桥（legacy.js / legacy-views.js）已整体拆除，没有第二套实现。
  const MIGRATED = {
    facts: Facts, channels: Channels, plan: Plan, samples: Samples,
    verify: Verify, assets: Assets, gaps: Gaps, questions: Questions,
    report: Report, workbench: Workbench, siteaudit: SiteAudit,
    competitors: Competitors, publishing: Publishing, engines: Engines,
    overview: Overview, onboard: Onboard, settings: Settings,
  }

  onMount(boot)

  // 刷新接回还在跑的任务。不接的话页面看着是空闲的，后台其实在跑，
  // 用户会再点一次「开始」——服务端挡住并报「已有任务在运行」，
  // 等于白等一轮；日志面板也永远是空的。
  $effect(() => {
    const jid = project.data?.running_job
    if (jid) resumeJob(jid)
  })

  // 复刻 ui.html:3003-3020 的启动 IIFE 与 load() 末尾的路由决策。
  async function boot() {
    await loadActions()
    const ps = await loadProjects()
    if (ps === null) return                    // 连接失败，交给错误页
    if (!ps.length) {                          // 一个项目都没有 → 接入引导
      clearProject()
      ui.obStep = 1
      route.name = 'onboard'
      return
    }
    await loadProject(ps[0].slug)
    // 深链优先；否则有采样数据看总览，没有就去设置页
    const h = routeFromHash()
    route.name = h || (project.data?.analytics?.latest_date ? 'overview' : 'settings')
    syncHash(route.name)
  }

  function toggleSide() {
    document.getElementById('side')?.classList.toggle('open')
  }
</script>

<button id="burger" class="btn btn-secondary" onclick={toggleSide}>☰</button>

<div id="shell">
  <Sidebar />
  <main id="main">
    {#if projects.error || project.error}
      <div class="page narrow">
        <h3>{t('Cannot reach the service')}</h3>
        <!-- project.error 之前只写不读：指标接口挂了的时候页面走「还没有采样
             数据」分支，用户会去重跑一轮采样（真金白银），而不是去看日志。 -->
        <p class="soft" style="font-size:13.5px">{projects.error || project.error}</p>
        <div class="row" style="margin-top:14px">
          <button class="btn btn-primary" onclick={() => location.reload()}>{t('Retry')}</button>
        </div>
      </div>
    {:else}
      <!-- {#key} 是必需的：不加的话切路由时 Svelte 复用同一个组件实例，
           新视图不渲染，页面停在上一页的内容上。 -->
      {#key route.name}
        {@const View = MIGRATED[route.name]}
        <View />
      {/key}
    {/if}
  </main>
</div>

<Toast />
