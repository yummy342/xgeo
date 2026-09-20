<script>
  import { onMount } from 'svelte'
  import Sidebar from './components/Sidebar.svelte'
  import LegacyView from './components/LegacyView.svelte'
  import Toast from './components/Toast.svelte'
  import Modal from './components/Modal.svelte'
  import Facts from './views/Facts.svelte'
  import Channels from './views/Channels.svelte'
  import Plan from './views/Plan.svelte'
  import Samples from './views/Samples.svelte'

  // 已迁到 Svelte 的视图。没列在这里的走 LegacyView 的旧实现。
  // 每批迁移就往这里加一个，B6 加满 17 个、删掉 LegacyView。
  const MIGRATED = { facts: Facts, channels: Channels, plan: Plan, samples: Samples }
  import { route, routeFromHash, syncHash } from './lib/router.svelte.js'
  import { ui } from './lib/stores/ui.svelte.js'
  import {
    project, projects, loadActions, loadProjects, loadProject, clearProject,
  } from './lib/stores/project.svelte.js'

  onMount(boot)

  // 复刻 ui.html:3003-3020 的启动 IIFE 与 load() 末尾的路由决策。
  // 装桥不在这里——见 main.js，必须早于组件挂载。
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
    {#if projects.error}
      <div class="page narrow">
        <h3>无法连接服务</h3>
        <p class="soft" style="font-size:13.5px">{projects.error}</p>
        <div class="row" style="margin-top:14px">
          <button class="btn btn-primary" onclick={() => location.reload()}>重试</button>
        </div>
      </div>
    {:else}
      {#if MIGRATED[route.name]}
        <!-- {#key} 是必需的：不加的话切路由时 Svelte 复用同一个组件实例，
             新视图不渲染，页面停在上一页的内容上。 -->
        {#key route.name}
          {@const View = MIGRATED[route.name]}
          <View />
        {/key}
      {:else}
        <LegacyView name={route.name} />
      {/if}
    {/if}
  </main>
</div>

<Modal />
<Toast />
