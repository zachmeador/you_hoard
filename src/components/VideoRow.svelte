<script>
  /** @import { Video } from '../lib/types' */
  import { bytes, dmy, dur, isoDate, qualityWithRate, KIND_WORDS } from '../lib/format.js'
  import { queue } from '../lib/queue.svelte.js'
  import { href } from '../lib/router.svelte.js'
  import { videoState } from '../lib/status.js'
  import { clock } from '../lib/ui.svelte.js'
  import Icon from './Icon.svelte'
  import StatusWord from './StatusWord.svelte'
  import Thumb from './Thumb.svelte'
  import ThumbBar from './ThumbBar.svelte'

  /** @type {{ video: Video }} */
  let { video } = $props()

  const phase = $derived(videoState(video, queue.jobFor(video.id), clock.now))
  const target = $derived(href(`/video/${video.id}`))
  const kind = $derived(video.video_type === 'video' ? '' : KIND_WORDS[video.video_type])
  const archived = $derived(video.status === 'archived')
  const file = $derived(archived && video.quality ? `${qualityWithRate(video)} · ${bytes(video.media_size)}` : '')
</script>

<tr class="s-{phase.key}" class:is-watched={!!video.watched_at}>
  <td class="c-th keep">
    <a class="mini" class:vert={video.video_type === 'short'} href={target} tabindex="-1" aria-hidden="true">
      <Thumb src={video.thumbnail_url} />
      <ThumbBar {video} />
    </a>
  </td>
  <td class="c-main keep">
    <a class="ttl" href={target}>
      {#if video.unavailable}<i class="lz" title="Gone from YouTube"></i>{/if}{video.title}
    </a>
    <div class="row-sub">
      {#if video.channel}
        <a href={href('/library', { channel: video.channel.id })}>{video.channel.name}</a>
      {:else}
        <span>Unknown channel</span>
      {/if}
      {#if kind}<span class="kindtag">{kind}</span>{/if}
      {#if video.unavailable && archived}
        <span class="gilt-note"><i class="lz"></i>Gone from YouTube since {dmy(video.unavailable_at)}</span>
      {/if}
    </div>
    {#if phase.key === 'failed' && video.error}
      <div class="row-err" title={video.error}>{video.error}</div>
    {/if}
    <div class="m-meta">
      {dmy(video.published_at)}{video.duration ? ` · ${dur(video.duration)}` : ''}<br />
      <StatusWord status={video.status} videoId={video.id} job={video.job} />
      {#if file}<span class="sep">·</span> {file}{/if}
      {#if video.watched_at}<span class="sep">·</span> watched{/if}
    </div>
  </td>
  <td class="num c-pub">{isoDate(video.published_at)}</td>
  <td class="num c-len">{video.duration ? dur(video.duration) : '—'}</td>
  <td class="c-st"><StatusWord status={video.status} videoId={video.id} job={video.job} bar /></td>
  <td class="num c-file">{file || '—'}</td>
  <td class="num c-arch">{video.archived_at ? isoDate(video.archived_at) : '—'}</td>
  <td class="c-seen">
    {#if video.watched_at}
      <span title="Watched {dmy(video.watched_at)}"><Icon name="check" /><span class="sr">Watched</span></span>
    {/if}
  </td>
</tr>
