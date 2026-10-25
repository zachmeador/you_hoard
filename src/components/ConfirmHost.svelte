<script>
  import { confirmState } from '../lib/confirm.svelte.js'
  import ConfirmDialog from './ConfirmDialog.svelte'
</script>

{#if confirmState.current}
  {#key confirmState.current}
    <ConfirmDialog request={confirmState.current} />
  {/key}
{/if}
