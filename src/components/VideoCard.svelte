<script>
  /** @import { Video } from '../lib/types' */
  import { VIDEO_TYPES, date, duration } from '../lib/format.js'
  import StatusBadge from './StatusBadge.svelte'
  import Thumb from './Thumb.svelte'

  /** @type {{ video: Video, onopen: () => void }} */
  let { video, onopen } = $props()
</script>

<article class="vcard" class:watched={!!video.watched_at}>
  <div class="thumb">
    <Thumb src={video.thumbnail_url} />
    <div class="flags">
      {#if video.status !== 'archived'}<StatusBadge status={video.status} />{/if}
      {#if video.unavailable}<span class="badge badge-danger">Gone from YouTube</span>{/if}
      {#if video.video_type !== 'video'}<span class="badge">{VIDEO_TYPES[video.video_type]}</span>{/if}
    </div>
    {#if video.watched_at}<span class="badge badge-ok watched-mark">✓ Watched</span>{/if}
    {#if video.duration}<span class="duration">{duration(video.duration)}</span>{/if}
  </div>
  <div class="body">
    <h2 class="title">
      <button type="button" class="link-btn stretched" onclick={onopen}><span class="clamp">{video.title}</span></button>
    </h2>
    <p class="meta">
      <span class="truncate">{video.channel?.name ?? 'Unknown channel'}</span>
      <span class="nowrap">{date(video.published_at)}</span>
    </p>
  </div>
</article>

<style>
  .vcard {
    position: relative;
    display: flex;
    flex-direction: column;
    height: 100%;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
    transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
  }

  .vcard:hover,
  .vcard:focus-within {
    border-color: var(--terminal-green);
    box-shadow: var(--glow-primary);
    transform: translateY(-2px);
  }

  .thumb {
    position: relative;
    aspect-ratio: 16 / 9;
    background: var(--surface-hover);
  }

  .watched .thumb :global(.thumb-img) {
    opacity: 0.55;
  }

  .flags {
    position: absolute;
    top: 4px;
    left: 4px;
    right: 4px;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  .watched-mark {
    position: absolute;
    left: 4px;
    bottom: 4px;
  }

  .duration {
    position: absolute;
    right: 4px;
    bottom: 4px;
    padding: 0 0.3rem;
    border-radius: var(--radius-sm);
    background: rgb(0 0 0 / 0.85);
    font-size: 0.6875rem;
    font-weight: 600;
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    padding: var(--space-2) var(--space-3) var(--space-3);
    min-width: 0;
  }

  .title {
    font-size: 0.8125rem;
    font-weight: 600;
    line-height: 1.35;
  }

  .stretched {
    display: block;
    width: 100%;
  }

  .stretched::after {
    content: '';
    position: absolute;
    inset: 0;
  }

  .stretched:focus-visible {
    outline: none;
  }

  .stretched:focus-visible::after {
    outline: 2px solid var(--terminal-green);
    outline-offset: -2px;
    border-radius: var(--radius-lg);
  }

  .clamp {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    overflow-wrap: anywhere;
  }

  .meta {
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    font-size: 0.75rem;
    color: var(--text-muted);
  }
</style>
