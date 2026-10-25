<script>
  /** @import { Snippet } from 'svelte' */
  import Icon from './Icon.svelte'

  /** @type {{ label: string, children: Snippet<[() => void]> }} */
  let { label, children } = $props()

  let open = $state(false)
  /** @type {HTMLSpanElement | undefined} */
  let wrap = $state()

  function close() {
    open = false
  }

  /** @param {MouseEvent} event */
  function onwindowclick(event) {
    if (open && wrap && event.target instanceof Node && !wrap.contains(event.target)) close()
  }

  /** @param {KeyboardEvent} event */
  function onwindowkeydown(event) {
    if (!open || !wrap) return
    if (event.key === 'Escape') {
      close()
      wrap.querySelector('button')?.focus()
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      const items = [...wrap.querySelectorAll('.menu button, .menu a')].filter(
        (el) => el instanceof HTMLElement
      )
      if (!items.length) return
      event.preventDefault()
      const at = items.indexOf(/** @type {HTMLElement} */ (document.activeElement))
      const next = event.key === 'ArrowDown' ? at + 1 : at - 1
      items[(next + items.length) % items.length].focus()
    }
  }
</script>

<svelte:window onclick={onwindowclick} onkeydown={onwindowkeydown} />

<span class="menu-wrap" bind:this={wrap}>
  <button
    type="button"
    class="btn icon sm quiet"
    aria-haspopup="menu"
    aria-expanded={open}
    aria-label={label}
    onclick={() => (open = !open)}
  >
    <Icon name="more" />
  </button>
  {#if open}
    <div class="menu open" role="menu" aria-label={label}>
      {@render children(close)}
    </div>
  {/if}
</span>
