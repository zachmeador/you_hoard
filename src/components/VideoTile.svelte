<script>
  /** @import { Video } from '../lib/types' */
  import { dmy, dshort } from '../lib/format.js'
  import { queue } from '../lib/queue.svelte.js'
  import { href } from '../lib/router.svelte.js'
  import { videoState } from '../lib/status.js'
  import { clock } from '../lib/ui.svelte.js'
  import Corners from './Corners.svelte'
  import Icon from './Icon.svelte'
  import Thumb from './Thumb.svelte'
  import ThumbBar from './ThumbBar.svelte'

  /** @type {{ video: Video }} */
  let { video } = $props()

  const phase = $derived(videoState(video, queue.jobFor(video.id), clock.now))
  const target = $derived(href(`/video/${video.id}`))
</script>

<article
  class="tile s-{phase.key === 'waiting' ? 'queued' : phase.key}"
  class:is-watched={!!video.watched_at}
  class:is-gone={video.unavailable && video.status === 'archived'}
>
  <a class="thumb" class:vert={video.video_type === 'short'} href={target} tabindex="-1" aria-hidden="true">
    <Thumb src={video.thumbnail_url} />
    <Corners {video} />
    <ThumbBar {video} />
  </a>
  <h3 class="t-title"><a href={target}>{video.title}</a></h3>
  <p class="t-meta">
    {#if video.channel}
      <a class="ch" href={href('/library', { channel: video.channel.id })}>{video.channel.name}</a>
    {:else}
      <span class="ch">Unknown channel</span>
    {/if}
    <span class="sep">·</span><span class="nowrap">{dshort(video.published_at, clock.now)}</span>
    {#if video.watched_at}
      <span class="seen" title="Watched {dmy(video.watched_at)}">
        <Icon name="check" /><span class="sr">Watched</span>
      </span>
    {/if}
  </p>
  {#if phase.key === 'failed' && video.error}
    <p class="t-err">{video.error}</p>
  {:else if phase.why}
    <p class="t-note">{phase.why}</p>
  {/if}
</article>
