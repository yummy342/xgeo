<script>
  import { modalState, closeModal } from '../lib/stores/modal.svelte.js'

  // 点背景关闭，复刻 ui.html:182 的 onclick="if(event.target===this)closeModal()"
  function onBackdrop(e) {
    if (e.target === e.currentTarget) closeModal()
  }
</script>

{#if modalState.html}
  <div class="modal" onclick={onBackdrop}>
    <div class="box">{@html modalState.html}</div>
  </div>
{/if}
