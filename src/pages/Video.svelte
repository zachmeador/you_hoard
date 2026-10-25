<script>
  /** @import { Channel, Subscription, Video, VideoOptions } from '../lib/types' */
  import { untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { confirmAction } from '../lib/confirm.svelte.js'
  import {
    bytes,
    compact,
    dmy,
    dur,
    eta,
    int,
    policyLabel,
    rel,
    speed,
    whenShort,
    percent,
    SUBTITLE_SOURCES
  } from '../lib/format.js'
  import { isRetry } from '../lib/jobs.js'
  import { Loader } from '../lib/loader.svelte.js'
  import { queue } from '../lib/queue.svelte.js'
  import { href } from '../lib/router.svelte.js'
  import { system } from '../lib/system.svelte.js'
  import { videoState } from '../lib/status.js'
  import { notify } from '../lib/toasts.svelte.js'
  import { channelsChanged, clock, ui } from '../lib/ui.svelte.js'
  import Avatar from '../components/Avatar.svelte'
  import Chapters from '../components/Chapters.svelte'
  import ChatReplay from '../components/ChatReplay.svelte'
  import Comments from '../components/Comments.svelte'
  import Description from '../components/Description.svelte'
  import DownloadControls from '../components/DownloadControls.svelte'
  import FileTree from '../components/FileTree.svelte'
  import FilterTabs from '../components/FilterTabs.svelte'
  import Icon from '../components/Icon.svelte'
  import Player from '../components/Player.svelte'
  import StatusWord from '../components/StatusWord.svelte'
  import Thumb from '../components/Thumb.svelte'
  import VideoDetails from '../components/VideoDetails.svelte'

  /** @type {{ id: number }} */
  let { id } = $props()

  /** @type {Loader<import('../lib/types').VideoDetail>} */
  const detail = new Loader()
  /** @type {{ seek: (t: number, options?: { play?: boolean }) => void } | undefined} */
  let player = $state()
  let time = $state(0)
  /** @type {Channel | null} */
  let channel = $state(null)
  /** @type {Subscription | null} */
  let subscription = $state(null)
  /** @type {Video[]} */
  let more = $state([])
  let busy = $state('')
  /** @type {'description' | 'comments'} */
  let tab = $state('description')

  const video = $derived(detail.data)
  const job = $derived(video ? queue.jobFor(video.id) : undefined)
  const phase = $derived(video ? videoState(video, job, clock.now) : null)
  const archived = $derived(video?.status === 'archived')
  const channelId = $derived(video?.channel?.id ?? null)
  const hasComments = $derived(!!video?.comments && video.comments.saved > 0)
  const canDownload = $derived(video?.status === 'missing' || video?.status === 'deleted')
  const pending = $derived(
    !!video && (video.status === 'downloading' || video.status === 'queued') && video.job_id != null
  )
  const progress = $derived(job?.progress ?? null)

  $effect(() => {
    void ui.videosVersion
    void queue.signature
    untrack(() => detail.run(() => api.videos.get(id), { quiet: !!detail.data }))
  })

  $effect(() => {
    const cid = channelId
    untrack(() => {
      channel = null
      subscription = null
      more = []
      if (cid == null) return
      api.channels
        .get(cid)
        .then(async (c) => {
          if (channelId !== cid) return
          channel = c
          const sub = c.subscription_id ? await api.subscriptions.get(c.subscription_id).catch(() => null) : null
          if (channelId === cid) subscription = sub
        })
        .catch(() => {})
      api.videos
        .list({ channel_id: cid, per_page: 7, sort: 'published' })
        .then((res) => {
          if (channelId === cid) more = res.items.filter((v) => v.id !== id).slice(0, 6)
        })
        .catch(() => {})
    })
  })

  const reload = () => detail.run(() => api.videos.get(id), { quiet: true })

  /** @param {number} t */
  function seekTo(t) {
    player?.seek(t, { play: true })
  }

  /** @param {() => Promise<void>} action @param {string} name */
  async function run(name, action) {
    busy = name
    try {
      await action()
    } catch (e) {
      notify.error(e)
    } finally {
      busy = ''
    }
  }

  function toggleWatched() {
    if (!video) return
    const target = video
    return run('watched', async () => {
      const updated = await api.videos.setWatched(target.id, !target.watched_at)
      if (detail.data) detail.data = { ...detail.data, ...updated }
    })
  }

  /** @param {VideoOptions} options */
  function download(options) {
    if (!video) return
    const target = video
    return run('download', async () => {
      await api.videos.download(target.id, options)
      notify.success('Download queued')
      queue.refresh().catch(() => {})
      await reload()
    })
  }

  function cancelDownload() {
    if (!video?.job_id) return
    const jobId = video.job_id
    return run('cancel', async () => {
      await api.jobs.act(jobId, 'cancel')
      notify.success('Download cancelled')
      queue.refresh().catch(() => {})
      await reload()
    })
  }

  async function removeFiles() {
    if (!video) return
    const target = video
    const ok = await confirmAction({
      title: 'Remove local files?',
      message:
        `This deletes the downloaded files for “${target.title}”. The video stays in your library as ` +
        "removed, so subscriptions won't fetch it again. You can download it again later.",
      confirmLabel: 'Remove files',
      danger: true
    })
    if (!ok) return
    await run('remove', async () => {
      await api.videos.removeFiles(target.id)
      notify.success('Local files removed')
      await reload()
      channelsChanged()
    })
  }

  /** @param {string} error */
  function hintFor(error) {
    if (/bot|429/i.test(error)) return 'If bot checks keep coming back, load browser cookies with YTDLP_COOKIE_FILE.'
    if (/members/i.test(error)) return 'Needs cookies from an account with this membership.'
    return ''
  }
</script>

<svelte:head>
  <title>{video ? `${video.title} · ` : ''}YouHoard</title>
</svelte:head>

{#if detail.error && !video}
  <div class="empty">
    <b>{detail.error}</b>
    <a class="lnk" href={href('/library')}>Back to the library</a>
  </div>
{:else if video && phase}
  <nav class="crumbs" aria-label="Breadcrumb">
    <a href={href('/library')}>Library</a>
    {#if video.channel}
      <span class="sep">/</span>
      <a href={href('/library', { channel: video.channel.id })}>{video.channel.name}</a>
    {/if}
    <span class="sep">/</span>
    <span class="cur">{video.title}</span>
  </nav>

  <div class="watch">
    <div style="min-width: 0">
      {#if archived}
        <Player bind:this={player} {video} bind:time />
      {:else}
        <div class="player unavail" style:aspect-ratio="16 / 9">
          <Thumb src={video.thumbnail_url} />
          <div class="scrim"></div>
          {#if phase.key === 'downloading'}
            <div class="pov">
              {#if phase.processing}
                <span class="what"><Icon name="refresh" />Processing</span>
                <span class="info">Merging with ffmpeg{progress?.total_bytes ? ` · ${bytes(progress.total_bytes)}` : ''}</span>
                <div class="prog ind"><i></i></div>
              {:else}
                <span class="what">Downloading {percent(progress?.percent ?? null)}</span>
                <span class="info">
                  {bytes(progress?.downloaded_bytes)} of {bytes(progress?.total_bytes)} · {speed(progress?.speed)} · ETA {eta(progress?.eta)}
                </span>
                <div class="prog"><i style:width="{progress?.percent ?? 0}%"></i></div>
              {/if}
            </div>
          {:else if phase.key === 'queued' || phase.key === 'paused' || phase.key === 'missing'}
            <div class="pov">
              <span class="what">{{ queued: 'Queued', paused: 'Paused', missing: 'Not downloaded' }[phase.key]}</span>
            </div>
          {/if}
        </div>
      {/if}

      <h1 class="w-title">
        {#if video.unavailable}<i class="lz g" aria-hidden="true"></i>{/if}{video.title}
      </h1>
      <div class="w-by">
        <div class="who">
          <Avatar name={video.channel?.name ?? ''} src={channel?.avatar_url} />
          <div style="min-width: 0">
            {#if video.channel}
              <a class="chn" href={href('/library', { channel: video.channel.id })}>{video.channel.name}</a>
              {#if channel?.verified}
                <span class="verified" title="Verified"><Icon name="verified" /><span class="sr">Verified</span></span>
              {/if}
            {:else}
              <span class="chn">Unknown channel</span>
            {/if}
            <div class="sub">
              {#if subscription}
                <a class="lnk" href={href(`/subscriptions/${subscription.id}`)}>Subscribed · {policyLabel(subscription)}</a>
              {:else}
                Not subscribed
              {/if}
              {#if channel?.subscriber_count}· {compact(channel.subscriber_count)} subscribers{/if}
            </div>
          </div>
        </div>
        <div class="w-stats">
          <span><b>{dmy(video.published_at)}</b></span>
          {#if video.duration}<span><b>{dur(video.duration)}</b></span>{/if}
          {#if video.view_count}<span><b>{compact(video.view_count)}</b> views</span>{/if}
          {#if video.like_count}<span><b>{compact(video.like_count)}</b> likes</span>{/if}
        </div>
      </div>

      {#if video.unavailable && archived}
        <div class="callout gone">
          <i class="lz mk" aria-hidden="true"></i>
          <div><span class="ttl2">Gone from YouTube since {dmy(video.unavailable_at)}</span></div>
        </div>
      {:else if phase.key === 'failed'}
        <div class="callout fail">
          <Icon name="x" class="mk" />
          <div>
            <span class="ttl2">{video.unavailable ? 'Gone from YouTube before it was downloaded' : 'Download failed'}</span>
            {#if video.error}<q>{video.error}</q>{/if}
            {#if video.error && !video.unavailable && hintFor(video.error)}
              <div class="note">{hintFor(video.error)}</div>
            {/if}
            {#if !video.unavailable}
              <div class="acts"><DownloadControls label="Retry" icon="retry" busy={busy === 'download'} onrun={download} /></div>
            {/if}
          </div>
        </div>
      {:else if phase.key === 'deleted'}
        <div class="callout">
          <span class="st deleted mk" aria-hidden="true"></span>
          <div><span class="ttl2">Local files removed on {dmy(video.deleted_at)}</span></div>
        </div>
      {:else if phase.key === 'waiting' && job}
        <div class="callout">
          <Icon name="clock" class="mk" />
          <div>
            <span class="ttl2">
              {#if phase.premiere}Premieres {whenShort(job.run_after, clock.now)}
              {:else if isRetry(job)}Next attempt {whenShort(job.run_after, clock.now)} ({rel(job.run_after, clock.now)})
              {:else}Waiting until {whenShort(job.run_after, clock.now)} ({rel(job.run_after, clock.now)}){/if}
            </span>
            {#if phase.why}{phase.why}{/if}
          </div>
        </div>
      {/if}

      <div class="w-acts">
        {#if canDownload}
          <DownloadControls
            label={phase.key === 'deleted' ? 'Download again' : 'Download'}
            busy={busy === 'download'}
            onrun={download}
          />
        {/if}
        {#if pending || phase.key === 'paused'}
          <button type="button" class="btn" disabled={busy === 'cancel' || !video.job_id} onclick={cancelDownload}>
            <Icon name="x" />Cancel download
          </button>
        {/if}
        <button type="button" class="btn" aria-pressed={!!video.watched_at} disabled={busy === 'watched'} onclick={toggleWatched}>
          <Icon name={video.watched_at ? 'check' : 'eye'} />{video.watched_at ? 'Watched' : 'Mark watched'}
        </button>
        <a class="btn quiet" href={video.youtube_url} target="_blank" rel="noopener noreferrer">
          <Icon name="ext" />Open on YouTube
        </a>
        <span class="grow"></span>
        {#if archived}
          <button type="button" class="btn danger" disabled={busy === 'remove'} onclick={removeFiles}>
            <Icon name="trash" />Remove local files
          </button>
        {/if}
      </div>

      {#if hasComments}
        <FilterTabs
          class="vtabs"
          label="Video sections"
          value={tab}
          tabs={[
            { value: 'description', label: 'Description' },
            { value: 'comments', label: 'Comments' }
          ]}
          onchange={(value) => (tab = value === 'comments' ? 'comments' : 'description')}
        />
      {/if}
      {#if tab === 'comments' && hasComments && video.comments}
        <Comments
          videoId={video.id}
          saved={video.comments.saved}
          total={video.comment_count}
          duration={video.duration}
          onseek={archived ? seekTo : undefined}
        />
      {:else if video.description}
        <Description text={video.description} duration={video.duration} onseek={archived ? seekTo : undefined} />
      {/if}

      {#if more.length && video.channel}
        <div class="sec-h">
          <h2 class="label">More from {video.channel.name}</h2>
          {#if channel}<span class="n">{int(channel.archived_count)} archived</span>{/if}
          <span class="r">
            <a class="btn sm quiet" href={href('/library', { channel: video.channel.id })}>All<Icon name="right" /></a>
          </span>
        </div>
        <ul class="morelist">
          {#each more as item (item.id)}
            <li>
              <a class="mini" class:vert={item.video_type === 'short'} href={href(`/video/${item.id}`)} tabindex="-1" aria-hidden="true">
                <Thumb src={item.thumbnail_url} />
                {#if item.duration}<span class="cn br">{dur(item.duration)}</span>{/if}
              </a>
              <div style="min-width: 0">
                <a class="ttl" href={href(`/video/${item.id}`)}>
                  {#if item.unavailable}<i class="lz" aria-hidden="true"></i>{/if}{item.title}
                </a>
                <div class="meta">{dmy(item.published_at)} · <StatusWord status={item.status} videoId={item.id} /></div>
              </div>
            </li>
          {/each}
        </ul>
      {/if}
    </div>

    <aside class="record" aria-label="Details">
      {#if archived && video.chat_url}
        <ChatReplay videoId={video.id} {time} onseek={seekTo} />
      {/if}
      {#if archived && video.chapters?.length}
        <Chapters chapters={video.chapters} {time} onseek={seekTo} />
      {/if}
      <VideoDetails {video} {subscription} />
      {#if archived}
        <section aria-labelledby="subtitles-h">
          <h2 class="label" id="subtitles-h">Subtitles</h2>
          {#if video.subtitles?.length}
            <ul class="subs-list">
              {#each video.subtitles as track (track.lang)}
                <li>
                  <span>
                    {track.name || track.lang}
                    {#if SUBTITLE_SOURCES[track.source]}<span class="origin">{SUBTITLE_SOURCES[track.source]}</span>{/if}
                  </span>
                  <a
                    class="btn sm quiet"
                    href={track.url}
                    download="{video.youtube_id}.{track.lang}.vtt"
                    aria-label="Download {track.name || track.lang} subtitles as VTT"
                  >
                    <Icon name="dl" />VTT
                  </a>
                </li>
              {/each}
            </ul>
          {:else}
            <p class="note first">None saved</p>
          {/if}
        </section>
      {/if}
      {#if video.files?.length}
        <FileTree files={video.files} root={system.info?.media_dir ?? null} />
      {/if}
    </aside>
  </div>
{/if}
