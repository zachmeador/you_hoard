<script>
  /** @import { Snippet } from 'svelte' */

  /** @type {{ title: string, onclose: () => void, children: Snippet, size?: 'sm' | 'md' | 'lg' }} */
  let { title, onclose, children, size = 'md' } = $props()

  const id = $props.id()
  /** @type {HTMLDialogElement | undefined} */
  let dialog = $state()
  let pressedBackdrop = false

  $effect(() => {
    if (!dialog || dialog.open) return
    dialog.showModal()
    const preferred = dialog.querySelector('[data-autofocus]')
    if (preferred instanceof HTMLElement) preferred.focus()
  })

  export function close() {
    if (dialog?.open) dialog.close()
  }

  /** @param {PointerEvent} event */
  function onpointerdown(event) {
    pressedBackdrop = event.target === dialog
  }

  /** @param {MouseEvent} event */
  function onclick(event) {
    if (pressedBackdrop && event.target === dialog) close()
    pressedBackdrop = false
  }
</script>

<!-- Backdrop clicks close the dialog; Escape is handled natively by <dialog>. -->
<dialog
  bind:this={dialog}
  class="modal modal-{size}"
  aria-labelledby="{id}-title"
  {onclose}
  {onpointerdown}
  {onclick}
>
  <header class="modal-header">
    <h2 id="{id}-title">{title}</h2>
    <button type="button" class="icon-btn" aria-label="Close" onclick={close}>×</button>
  </header>
  <div class="modal-body">
    {@render children()}
  </div>
</dialog>
