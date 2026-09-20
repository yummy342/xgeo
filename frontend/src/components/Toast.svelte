<script>
  import { toasts, remove } from '../lib/stores/toast.svelte.js'
</script>

{#each toasts as t (t.id)}
  <div class="toast {t.kind}" onclick={() => remove(t.id)} role="status">{t.message}</div>
{/each}
