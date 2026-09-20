<script>
  // 取代 ui.html:1359 showMethod —— 「这些数字怎么来的」完整口径说明。
  // 纯展示，无状态。文案与代码同步维护：改判据就要改这里。
  import { t } from '../lib/i18n/index.svelte.js'

  let { onclose } = $props()

  const SECTIONS = [
    {
      head: '1 · How the question bank is generated (onboarding / AI add topics)',
      items: [
        'Only four inputs: <b>brand name, category, target users, one-line definition</b> — all extracted from site copy. Anything it cannot find is marked "to confirm" rather than filled in from general knowledge.',
        'A configured LLM writes the questions from a fixed prompt, in seven groups: <b>recommendation, comparison, alternative, price, risk, brand validation, scenario</b>, 2–4 questions each.',
        'Counts are set per market: 18–24 for CN, 14–20 for global; both markets = 16–20 CN + 12–16 global + 2 shared. Numbering starts at q001 for CN, q101 for global, q901 for shared.',
        'Questions must read like real speech: CN questions as a person would actually type them; global questions are <b>native English phrasing</b>, not translations of the Chinese ones.',
        '<b>Key discipline: almost no question names the brand</b> — the test is whether AI thinks of you unprompted. Only the "brand validation" group names it; those carry a name-check tag, count as brand awareness, and are excluded from mention rate.',
        'After generation the bank is de-duplicated and checked for group and market labels. It stays hand-editable at any time; changes take effect on the next sampling run.',
        'Topic mining: using brand / competitor / category as roots, it pulls real autocomplete terms from Baidu (CN) and Google (global), sorts them into the seven groups and rephrases them as questions. It only produces candidates — adding them is a manual tick. Each round is diffed against the last; first-seen terms are marked "rising demand" and affect topic ordering but not any metric.',
      ],
    },
    {
      head: '2 · How sampling runs',
      items: [
        'Each round asks every question against every engine, and stores <b>the full raw answer</b> — the sample replay under Engines is that text.',
        'Market routing: Chinese questions go only to CN engines, English only to global engines, shared questions to both. The two markets are computed separately, each against its own denominator.',
        'Engines fall into three kinds: networked API (answers carry real citation sources), non-networked API (measures brand awareness inside the model\'s parametric knowledge), and no public API (manual sampling sheet). Each row is labeled.',
        'Every sample records API latency; the engine table shows the median (robust to long tails) so sampling cost stays visible.',
        '<b>Stability</b>: a single AI answer is inherently random, so no metric ever reads one sample — they are aggregate ratios over dozens of questions × several engines. The model version is pinned per engine (visible and editable in Settings); the sampling command supports <code>--repeat</code> for extra rounds. Cross-round comparison follows attribution discipline: a single round of movement counts as an observation, and only two consecutive rounds in the same direction count as a trend.',
      ],
    },
    {
      head: '3 · Metric definitions (every column under Engines)',
      items: [
        '<b>Mention rate</b> = share of unprompted samples whose answer mentions the brand (aliases included). Samples where the question named the brand are removed — including them would guarantee 100%, a false positive. Missing aliases undercount it; add them under Settings → edit brand config.',
        '<b>Rank</b> = median position of the brand relative to other candidate brands in the answer; smaller is earlier.',
        '<b>Cite share</b> = share of all cited domain instances in the answers that belong to your own domain (subdomains included). Non-networked engines usually have no citations and show —.',
        '<b>Verdict</b> rules: 0% → invisible; strictly above every engine in the same market → leading; ≥5% → present but unstable; &lt;5% → occasional. Citing your domain is called out separately. No verdict when samples are insufficient or comparison is impossible.',
        '<b>GEO health score</b> = mention ×30 + cite share ×25 + channel coverage ×20 + content readiness ×15 + fact consistency ×10. Untested components are not scored as zero — the weights are re-normalized, so "not measured yet" is not punished.',
        '<b>Diagnosis</b> (question bank / gap diagnosis) follows a fixed priority: <b>suspected negative</b> (negative cue words near the brand; needs human review) &gt; <b>rival-dominated</b> (you at 0% while some rival is ≥50%) &gt; <b>absent</b> (0%) &gt; <b>ranked low</b> (median rank &gt;3) &gt; normal. Hover a tag to see the basis.',
        '<b>Suspected negative</b> is only a cue word (avoid / not recommended / complaint / scam and the like) landing within roughly a hundred characters of the brand name. It is never auto-concluded — the call is made by a human in the sample replay. A false positive is cheaper than a miss.',
        '<b>Brand mention distribution / strongest rival engine</b>: counts you and the configured competitors (aliases merged) appearing in answers, over the unprompted sample count for that scope; repeated mentions in one sample count once. <b>Unconfigured brands are excluded</b> — the fuller the competitor list and aliases, the truer the distribution.',
      ],
    },
  ]
</script>

<div class="modal" role="presentation">
  <div class="box wide">
    <h4>{t('Where these numbers come from — generation rules and metric definitions')}</h4>
    <p class="muted intro">
      {t('Every metric on this board comes from batch sampling of question bank × engines. The rules are fixed and reproducible; here is the full accounting.')}
    </p>

    {#each SECTIONS as s (s.head)}
      <div class="sec-h">{t(s.head)}</div>
      <ul class="sec-list">
        {#each s.items as item (item)}
          <li>{@html t(item)}</li>
        {/each}
      </ul>
    {/each}

    <p class="muted foot">
      {t('The rules live in scripts/bootstrap.py (question generation), expand.py (topic mining), sample.py (sampling and judgment) and analytics.py (metrics). This dialog is maintained alongside them.')}
    </p>

    <div class="row actions">
      <button class="btn btn-primary" onclick={() => onclose?.()}>{t('Got it')}</button>
    </div>
  </div>
</div>

<style>
  .box.wide { max-width: 760px; }
  .intro { font-size: 12.5px; margin-top: 4px; }
  .sec-h { font-size: 14px; font-weight: 500; margin: 18px 0 4px; color: var(--a300); }
  .sec-list { font-size: 12.5px; color: var(--t400); padding-left: 18px; margin: 0; }
  .sec-list li { margin: 5px 0; line-height: 1.6; }
  .foot { font-size: 11.5px; margin-top: 10px; }
  .actions { justify-content: flex-end; margin-top: 12px; }
</style>
