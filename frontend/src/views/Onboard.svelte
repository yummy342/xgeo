<script>
  import { api } from '../lib/api.js'
  import { go } from '../lib/router.svelte.js'
  import { project } from '../lib/stores/project.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { ui } from '../lib/stores/ui.svelte.js'

  // 迁自 ui.html:2585 vOnboard。
  //
  // 这个视图的逻辑基本都在 legacy 里（obCreate / obRetry），它们读写 ST.ob*
  // 和 KEYS。ob* 是接入引导的跨步骤状态，本来就该留在 ui store，所以这里
  // 只负责渲染 + 按 id 暴露表单元素（obCreate 用 $('#ob-url') 取值）。

  let keys = $state([])

  $effect(() => {
    api('/api/keys').then((r) => {
      keys = Array.isArray(r) ? r : []
      window.KEYS = keys
    })
  })

  const step = $derived(ui.obStep || 1)
  const okCn = $derived(keys.filter((k) => k.ok === true && k.market === 'cn').length)
  const okGl = $derived(keys.filter((k) => k.ok === true && k.market === 'global').length)
  const noKey = $derived(!(okCn + okGl))

  const TITLES = ['', 'Who you are and what you do', 'Generating the first diagnosis', 'Finished']
  const SUBS = [
    '',
    'Just a domain. Competitors and the question bank are derived from your site content, and can be changed later.',
    'The first full run takes roughly 10–30 minutes depending on sampling size.',
    'The foundation is ready.',
  ]
</script>

<div class="ob-wrap">
  <div class="ob-inner">
    <div class="kicker">{t('ONBOARDING · step {s} of 3').replace('{s}', String(step))}</div>
    <h3 class="ob-title">{t(TITLES[step] || '')}</h3>
    <p class="soft ob-sub">{t(SUBS[step] || '')}</p>

    <div class="ob-bars">
      {#each [1, 2, 3] as i (i)}
        <span class="ob-bar" class:on={step >= i}></span>
      {/each}
    </div>

    {#if step === 1}
      <div class="ob-body">
        {#if noKey}
          <div class="card warn">
            <div class="warn-t">{t('⚠ No engine API key configured yet')}</div>
            <div class="warn-b">
              {t('The automatic path ("answer sampling" and "AI-derive question bank / brand facts") needs at least one engine key (DeepSeek or Zhipu GLM is the easiest start). You can create without one — but it will only crawl and audit the site, and the question bank and brand facts will have to be filled in by hand.')}
            </div>
            <div class="row warn-actions">
              <button class="btn btn-secondary sm" onclick={() => go('settings')}>{t('Configure keys →')}</button>
              <span class="muted warn-note">{t('Come back here when done')}</span>
            </div>
          </div>
        {:else}
          <div class="muted keys-note">
            {t('Engines configured: {c} CN · {g} global (change them under Settings)').replace('{c}', String(okCn)).replace('{g}', String(okGl))}
            {#if ui.obMkt !== 'global' && !okCn}{t('— note: no usable key for the CN market')}{/if}
            {#if ui.obMkt !== 'cn' && !okGl}{t('— note: no usable key for the global market')}{/if}
          </div>
        {/if}

        <div class="field">
          <label>{t('Site domain *')}</label>
          <input id="ob-url" class="input" placeholder="https://example.com" value={ui.obUrl || ''}>
        </div>
        <div class="field">
          <label>{t('Brand name (leave blank to detect from the page)')}</label>
          <input id="ob-name" class="input" value={ui.obName || ''}>
        </div>
        <div class="field">
          <label>{t('Target market')}</label>
          <div class="seg">
            {#each [['cn', t('CN engines')], ['global', t('Global engines')], ['both', t('Both')]] as [m, l] (m)}
              <label class="seg-opt"><input type="radio" name="obm" value={m} checked={(ui.obMkt || 'both') === m}>{l}</label>
            {/each}
          </div>
        </div>
        <label class="row nosample">
          <input type="checkbox" id="ob-nosample" checked={ui.obNoSample}>{t('Skip sampling for the first round (saves time, can be added later)')}
        </label>
        <div class="row ob-actions">
          <button class="btn btn-primary" onclick={() => window.obCreate()}>{t('Create and start the automatic run')}</button>
          <button class="btn btn-ghost" onclick={() => go('settings')}>{t('Back to Settings')}</button>
        </div>
      </div>

    {:else if step === 2}
      <div class="ob-body">
        <div id="jobstat" class="ob-status">
          {#if ui.obFail}
            {t('✗ The first run did not finish (failed, stopped, or interrupted). Log below; you can retry.')}
          {:else}
            <span class="spin"></span>{t('Crawling the site, deriving brand facts / competitors / question bank, sampling, and generating deliverables…')}
          {/if}
        </div>
        <pre class="log" id="joblog"></pre>
        {#if ui.obFail}
          <div class="row">
            <button class="btn btn-primary" onclick={() => window.obRetry()}>{t('Retry')}</button>
            <button class="btn btn-ghost" onclick={() => go('settings')}>{t('Run it manually under Settings')}</button>
          </div>
        {:else}
          <div class="muted ob-note">
            {t('Derivation only extracts from your site text; anything it cannot find is marked "to confirm" rather than filled in from general knowledge. Check the question bank and brand facts once it finishes. No need to wait on this page.')}
          </div>
        {/if}
      </div>

    {:else}
      <div class="ob-body">
        <div class="ob-done">{t('✓ First round complete. The three deliverables are generated and metrics are live.')}</div>
        <div class="muted ob-note">
          {t('Next: check the entries marked "to confirm" in Brand Facts, skim how the questions are phrased, then work through the Action Plan.')}
        </div>
        <div class="row">
          <button class="btn btn-primary" onclick={() => go('overview')}>{t('Go to Overview →')}</button>
          <button class="btn btn-secondary" onclick={() => go('facts')}>{t('Check facts first')}</button>
        </div>
      </div>
    {/if}
  </div>
</div>

<style>
  .ob-wrap { padding: 44px; display: flex; justify-content: center; }
  .ob-inner { width: 100%; max-width: 720px; }
  .ob-title { margin-bottom: 6px; }
  .ob-sub { font-size: 13.5px; }
  .ob-bars { display: flex; gap: 6px; margin: 20px 0 26px; }
  .ob-bar { flex: 1; height: 3px; border-radius: 2px; background: #3f424d; }
  .ob-bar.on { background: var(--accent); }

  .ob-body { display: flex; flex-direction: column; gap: 14px; }
  .warn { box-shadow: 0 0 0 1px var(--a700); padding: 14px 16px; gap: 6px; }
  .warn-t { font-size: 13.5px; font-weight: 500; }
  .warn-b { font-size: 12.5px; color: var(--t400); line-height: 1.6; }
  .warn-actions { margin-top: 4px; }
  .warn-note { font-size: 11.5px; }
  .keys-note { font-size: 12px; }
  .nosample { gap: 6px; font-size: 13px; }
  .nosample input { width: auto; }
  .ob-actions { margin-top: 10px; }
  .sm { font-size: 12.5px; }

  .ob-status { font-size: 13px; }
  .ob-note { font-size: 12px; }
  .ob-done { font-size: 14px; }

  @media (max-width: 640px) {
    .ob-wrap { padding: 20px 16px; }
  }
</style>
