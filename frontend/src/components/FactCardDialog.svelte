<script>
  // 取代 ui.html:1825 的 factModal。
  // 旧版读全局 FACT_CARDS[i]（由 Facts 视图在渲染时同步过去），现在由调用方
  // 直接把卡片对象传进来——不再需要那条隐式的全局同步。
  import { t } from '../lib/i18n/index.svelte.js'

  let { card, onclose, oneditSource, onaddFact } = $props()
</script>

<div class="modal" role="presentation">
  <div class="box">
    <h4>{card.field}</h4>

    <div class="lbl">{t('Official claim (how you want AI to say it)')}</div>
    <div class="val">{card.value}</div>

    <div class="lbl">
      {t('What AI says now')}
      {#if card.ai.state}
        <span class="tag {card.ai.state === '一致' ? 'pill-good' : 'tag-accent'} st">{card.ai.state}</span>
      {:else}
        <span class="tag tag-dim st">{t('Not compared')}</span>
      {/if}
    </div>
    <div class="val soft">{card.ai.txt}</div>

    <p class="muted hint">
      {t('"What AI says now" comes from real answers in Engines → sample replay. Fact consistency only enters the health score once you compare by hand and record it.')}
    </p>

    <div class="row actions">
      <button class="btn btn-ghost edit" onclick={() => { onclose?.(); oneditSource?.() }}>{t('Edit claim (source file)')}</button>
      <button class="btn btn-secondary" onclick={() => onclose?.()}>{t('Close')}</button>
      <button class="btn btn-primary" onclick={() => { onclose?.(); onaddFact?.(card.field) }}>{t('Record a comparison')}</button>
    </div>
  </div>
</div>

<style>
  .lbl { font-size: 12px; color: var(--t600); margin: 10px 0 3px; }
  .val { font-size: 13.5px; line-height: 1.6; }
  .val.soft { color: var(--t400); }
  .st { font-size: 10px; }
  .hint { font-size: 11.5px; margin-top: 10px; }
  .actions { justify-content: flex-end; margin-top: 14px; gap: 9px; }
  .edit { margin-right: auto; }
</style>
