<script>
  import { parseClock, textParts } from '../lib/format.js'

  /** @type {{ text: string, duration: number | null, onseek?: (t: number) => void }} */
  let { text, duration, onseek } = $props()

  let open = $state(false)
  const parts = $derived(textParts(text, duration))
  const long = $derived(text.split('\n').length > 7)
</script>

<section class="desc" class:collapsed={long && !open} aria-label="Description">
  <div class="desc-text">{#each parts as part, i (i)}{#if part.kind === 'url'}<a href={part.text} target="_blank" rel="noopener noreferrer">{part.text}</a>{:else if part.kind === 'time' && onseek}<button type="button" class="ts" onclick={() => onseek(part.seconds ?? parseClock(part.text) ?? 0)}>{part.text}</button>{:else}{part.text}{/if}{/each}</div>
  {#if long}
    <button type="button" class="more-btn" aria-expanded={open} onclick={() => (open = !open)}>
      {open ? 'Show less' : 'Show more'}
    </button>
  {/if}
</section>
