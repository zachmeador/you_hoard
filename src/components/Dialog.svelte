<script>
  /** @import { Snippet } from 'svelte' */
  import Icon from './Icon.svelte'

  /** @type {{ title: string, onclose: () => void, children: Snippet, narrow?: boolean }} */
  let { title, onclose, children, narrow = false } = $props()

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

<dialog bind:this={dialog} class:narrow aria-labelledby="{id}-title" {onclose} {onpointerdown} {onclick}>
  <div class="dlg-h">
    <h2 id="{id}-title">{title}</h2>
    <button type="button" class="btn icon quiet" aria-label="Close" onclick={close}>
      <Icon name="x" />
    </button>
  </div>
  <div class="dlg-b">
    {@render children()}
  </div>
</dialog>
