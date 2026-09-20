<script>
  // 复刻 ui.html:1048-1081 的 renderSide。导航结构与语言列表直接取 legacy 的
  // GL_NAV / GL_ULANG，不重新定义——两套前端同时在线，漂移了就没法对照。
  import { project } from '../lib/stores/project.svelte.js'
  import { route, go } from '../lib/router.svelte.js'
  import { jobs } from '../lib/stores/jobs.svelte.js'
  import SwitchBrandDialog from './SwitchBrandDialog.svelte'

  let switching = $state(false)

  const NAV = window.GL_NAV || []
  const badgeOf = window.GL_BADGE || (() => '')
  const ULANG = window.GL_ULANG || 'en'
  const LANGS = [['zh', '中'], ['en', 'EN'], ['ja', '日']]

  const brandName = $derived(project.data?.brand?.name || '—')
  const latest = $derived(project.data?.analytics?.latest_date || '—')
</script>

<aside id="side">
  <div class="top">
    <div class="brand-row">
      <div class="brand">Geo<span>Look</span></div>
      <span class="langs">
        {#each LANGS as [l, t]}
          <button class="lang" class:on={ULANG === l} onclick={() => window.setLang(l)}>{t}</button>
        {/each}
      </span>
    </div>
    <div class="tagline">生成式引擎优化平台</div>
  </div>

  <button class="btn btn-secondary pick" onclick={() => (switching = true)}>
    <span class="pick-l">
      <span class="pick-k">当前品牌</span>
      <span class="pick-v">{brandName}</span>
    </span>
    <span class="pick-arrow">切换 ▾</span>
  </button>

  <nav>
    {#each NAV as g}
      <div class="grp">
        <div class="navgrp">{g.t}</div>
        {#each g.items as [k, t]}
          <button class="navit" class:on={route.name === k} onclick={() => go(k)}>
            <span class="mark"></span><span>{t}</span><span class="bdg">{badgeOf(k)}</span>
          </button>
        {/each}
      </div>
    {/each}
  </nav>

  <div class="foot">
    数据更新于 {latest}<br>
    采样为手动触发或由 schedule 驱动
    <div class="run">
      {#if jobs.running}
        <span class="spin"></span>任务运行中
      {:else}
        <button class="btn btn-ghost run-btn" onclick={() => window.runAction('serve')}>▶ 跑完整一期</button>
      {/if}
    </div>
  </div>
</aside>

{#if switching}
  <SwitchBrandDialog currentSlug={project.slug} onclose={() => (switching = false)} />
{/if}

<style>
  .top { padding: 0 8px; }
  .brand-row { display: flex; align-items: center; justify-content: space-between; }
  .brand { font-weight: 500; font-size: 17px; letter-spacing: -.01em; }
  .brand span { color: var(--accent); }
  .langs { display: flex; gap: 2px; }
  .lang {
    background: none; border: 0; font-size: 10.5px; padding: 2px 6px;
    border-radius: 5px; cursor: pointer; color: var(--t600);
  }
  .lang.on { background: var(--a900); color: var(--a300); }
  .tagline { font-size: 11px; color: var(--t500); margin-top: 2px; }

  .pick { justify-content: space-between; padding: 8px 10px; text-align: left; }
  .pick-l { display: flex; flex-direction: column; gap: 1px; align-items: flex-start; }
  .pick-k { font-size: 9px; letter-spacing: .12em; color: var(--t500); text-transform: uppercase; }
  .pick-v { font-size: 13px; }
  .pick-arrow { color: var(--t500); font-size: 11px; }

  nav { display: flex; flex-direction: column; gap: 16px; }
  .grp { display: flex; flex-direction: column; gap: 2px; }

  .foot {
    margin-top: auto; padding: 10px; border-radius: var(--r-md);
    background: var(--surface); font-size: 11px; color: var(--t500); line-height: 1.55;
  }
  .run { margin-top: 8px; }
  .run-btn { font-size: 12px; padding: 2px 4px; }
</style>
