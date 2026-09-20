<script>
  // 取代 ui.html:193 的 head()。旧版把 kicker/title/sub 当 HTML 字符串拼接，
  // 这里走文本插值，自动转义；需要富文本的地方由调用方单独处理。
  let { kicker, title, sub = '' } = $props()
</script>

<div class="kicker">{kicker}</div>
<h3 class="ph-title">{title}</h3>
{#if sub}<p class="soft ph-sub">{sub}</p>{/if}

<style>
  .ph-title { margin-bottom: 6px; }
  .ph-sub { font-size: 14px; max-width: 700px; text-wrap: pretty; }
</style>
