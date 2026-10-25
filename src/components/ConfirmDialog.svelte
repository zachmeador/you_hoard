<script>
  /** @import { ActiveConfirm } from '../lib/confirm.svelte.js' */
  import { untrack } from 'svelte'
  import { confirmState } from '../lib/confirm.svelte.js'
  import Dialog from './Dialog.svelte'

  /** @type {{ request: ActiveConfirm }} */
  let { request } = $props()

  // A dialog still closing when the next question arrives must not answer or clear the new one.
  const mine = untrack(() => request)
  /** @type {{ close: () => void } | undefined} */
  let dialog = $state()
  let answered = false

  /** @param {boolean} ok */
  function answer(ok) {
    answered = true
    mine.resolve(ok)
    dialog?.close()
  }

  function closed() {
    if (!answered) mine.resolve(false)
    if (confirmState.current === mine) confirmState.current = null
  }
</script>

<Dialog title={mine.title} narrow bind:this={dialog} onclose={closed}>
  <p class="p">{mine.message}</p>
  <div class="foot">
    <button type="button" class="btn quiet" data-autofocus onclick={() => answer(false)}>Cancel</button>
    <button type="button" class="btn {mine.danger ? 'danger' : 'primary'}" onclick={() => answer(true)}>
      {mine.confirmLabel}
    </button>
  </div>
</Dialog>
