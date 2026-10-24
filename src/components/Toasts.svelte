<script>
  import { fly } from 'svelte/transition'
  import { dismiss, toasts } from '../lib/toasts.svelte.js'

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
      class="toast toast-{toast.kind}"
      role={toast.kind === 'error' ? 'alert' : 'status'}
      transition:fly={{ x: 32, duration: 180 }}
    >
      <p class="message">{toast.message}</p>
      <button type="button" class="icon-btn" aria-label="Dismiss notification" onclick={() => dismiss(toast.id)}>
        ×
      </button>
    </div>
  {/each}
</div>

<style>
  .toasts {
    position: fixed;
    inset: var(--space-4) var(--space-4) auto auto;
    width: min(380px, calc(100vw - 2rem));
    height: auto;
    margin: 0;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--text-primary);
    overflow: visible;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    pointer-events: none;
  }

  .toast {
    pointer-events: auto;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
    background: var(--surface);
    border: 1px solid var(--border);
    border-left: 4px solid var(--info);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
  }

  .toast-success {
    border-left-color: var(--success);
    box-shadow: var(--shadow), var(--glow-primary);
  }

  .toast-error {
    border-left-color: var(--error);
    box-shadow: var(--shadow), 0 0 10px var(--accent-glow);
  }

  .message {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
  }

  @media (max-width: 640px) {
    .toasts {
      inset: auto var(--space-2) var(--space-2) var(--space-2);
      width: auto;
    }
  }
</style>
