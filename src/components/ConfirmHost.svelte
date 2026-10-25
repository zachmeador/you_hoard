<script>
  import { confirmState } from '../lib/confirm.svelte.js'
  import Dialog from './Dialog.svelte'

  /** @type {{ close: () => void } | undefined} */
  let dialog = $state()
  let answered = false

  /** @param {boolean} ok */
  function answer(ok) {
    confirmState.current?.resolve(ok)
    answered = true
    dialog?.close()
  }

  function closed() {
    if (!answered) confirmState.current?.resolve(false)
    answered = false
    confirmState.current = null
  }
</script>

{#if confirmState.current}
  {@const request = confirmState.current}
  <Dialog title={request.title} narrow bind:this={dialog} onclose={closed}>
    <p class="p">{request.message}</p>
    <div class="foot">
      <button type="button" class="btn quiet" data-autofocus onclick={() => answer(false)}>Cancel</button>
      <button type="button" class="btn {request.danger ? 'danger' : 'primary'}" onclick={() => answer(true)}>
        {request.confirmLabel}
      </button>
    </div>
  </Dialog>
{/if}
