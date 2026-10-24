<script>
  /** @import { Channel, Page, Video } from '../lib/types' */
  import { onMount, untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { CONTENT_TYPES, STATUS, int, plural } from '../lib/format.js'
  import { Loader } from '../lib/loader.svelte.js'
  import { poll } from '../lib/poll.js'
  import { pageParam, router, updateQuery } from '../lib/router.svelte.js'
  import { ui } from '../lib/ui.svelte.js'
  import Pagination from '../components/Pagination.svelte'
  import SearchBox from '../components/SearchBox.svelte'
  import VideoCard from '../components/VideoCard.svelte'
  import VideoDialog from '../components/VideoDialog.svelte'

  const PER_PAGE = 48
  const STATUSES = ['archived', 'queued', 'downloading', 'failed', 'missing', 'deleted']
  const TYPES = /** @type {const} */ (['video', 'short', 'live'])
  const SORTS = [
    ['published', 'Published'],
    ['archived', 'Archived'],
    ['added', 'Added'],
    ['title', 'Title'],
    ['duration', 'Duration']
  ]

  const filters = $derived({
    q: router.query.q ?? '',
    status: router.query.status ?? '',
    type: router.query.type ?? '',
    watched: router.query.watched ?? '',
    channel: router.query.channel ?? '',
    sort: router.query.sort ?? 'published',
    order: router.query.order ?? 'desc',
    page: pageParam(router.query.page)
  })
  const search = $derived(filters.q)
  const channelId = $derived(Number(router.query.channel) || 0)
  const filtered = $derived(Boolean(filters.q || filters.status || filters.type || filters.watched || filters.channel))

  /** @type {Loader<Page<Video>>} */
  const videos = new Loader()
  /** @type {Channel[]} */
  let channels = $state([])
  let channelTotal = $state(0)
  let activeChannel = $state(/** @type {Channel | null} */ (null))
  let selected = $state(/** @type {Video | null} */ (null))

  const channelOptions = $derived(
    activeChannel && !channels.some((c) => c.id === activeChannel?.id) ? [activeChannel, ...channels] : channels
  )
  const hasPending = $derived(
    videos.data?.items.some((v) => v.status === 'queued' || v.status === 'downloading') ?? false
  )

  /** @param {typeof filters} f */
  function fetchVideos(f) {
    return api.videos.list({
      q: f.q,
      status: f.status,
      video_type: f.type,
      watched: f.watched,
      channel_id: f.channel,
      sort: f.sort,
      order: f.order,
      page: f.page,
      per_page: PER_PAGE
    })
  }

  function reload() {
    videos.run(() => fetchVideos(filters))
  }

  $effect(() => {
    const f = filters
    void ui.videosVersion
    untrack(() => videos.run(() => fetchVideos(f)))
  })

  $effect(() => {
    if (!hasPending) return
    return poll(() => videos.run(() => fetchVideos(filters), { quiet: true }), 3000, { immediate: false })
  })

  $effect(() => {
    const data = videos.data
    const page = filters.page
    if (!data || data.items.length > 0 || page <= 1) return
    const last = Math.max(1, Math.ceil(data.total / (data.per_page || PER_PAGE)))
    if (last < page) untrack(() => updateQuery({ page: last > 1 ? last : null }))
  })

  $effect(() => {
    const id = channelId
    if (!id) {
      activeChannel = null
      return
    }
    untrack(() => {
      if (activeChannel?.id === id) return
      api.channels
        .get(id)
        .then((channel) => {
          if (channelId === channel.id) activeChannel = channel
        })
        .catch(() => {})
    })
  })

  onMount(() => {
    api.channels
      .list({ per_page: 200 })
      .then((res) => {
        channels = res.items
        channelTotal = res.total
      })
      .catch(() => {})
  })

  /** @param {Video} updated */
  function patch(updated) {
    const items = videos.data?.items
    if (!items) return
    const i = items.findIndex((v) => v.id === updated.id)
    if (i !== -1) items[i] = updated
  }

  /** @param {Event & { currentTarget: HTMLSelectElement }} event */
  function selectValue(event) {
    return event.currentTarget.value
  }

  function resetFilters() {
    updateQuery({ q: '', status: '', type: '', watched: '', channel: '' })
  }
</script>

<svelte:head>
  <title>{activeChannel ? `${activeChannel.name} · ` : ''}Library · YouHoard</title>
</svelte:head>

<div class="page-head">
  <h1 class="page-title">Library</h1>
  {#if videos.data}
    <span class="muted">{plural(videos.data.total, 'video')}{filtered ? ' match' : ''}</span>
  {/if}
</div>

{#if activeChannel}
  <div class="channel-bar">
    <span>Channel: <strong>{activeChannel.name}</strong></span>
    <span class="muted small">{int(activeChannel.archived_count)} of {int(activeChannel.video_count)} archived</span>
    {#if activeChannel.subscription_id}
      <a class="badge badge-ok" href="#/subscriptions/{activeChannel.subscription_id}">Subscribed</a>
    {/if}
    <a class="ext-link small" href={activeChannel.youtube_url} target="_blank" rel="noopener noreferrer">YouTube ↗</a>
  </div>
{/if}

<div class="toolbar">
  <SearchBox value={search} label="Search videos" placeholder="Search videos…" onsearch={(q) => updateQuery({ q })} />

  <label class="sr-only" for="library-status">Status</label>
  <select id="library-status" value={filters.status} onchange={(e) => updateQuery({ status: selectValue(e) })}>
    <option value="">All statuses</option>
    {#each STATUSES as status (status)}
      <option value={status}>{STATUS[status].label}</option>
    {/each}
  </select>

  <label class="sr-only" for="library-type">Type</label>
  <select id="library-type" value={filters.type} onchange={(e) => updateQuery({ type: selectValue(e) })}>
    <option value="">All types</option>
    {#each TYPES as type (type)}
      <option value={type}>{CONTENT_TYPES[type]}</option>
    {/each}
  </select>

  <label class="sr-only" for="library-watched">Watched</label>
  <select id="library-watched" value={filters.watched} onchange={(e) => updateQuery({ watched: selectValue(e) })}>
    <option value="">Watched: any</option>
    <option value="false">Unwatched</option>
    <option value="true">Watched</option>
  </select>

  <label class="sr-only" for="library-channel">Channel</label>
  <select id="library-channel" value={filters.channel} onchange={(e) => updateQuery({ channel: selectValue(e) })}>
    <option value="">All channels</option>
    {#each channelOptions as channel (channel.id)}
      <option value={String(channel.id)}>{channel.name}</option>
    {/each}
    {#if channelTotal > channels.length}
      <option disabled value="more">More on the Channels page…</option>
    {/if}
  </select>

  <label class="sr-only" for="library-sort">Sort by</label>
  <select
    id="library-sort"
    value={filters.sort}
    onchange={(e) => {
      const sort = selectValue(e)
      updateQuery({ sort: sort === 'published' ? '' : sort })
    }}
  >
    {#each SORTS as [value, label] (value)}
      <option {value}>{label}</option>
    {/each}
  </select>

  <label class="sr-only" for="library-order">Order</label>
  <select
    id="library-order"
    value={filters.order}
    onchange={(e) => {
      const order = selectValue(e)
      updateQuery({ order: order === 'desc' ? '' : order })
    }}
  >
    <option value="desc">↓ Desc</option>
    <option value="asc">↑ Asc</option>
  </select>

  {#if filtered}
    <button type="button" class="btn btn-ghost btn-sm" onclick={resetFilters}>Reset filters</button>
  {/if}
</div>

{#if videos.error}
  <div class="form-error error-bar" role="alert">
    <span>{videos.error}</span>
    <button type="button" class="btn btn-secondary btn-sm" onclick={reload}>Try again</button>
  </div>
{/if}

{#if videos.data}
  {#if videos.data.items.length === 0}
    <div class="empty">
      {#if filtered}
        No videos match these filters.
      {:else}
        Nothing here yet. Use “Add video” above, or <a href="#/subscriptions">set up a subscription</a>.
      {/if}
    </div>
  {:else}
    <ul class="video-grid" class:stale={videos.loading}>
      {#each videos.data.items as video (video.id)}
        <li><VideoCard {video} onopen={() => (selected = video)} /></li>
      {/each}
    </ul>
  {/if}
  <Pagination
    page={filters.page}
    total={videos.data.total}
    perPage={videos.data.per_page || PER_PAGE}
    label="Library pages"
    onpage={(page) => {
      updateQuery({ page: page > 1 ? page : null })
      window.scrollTo(0, 0)
    }}
  />
{:else if videos.loading}
  <p class="loading-line"><span class="spinner"></span> Loading library…</p>
{/if}

{#if selected}
  <VideoDialog id={selected.id} initial={selected} onchange={patch} onclose={() => (selected = null)} />
{/if}

<style>
  .channel-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    margin-bottom: var(--space-3);
    padding: var(--space-2) var(--space-3);
    background: var(--surface);
    border: 1px solid var(--border);
    border-left: 3px solid var(--terminal-green);
    border-radius: var(--radius);
  }

  .video-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 190px), 1fr));
    gap: var(--space-3);
  }

  @media (max-width: 640px) {
    .video-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: var(--space-2);
    }
  }
</style>
