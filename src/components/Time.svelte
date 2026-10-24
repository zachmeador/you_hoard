<script>
  import { dateTime, relative } from '../lib/format.js'
  import { clock } from '../lib/ui.svelte.js'

  /** @type {{ value: string | null | undefined, absolute?: boolean }} */
  let { value, absolute = false } = $props()
</script>

{#if value}<time datetime={value} title={dateTime(value)}>{absolute ? dateTime(value) : relative(value, Math.max(clock.now, Date.now()))}</time
  >{:else}—{/if}
