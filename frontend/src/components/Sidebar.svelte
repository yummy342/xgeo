<script>
  import SwitchBrandDialog from './SwitchBrandDialog.svelte'
  import { NAV, badgeFor, LANGS } from '../lib/nav.js'
  import { i18n, setLocale, t } from '../lib/i18n/index.svelte.js'
  import { api } from '../lib/api.js'
  import { jobs } from '../lib/stores/jobs.svelte.js'
  import { runAction } from '../lib/jobs.svelte.js'
  import { project } from '../lib/stores/project.svelte.js'
  import { route, go } from '../lib/router.svelte.js'

  // 复刻 ui.html:1048-1081 的 renderSide。导航结构与角标逻辑已搬到 lib/nav.js，
  // 语言状态改读 i18n store——切换不再整页 reload。

  let switching = $state(false)
  let me = $state(null)

  // 只有账号档答得上「你是谁」：令牌档服务端只知道一个令牌，默认档（本机无凭据）
  // 压根没有账号。查不到就整块不渲染，不留空位。
  $effect(() => {
    let cancelled = false
    api('/api/auth/me').then((r) => {
      if (!cancelled && r && !r.error) me = r
    })
    return () => { cancelled = true }
  })

  const account = $derived(me && me.mode === 'account' ? me : null)

  async function signOut() {
    await api('/api/auth/logout', { method: 'POST' })
    // 会话在服务端的进程里，刷新之后这个请求就是 401，浏览器落到登录页
    location.reload()
  }

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
      <span class="pick-k">{t('Current brand')}</span>
      <span class="pick-v">{brandName}</span>
    </span>
    <span class="pick-arrow">{t('Switch')} ▾</span>
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
    {#if account}
      <div class="who">
        <span class="mail" title={account.email}>{account.email}</span>
        <button class="btn btn-ghost out" onclick={signOut}>{t('Sign out')}</button>
      </div>
    {/if}
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

  .who {
    display: flex; align-items: center; gap: 6px; justify-content: space-between;
    padding-bottom: 8px; margin-bottom: 8px; border-bottom: 1px solid var(--line);
  }
  .mail {
    font-size: 11px; color: var(--t400);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .out { font-size: 11px; padding: 2px 6px; flex: none; }
</style>
