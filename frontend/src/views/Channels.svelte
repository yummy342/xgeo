<script>
  // 迁自 ui.html:1692 vChannels。阵地的适配题数依赖 chanFitQs，它和
  // distOf 都还在 legacy 里（读的是全局 D），这里直接复用不做重复实现。
  import { project } from '../lib/stores/project.svelte.js'
  import { ui } from '../lib/stores/ui.svelte.js'
  import { t } from '../lib/i18n/index.svelte.js'
  import { esc, pct } from '../lib/format.js'
  import PageHead from '../components/PageHead.svelte'

  const bp = $derived(project.data?.blueprint)
  const chs = $derived(bp?.channels || [])
  const cov = $derived(bp?.coverage || {})
  const roadmap = $derived(bp?.roadmap || [])

  const TIERS = [
    ['P0', 'Foundation · skip this and the rest is wasted'],
    ['P1', 'Amplify · do it right after the foundation'],
    ['P2', 'Optional · once there is spare capacity'],
  ]

  // 从「差距诊断 · 建设方案」跳来时（设了 ST.chanSel）滚动定位并打开详情。
  // 旧代码把这段副作用写在渲染函数体内，每次重渲染都会重跑；这里收进 $effect。
  let handled = null
  $effect(() => {
    const sel = ui.chanSel
    if (!sel || sel === handled) return
    handled = sel
    setTimeout(() => {
      const el = document.querySelector(`[data-chan="${CSS.escape(sel)}"]`)
      if (el) {
        el.scrollIntoView({ block: 'center' })
        el.style.boxShadow = '0 0 0 2px var(--accent)'
        setTimeout(() => { el.style.boxShadow = 'var(--sh-sm)' }, 2600)
      }
      window.chanOpen(sel)
    }, 60)
    ui.chanSel = null
  })

  function coverPct() {
    return pct(cov.channel_covered / Math.max(1, cov.channel_total))
  }
</script>

{#if !bp}
  <div class="page">
    <PageHead
      kicker={t('DIAGNOSIS · CHANNEL MAP')}
      title={t('No build blueprint yet')}
      sub={t('Run "Generate build blueprint" under Settings → Run tasks.')}
    />
  </div>
{:else}
  <div class="page">
    <PageHead
      kicker={t('DIAGNOSIS · CHANNEL MAP')}
      title={t('Where to build, what to build there, and how much')}
      sub={t('A "channel" is a site AI can cite. Each one is weighted by its share of 187,818 real citations in CN-GEO — not a guess. ✓ marks channels already cited in this round\'s samples.')}
    />

    <div class="row coverage">
      <span class="bar cov-bar"><span style="width:{(cov.channel_covered / Math.max(1, cov.channel_total) * 100).toFixed(0)}%"></span></span>
      <span class="cov-num">{t('Channel coverage')} {cov.channel_covered} / {cov.channel_total} · {coverPct()}</span>
    </div>

    {#each TIERS as [tier, label] (tier)}
      {@const items = chs.filter((c) => c.priority === tier)}
      {#if items.length}
        <div class="tier">
          <div class="row tier-head">
            <span class="tag {tier === 'P0' ? 'tag-accent' : tier === 'P1' ? 'tag-neutral' : 'tag-dim'}">{tier}</span>
            <span class="tier-label">{t(label)}</span>
            <span class="tier-count">{t('Covered')} {items.filter((c) => c.covered).length} / {items.length}</span>
          </div>
          {#each items as c (c.name)}
            <div class="chan" data-chan={c.name} title={t('Click for build details')} onclick={() => window.chanOpen(c.name)}>
              <div class="row">
                <span class="dot" style="background:{c.covered ? 'var(--a400)' : '#595d6c'}"></span>
                <span class="chan-name">{c.name}</span>
                <span class="tag tag-outline">{c.kind}</span>
                <span class="chan-meta">
                  {c.national ? t('Citations') + ' ' + c.national.toLocaleString() : ''}{c.position ? ` · ${t('avg. position')} ${c.position}` : ''}{c.platforms ? ` · ${c.platforms} ${t('surfaces')}` : ''}
                </span>
                {#if (c.fits || []).length}
                  {@const qs = window.chanFitQs(c)}
                  {@const dn = qs.filter((q) => window.distOf(q.id, c.id)).length}
                  <span class="tag {dn ? 'tag-outline' : 'tag-dim'} fits" title={t('Fits {groups} questions').replace('{groups}', (c.fits || []).join('/'))}>
                    {t('fits')} {qs.length} · {t('planted')} {dn}
                  </span>
                {/if}
                <span class="tag {c.covered ? 'pill-good' : 'tag-accent'} chan-state">
                  {c.covered ? t('✓ cited') : t('Not built')}
                </span>
              </div>
              <div class="chan-why">{@html esc(c.why).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')}</div>
              <div class="spec chan-spec">
                <div><div class="k">{t('What')}</div><div class="v">{esc((c.forms || []).join(' / '))}</div></div>
                <div><div class="k">{t('How much')}</div><div class="v">{c.volume}</div></div>
                <div><div class="k">{t('Cadence')}</div><div class="v">{c.cadence}</div></div>
                <div><div class="k">{t('Who')}</div><div class="v">{c.owner}</div></div>
              </div>
            </div>
          {/each}
        </div>
      {/if}
    {/each}

    {#if roadmap.length}
      <h4 class="roadmap-h">{t('Build cadence in phases')}</h4>
      <div class="roadmap">
        {#each roadmap as r (r.window)}
          <div class="card elev roadmap-card">
            <div class="roadmap-t">{r.window} · {r.focus}</div>
            <ul class="roadmap-ul">
              {#each r.items as i (i)}
                <li>{i}</li>
              {/each}
            </ul>
          </div>
        {/each}
      </div>
    {/if}
  </div>
{/if}

<style>
  .coverage { gap: 14px; margin: 22px 0 18px; }
  .cov-bar { flex: 1; height: 8px; }
  .cov-num { font-size: 12.5px; color: var(--t400); flex: none; }
  .tier { margin-bottom: 26px; }
  .tier-head { margin-bottom: 10px; }
  .tier-label { font-size: 14px; font-weight: 500; }
  .tier-count { font-size: 12px; color: var(--t600); }
  .chan {
    padding: 14px 16px; border-radius: var(--r-md); background: var(--surface);
    box-shadow: var(--sh-sm); margin-bottom: 8px; cursor: pointer;
  }
  .chan-name { font-size: 15px; font-weight: 500; }
  .chan-meta { font-size: 11.5px; color: var(--t600); }
  .fits { font-size: 10.5px; }
  .chan-state { margin-left: auto; }
  .chan-why { font-size: 12.5px; color: var(--t400); margin-top: 7px; line-height: 1.5; }
  .chan-spec { margin-top: 11px; }
  .roadmap-h { font-size: 16px; margin: 8px 0 10px; }
  .roadmap { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
  .roadmap-card { padding: 14px 16px; gap: 4px; }
  .roadmap-t { font-size: 13px; font-weight: 500; }
  .roadmap-ul { margin: 4px 0 0; padding-left: 17px; font-size: 12.5px; color: var(--t400); line-height: 1.75; }
</style>
