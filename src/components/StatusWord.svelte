<script>
  /** @import { JobState, VideoStatus } from '../lib/types' */
  import { percent, whenShort } from '../lib/format.js'
  import { queue } from '../lib/queue.svelte.js'
  import { videoState } from '../lib/status.js'
  import { clock } from '../lib/ui.svelte.js'

  /** @type {{ status: VideoStatus, videoId?: number | null, job?: JobState | null, bar?: boolean }} */
  let { status, videoId = null, job = null, bar = false } = $props()

  const phase = $derived(videoState({ status, job }, videoId == null ? undefined : queue.jobFor(videoId), clock.now))
</script>

{#if phase.key === 'archived'}
  <span class="st archived">Archived</span>
{:else if phase.key === 'downloading'}
  <span class="st downloading">{phase.processing ? 'Processing' : `Downloading ${percent(phase.percent)}`.trim()}</span>
  {#if bar && !phase.processing && phase.percent != null}
    <span class="mini-prog prog" aria-hidden="true"><i style:width="{phase.percent}%"></i></span>
  {/if}
{:else if phase.key === 'waiting'}
  <span class="st waiting" title={phase.why || undefined}>
    {phase.premiere ? 'Premieres' : 'Waiting'} · {whenShort(phase.runAfter, clock.now)}
  </span>
{:else if phase.key === 'queued'}
  <span class="st queued">Queued</span>
{:else if phase.key === 'paused'}
  <span class="st paused">Paused</span>
{:else if phase.key === 'failed'}
  <span class="st failed">Failed</span>
{:else if phase.key === 'deleted'}
  <span class="st deleted">Files removed</span>
{:else}
  <span class="st missing">Not downloaded</span>
{/if}
