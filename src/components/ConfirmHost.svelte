<script>
  import { confirmState } from '../lib/confirm.svelte.js'
  import Modal from './Modal.svelte'

  /** @type {{ close: () => void } | undefined} */
  let modal = $state()
  let answered = false

  /** @param {boolean} ok */
  function answer(ok) {
    confirmState.current?.resolve(ok)
    answered = true
    modal?.close()
  }

  function closed() {
    if (!answered) confirmState.current?.resolve(false)
    answered = false
    confirmState.current = null
  }
</script>

{#if confirmState.current}
  {@const request = confirmState.current}
  <Modal title={request.title} size="sm" bind:this={modal} onclose={closed}>
    <div class="stack">
      <p>{request.message}</p>
      <div class="form-actions">
        <button type="button" class="btn btn-secondary" data-autofocus onclick={() => answer(false)}>
          Cancel
        </button>
        <button
          type="button"
          class="btn {request.danger ? 'btn-danger' : 'btn-primary'}"
          onclick={() => answer(true)}
        >
          {request.confirmLabel}
        </button>
      </div>
    </div>
  </Modal>
{/if}
