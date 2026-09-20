<script>
  import SwitchBrandDialog from './SwitchBrandDialog.svelte'
  import { NAV, badgeFor, LANGS } from '../lib/nav.js'
  import { i18n, setLocale, t } from '../lib/i18n/index.svelte.js'
  import { jobs } from '../lib/stores/jobs.svelte.js'
  import { runAction } from '../lib/jobs.svelte.js'
  import { project } from '../lib/stores/project.svelte.js'
  import { route, go } from '../lib/router.svelte.js'

  // 复刻 ui.html:1048-1081 的 renderSide。导航结构与角标逻辑已搬到 lib/nav.js，
  // 语言状态改读 i18n store——切换不再整页 reload。

  let switching = $state(false)

  const brandName = $derived(project.data?.brand?.name || '—')
  const latest = $derived(project.data?.analytics?.latest_date || '—')
</script>

<aside id="side">
  <div class="top">
    <div class="brand-row">
      <div class="brand">Geo<span>Look</span></div>
      <span class="langs">
        {#each LANGS as [l, label] (l)}
          <button class="lang" class:on={i18n.locale === l} onclick={() => setLocale(l)}>{label}</button>
        {/each}
      </span>
    </div>
    <div class="tagline">{t('Generative Engine Optimization')}</div>
  </div>

  <button class="btn btn-secondary pick" onclick={() => (switching = true)}>
    <span class="pick-l">
      <span class="pick-k">当前品牌</span>
      <span class="pick-v">{brandName}</span>
    </span>
    <span class="pick-arrow">切换 ▾</span>
  </button>

  <nav>
    {#each NAV as g (g.key)}
      <div class="grp">
        <div class="navgrp">{t(g.label)}</div>
        {#each g.items as [k, label] (k)}
          <button class="navit" data-route={k} class:on={route.name === k} onclick={() => go(k)}>
            <span class="mark"></span><span>{t(label)}</span><span class="bdg">{badgeFor(project.data, k)}</span>
          </button>
        {/each}
      </div>
    {/each}
  </nav>

  <div class="foot">
    {t('Data updated')} {latest}<br>
    {t('Sampling is manual or schedule-driven')}
    <div class="run">
      {#if jobs.running}
        <span class="spin"></span>{t('A task is running')}
      {:else}
        <button class="btn btn-ghost run-btn" onclick={() => runAction('serve')}>▶ {t('Run full cycle')}</button>
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
