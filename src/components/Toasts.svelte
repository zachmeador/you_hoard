<script>
  import { fly } from 'svelte/transition'
  import { dismiss, toasts } from '../lib/toasts.svelte.js'
  import Icon from './Icon.svelte'

  /** @type {HTMLDivElement | undefined} */
  let region = $state()
  let shown = 0

  // The region is a manual popover so it can sit above modal dialogs in the top layer.
  // Re-showing it moves it back on top when a toast arrives while a dialog is open.
  $effect(() => {
    const count = toasts.length
    if (!region) return
    const added = count > shown
    shown = count
    const open = region.matches(':popover-open')
    if (open && added && document.querySelector('dialog[open]')) region.hidePopover()
    if (!region.matches(':popover-open')) region.showPopover()
  })
</script>

<div bind:this={region} popover="manual" class="toasts" aria-live="polite">
  {#each toasts as toast (toast.id)}
    <div
      class="toast"
      class:error={toast.kind === 'error'}
      role={toast.kind === 'error' ? 'alert' : 'status'}
      transition:fly={{ y: 8, duration: 160 }}
    >
      <span class="msg">{toast.message}</span>
      {#if toast.kind === 'error'}
        <button type="button" class="dismiss" aria-label="Dismiss notification" onclick={() => dismiss(toast.id)}>
          <Icon name="x" />
        </button>
      {/if}
    </div>
  {/each}
</div>
