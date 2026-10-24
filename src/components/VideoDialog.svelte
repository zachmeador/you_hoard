<script>
  /** @import { Subtitle, Video, VideoStatus } from '../lib/types' */
  import { onMount, untrack } from 'svelte'
  import { api, errorMessage } from '../lib/api.js'
  import { confirmAction } from '../lib/confirm.svelte.js'
  import {
    VIDEO_TYPES,
    bytes,
    compact,
    date,
    dateTime,
    duration,
    languageName,
    linkify,
    qualityLabel,
    resolution
  } from '../lib/format.js'
  import { poll } from '../lib/poll.js'
  import { queue } from '../lib/queue.svelte.js'
  import { href } from '../lib/router.svelte.js'
  import { librarySettings } from '../lib/settings.svelte.js'
  import { notify } from '../lib/toasts.svelte.js'
  import Modal from './Modal.svelte'
  import StatusBadge from './StatusBadge.svelte'
  import Thumb from './Thumb.svelte'

  /** @type {{ id: number, initial?: Video | null, onclose: () => void, onchange?: (video: Video) => void }} */
  let { id, initial = null, onclose, onchange } = $props()

  /** @type {Record<VideoStatus, string>} */
  const STATUS_MESSAGES = {
    archived: '',
    queued: 'Queued for download',
    downloading: 'Downloading…',
    failed: 'The last download failed',
    missing: 'Not downloaded',
    deleted: 'Local files were removed'
  }

  const uid = $props.id()
  /** @type {{ close: () => void } | undefined} */
  let modal = $state()
  /** @type {Video | null} */
  let video = $state(untrack(() => (initial ? { ...initial } : null)))
  /** @type {Subtitle[]} */
  let subtitles = $state([])
  let loadError = $state('')
  let busy = $state('')
  let quality = $state('')
  let expanded = $state(false)

  const pending = $derived(video?.status === 'queued' || video?.status === 'downloading')
  const canDownload = $derived(video?.status === 'missing' || video?.status === 'deleted' || video?.status === 'failed')
  const longDescription = $derived(
    (video?.description?.length ?? 0) > 320 || (video?.description?.split('\n').length ?? 0) > 6
  )
  const aspect = $derived(video?.width && video?.height ? `${video.width} / ${video.height}` : '16 / 9')
  const defaultQuality = $derived(librarySettings.current?.default_quality)

  async function load(quiet = false) {
    try {
      const { subtitles: subs, ...detail } = await api.videos.get(id)
      video = detail
      subtitles = subs ?? []
      loadError = ''
      onchange?.(detail)
    } catch (e) {
      if (!quiet) loadError = errorMessage(e)
    }
  }

  onMount(() => {
    load()
  })

  $effect(() => {
    if (pending) return poll(() => load(true), 3000, { immediate: false })
  })

  /** @param {Video} next */
  function update(next) {
    video = next
    onchange?.(next)
  }

  async function download() {
    if (!video) return
    busy = 'download'
    try {
      const { job_id } = await api.videos.download(video.id, quality || undefined)
      update({ ...video, status: 'queued', job_id, error: null })
      notify.success('Download queued')
      queue.refresh().catch(() => {})
    } catch (e) {
      notify.error(e)
    } finally {
      busy = ''
    }
  }

  async function removeFiles() {
    if (!video) return
    const ok = await confirmAction({
      title: 'Remove local files?',
      message:
        `This deletes the downloaded files for “${video.title}”. The video stays in your library as ` +
        "removed, so subscriptions won't fetch it again. You can still download it again later.",
      confirmLabel: 'Remove files',
      danger: true
    })
    if (!ok || !video) return
    busy = 'remove'
    try {
      await api.videos.removeFiles(video.id)
      update({ ...video, status: 'deleted', media_path: null, media_size: null, deleted_at: new Date().toISOString() })
      notify.success('Local files removed')
      load(true)
    } catch (e) {
      notify.error(e)
    } finally {
      busy = ''
    }
  }

  async function toggleWatched() {
    if (!video) return
    busy = 'watched'
    try {
      update(await api.videos.setWatched(video.id, !video.watched_at))
    } catch (e) {
      notify.error(e)
    } finally {
      busy = ''
    }
  }
</script>

<Modal title={video?.title ?? 'Video'} size="lg" bind:this={modal} {onclose}>
  {#if video}
    {@const v = video}
    <div class="detail">
      <div class="player">
        {#if v.status === 'archived'}
          <!-- Subtitles come from YouTube as subtitle tracks; there is no separate captions track. -->
          <!-- svelte-ignore a11y_media_has_caption -->
          <video controls preload="metadata" src={v.media_url} poster={v.thumbnail_url} style:aspect-ratio={aspect}>
            {#each subtitles as sub (sub.lang)}
              <track kind="subtitles" src={sub.url} srclang={sub.lang} label={languageName(sub.lang)} />
            {/each}
          </video>
        {:else}
          <div class="poster">
            <Thumb src={v.thumbnail_url} />
            <div class="poster-overlay">
              <span>{STATUS_MESSAGES[v.status]}</span>
              {#if pending}<span class="spinner"></span>{/if}
            </div>
          </div>
        {/if}
      </div>

      <div class="meta">
        {#if v.channel}
          <a href={href('/', { channel: v.channel.id })} onclick={() => modal?.close()}>{v.channel.name}</a>
        {/if}
        <span>{date(v.published_at)}</span>
        {#if v.duration}<span>{duration(v.duration)}</span>{/if}
        {#if v.view_count != null}<span>{compact(v.view_count)} views</span>{/if}
        {#if v.like_count != null}<span>{compact(v.like_count)} likes</span>{/if}
      </div>

      <div class="cluster">
        <StatusBadge status={v.status} />
        {#if v.video_type !== 'video'}<span class="badge">{VIDEO_TYPES[v.video_type]}</span>{/if}
        {#if v.unavailable}<span class="badge badge-danger">Gone from YouTube</span>{/if}
        {#if v.watched_at}<span class="badge badge-ok">Watched</span>{/if}
      </div>

      {#if v.status === 'failed' && v.error}
        <p class="form-error">{v.error}</p>
      {/if}

      <div class="actions">
        {#if canDownload}
          <label class="sr-only" for="{uid}-quality">Quality</label>
          <select id="{uid}-quality" class="quality" bind:value={quality}>
            <option value="">Library default{defaultQuality ? ` (${qualityLabel(defaultQuality)})` : ''}</option>
            {#each librarySettings.options.qualities as q (q)}
              <option value={q}>{qualityLabel(q)}</option>
            {/each}
          </select>
          <button type="button" class="btn btn-primary btn-sm" disabled={!!busy} onclick={download}>
            {v.status === 'failed' ? 'Retry' : 'Download'}
          </button>
        {/if}
        {#if v.status === 'archived'}
          <button type="button" class="btn btn-danger btn-sm" disabled={!!busy} onclick={removeFiles}>
            Remove local files
          </button>
        {/if}
        <button type="button" class="btn btn-secondary btn-sm" disabled={!!busy} onclick={toggleWatched}>
          {v.watched_at ? 'Mark unwatched' : 'Mark watched'}
        </button>
        <a class="btn btn-secondary btn-sm" href={v.youtube_url} target="_blank" rel="noopener noreferrer">
          Open on YouTube
        </a>
      </div>

      {#if v.description}
        <section class="description" class:collapsed={longDescription && !expanded} aria-label="Description">
          <p class="description-text">{#each linkify(v.description) as part, i (i)}{#if part.url}<a
                  href={part.text}
                  target="_blank"
                  rel="noopener noreferrer">{part.text}</a
                >{:else}{part.text}{/if}{/each}</p>
          {#if longDescription}
            <button type="button" class="link-btn small more" aria-expanded={expanded} onclick={() => (expanded = !expanded)}>
              {expanded ? 'Show less' : 'Show more'}
            </button>
          {/if}
        </section>
      {/if}

      <dl class="kv">
        <dt>Type</dt>
        <dd>{VIDEO_TYPES[v.video_type]}</dd>
        {#if v.quality || v.width}
          <dt>Quality</dt>
          <dd>{qualityLabel(v.quality)}{v.width && v.height ? ` · ${resolution(v.width, v.height)}` : ''}</dd>
        {/if}
        {#if v.media_size != null}
          <dt>Size</dt>
          <dd>{bytes(v.media_size)}</dd>
        {/if}
        {#if v.archived_at}
          <dt>Archived</dt>
          <dd>{dateTime(v.archived_at)}</dd>
        {/if}
        {#if v.watched_at}
          <dt>Watched</dt>
          <dd>{dateTime(v.watched_at)}</dd>
        {/if}
        {#if v.deleted_at}
          <dt>Files removed</dt>
          <dd>{dateTime(v.deleted_at)}</dd>
        {/if}
        <dt>Added</dt>
        <dd>{dateTime(v.created_at)}</dd>
        {#if subtitles.length}
          <dt>Subtitles</dt>
          <dd>{subtitles.map((s) => s.lang).join(', ')}</dd>
        {/if}
        <dt>YouTube ID</dt>
        <dd>{v.youtube_id}</dd>
        {#if v.media_path}
          <dt>File</dt>
          <dd class="path">{v.media_path}</dd>
        {/if}
      </dl>
    </div>
  {:else if loadError}
    <p class="form-error" role="alert">{loadError}</p>
  {:else}
    <p class="loading-line"><span class="spinner"></span> Loading…</p>
  {/if}
</Modal>

<style>
  .detail {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  .player {
    background: #000;
    border-radius: var(--radius);
    overflow: hidden;
  }

  .player video {
    width: 100%;
    max-height: 70vh;
    background: #000;
  }

  .poster {
    position: relative;
    aspect-ratio: 16 / 9;
    max-height: 50vh;
    margin: 0 auto;
  }

  .poster-overlay {
    position: absolute;
    inset: auto 0 0 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    background: linear-gradient(transparent, rgb(0 0 0 / 0.9));
    font-size: 0.8125rem;
  }

  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-3);
    color: var(--text-secondary);
    font-size: 0.8125rem;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .quality {
    width: auto;
    min-height: 0;
    padding-top: var(--space-1);
    padding-bottom: var(--space-1);
    font-size: 0.75rem;
  }

  .description {
    padding: var(--space-3);
    background: var(--background);
    border: 1px solid var(--border-dark);
    border-radius: var(--radius);
  }

  .description-text {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    color: var(--text-secondary);
    font-size: 0.8125rem;
  }

  .collapsed .description-text {
    max-height: 7.5em;
    overflow: hidden;
    mask-image: linear-gradient(#000 60%, transparent);
  }

  .more {
    margin-top: var(--space-2);
    color: var(--terminal-green);
  }

  .path {
    font-size: 0.75rem;
    color: var(--text-secondary);
  }
</style>
