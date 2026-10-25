<script>
  /** @import { Video } from '../lib/types' */
  import { queue } from '../lib/queue.svelte.js'
  import { videoState } from '../lib/status.js'
  import { clock } from '../lib/ui.svelte.js'

  /** @type {{ video: Video }} */
  let { video } = $props()

  const phase = $derived(videoState(video, queue.jobFor(video.id), clock.now))
</script>

{#if phase.key === 'downloading'}
  {#if phase.processing}
    <span class="bar ind"><i></i></span>
  {:else}
    <span class="bar"><i style:width="{phase.percent ?? 0}%"></i></span>
  {/if}
{:else if video.watched_at}
  <span class="bar seen"><i></i></span>
{/if}
