<script>
  /** @import { Video } from '../lib/types' */
  import { dur, hm, percent, qualityWithRate } from '../lib/format.js'
  import { queue } from '../lib/queue.svelte.js'
  import { videoState } from '../lib/status.js'
  import { clock } from '../lib/ui.svelte.js'
  import Icon from './Icon.svelte'

  /** @type {{ video: Video, quality?: boolean }} */
  let { video, quality = true } = $props()

  const phase = $derived(videoState(video, queue.jobFor(video.id), clock.now))
  const gone = $derived(video.unavailable)
</script>

{#if phase.key === 'downloading'}
  <span class="cn tl prog">
    {phase.processing ? 'Processing' : `Downloading ${percent(phase.percent)}`.trim()}
  </span>
{:else if phase.key === 'waiting'}
  <span class="cn tl wait">
    <Icon name="clock" />{phase.premiere ? 'Premieres' : 'Waiting'} {hm(phase.runAfter)}
  </span>
{:else if phase.key === 'queued'}
  <span class="cn tl">Queued</span>
{:else if phase.key === 'paused'}
  <span class="cn tl"><Icon name="pause" />Paused</span>
{:else if phase.key === 'failed'}
  {#if gone}
    <span class="cn tl hollow"><i class="lz hollow"></i>Gone · not saved</span>
  {:else}
    <span class="cn tl fail">Failed</span>
  {/if}
{:else if phase.key === 'deleted'}
  <span class="cn tl hollow">Files removed</span>
{:else if phase.key === 'missing'}
  <span class="cn tl hollow">Not downloaded</span>
{:else if gone}
  <span class="cn tl gone"><i class="lz"></i>Gone from YouTube</span>
{/if}
{#if video.video_type === 'short'}
  <span class="cn tr">Short</span>
{:else if video.video_type === 'live'}
  <span class="cn tr">Stream</span>
{/if}
{#if quality && phase.key === 'archived' && video.quality}
  <span class="cn bl">{qualityWithRate(video)}</span>
{/if}
{#if video.duration}
  <span class="cn br">{dur(video.duration)}</span>
{/if}
