<script>
  // 取代 ui.html:193 的 head()。旧版把 kicker/title/sub 当 HTML 字符串拼接。
  //
  // sub 走 {@html}：有几条文案本身带 <b>（发布页的「发布永远手动」就是这么写的）。
  // 调用方传进来的都是写死的文案，或服务端返回的数值，没有用户可控字符串——
  // 将来若有，必须先转义再传。
  let { kicker, title, sub = '' } = $props()
</script>

<div class="kicker">{kicker}</div>
<h3 class="ph-title">{title}</h3>
{#if sub}<p class="soft ph-sub">{@html sub}</p>{/if}

<style>
  .ph-title { margin-bottom: 6px; }
  .ph-sub { font-size: 14px; max-width: 700px; text-wrap: pretty; }
</style>
