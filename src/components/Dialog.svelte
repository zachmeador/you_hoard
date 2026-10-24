<script>
  export let show = false
  export let label
  export let width = 500
  export let busy = false
  let dialog

  $: if (dialog) {
    if (show && !dialog.open) dialog.showModal()
    else if (!show && dialog.open) dialog.close()
  }
</script>

<dialog bind:this={dialog} aria-label={label} style="--dialog-width: {width}px"
  on:cancel={event => { if (busy) event.preventDefault() }} on:close={() => show = false}>
  <slot />
</dialog>

<style>
  dialog {
    padding: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    color: var(--text-primary);
    margin: auto;
    width: min(95vw, var(--dialog-width));
    max-width: 95vw;
    max-height: 90vh;
  }
  dialog::backdrop { background: rgba(0, 0, 0, 0.8); }
  dialog :global(.modal-content) { margin: 0; width: 100%; max-width: none; max-height: none; border: 0; }
</style>
