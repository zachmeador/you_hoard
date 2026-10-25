<script>
  /** @import { Channel, Page, Subscription, Video, VideoCounts } from '../lib/types' */
  import { onMount, untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { groupLabel } from '../lib/format.js'
  import { Loader } from '../lib/loader.svelte.js'
  import { prefs } from '../lib/prefs.svelte.js'
  import { queue } from '../lib/queue.svelte.js'
  import { pageParam, router, updateQuery } from '../lib/router.svelte.js'
  import { clock, openAdd, ui } from '../lib/ui.svelte.js'
  import ChannelBand from '../components/ChannelBand.svelte'
  import FilterTabs from '../components/FilterTabs.svelte'
  import Icon from '../components/Icon.svelte'
  import Pager from '../components/Pager.svelte'
  import SearchField from '../components/SearchField.svelte'
  import Segmented from '../components/Segmented.svelte'
  import SelectField from '../components/SelectField.svelte'
  import VideoTable from '../components/VideoTable.svelte'
  import VideoTile from '../components/VideoTile.svelte'

  const PER_PAGE = 48
  const FACETS = [
    { value: '', label: 'All', key: 'all' },
    { value: 'archived', label: 'Archived', key: 'archived' },
    { value: 'downloading', label: 'Downloading', key: 'downloading' },
    { value: 'queued', label: 'Queued', key: 'queued' },
    { value: 'failed', label: 'Failed', key: 'failed' },
    { value: 'missing', label: 'Not downloaded', key: 'missing' },
    { value: 'deleted', label: 'Files removed', key: 'deleted' }
  ]
  const TYPE_OPTIONS = [
    { value: '', label: 'All' },
    { value: 'video', label: 'Videos' },
    { value: 'short', label: 'Shorts' },
    { value: 'live', label: 'Streams' }
  ]
  const WATCHED_OPTIONS = [
    { value: '', label: 'Any' },
    { value: 'false', label: 'Unwatched' },
    { value: 'true', label: 'Watched' }
  ]
  const SORT_OPTIONS = [
    { value: 'published', label: 'Published' },
    { value: 'archived', label: 'Archived' },
    { value: 'added', label: 'Added' },
    { value: 'title', label: 'Title' },
    { value: 'duration', label: 'Duration' },
    { value: 'views', label: 'Views' }
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
  const filtered = $derived(Boolean(filters.q || filters.type || filters.watched || filters.channel))

  /** @type {Loader<Page<Video>>} */
  const videos = new Loader()
  /** @type {Loader<VideoCounts>} */
  const counts = new Loader()
  /** @type {Channel[]} */
  let channels = $state([])
  /** @type {Channel | null} */
  let activeChannel = $state(null)
  /** @type {Subscription | null} */
  let activeSubscription = $state(null)
  let search = $state(untrack(() => router.query.q ?? ''))

  const items = $derived(videos.data?.items ?? [])
  const pages = $derived(Math.max(1, Math.ceil((videos.data?.total ?? 0) / (videos.data?.per_page || PER_PAGE))))
  const tabs = $derived([
    ...FACETS.map((facet) => ({
      value: facet.value,
      label: facet.label,
      count: counts.data ? counts.data[/** @type {keyof VideoCounts} */ (facet.key)] : null
    })),
    { value: 'gone', label: 'Gone from YouTube', count: counts.data?.unavailable ?? null, gone: true, gap: true }
  ])
  const channelOptions = $derived.by(() => {
    const list = activeChannel && !channels.some((c) => c.id === activeChannel?.id) ? [activeChannel, ...channels] : channels
    return [{ value: '', label: 'All' }, ...list.map((c) => ({ value: String(c.id), label: c.name }))]
  })
  const cells = $derived.by(() => {
    if (filters.sort !== 'published') return items.map((video) => ({ video, group: '' }))
    let last = ''
    return items.map((video) => {
      const group = groupLabel(video.published_at, clock.now)
      const heading = group === last ? '' : group
      last = group
      return { video, group: heading }
    })
  })
  const tokens = $derived.by(() => {
    /** @type {{ key: string, label: string }[]} */
    const list = []
    if (filters.q) list.push({ key: 'q', label: `“${filters.q}”` })
    if (filters.type) list.push({ key: 'type', label: TYPE_OPTIONS.find((o) => o.value === filters.type)?.label ?? filters.type })
    if (filters.watched) list.push({ key: 'watched', label: WATCHED_OPTIONS.find((o) => o.value === filters.watched)?.label ?? filters.watched })
    if (filters.channel) {
      const known = activeChannel ?? channels.find((c) => String(c.id) === filters.channel)
      list.push({ key: 'channel', label: known?.name ?? 'Channel' })
    }
    return list
  })

  /** @param {typeof filters} f */
  function listQuery(f) {
    const gone = f.status === 'gone'
    return {
      q: f.q,
      status: gone ? '' : f.status,
      unavailable: gone ? 'true' : '',
      video_type: f.type,
      watched: f.watched,
      channel_id: f.channel,
      sort: f.sort,
      order: f.order,
      page: f.page,
      per_page: PER_PAGE
    }
  }

  let lastKey = ''
  $effect(() => {
    const f = filters
    const version = ui.videosVersion
    void queue.signature
    const key = JSON.stringify(f) + version
    untrack(() => {
      const quiet = key === lastKey
      lastKey = key
      videos.run(() => api.videos.list(listQuery(f)), { quiet })
      counts.run(
        () => api.videos.counts({ q: f.q, video_type: f.type, watched: f.watched, channel_id: f.channel }),
        { quiet: true }
      )
    })
  })

  $effect(() => {
    const data = videos.data
    const page = filters.page
    if (!data || data.items.length > 0 || page <= 1) return
    const last = Math.max(1, Math.ceil(data.total / (data.per_page || PER_PAGE)))
    if (last < page) untrack(() => updateQuery({ page: last > 1 ? last : null }))
  })

  $effect(() => {
    const id = Number(filters.channel) || 0
    void ui.channelsVersion
    void ui.subscriptionsVersion
    untrack(() => {
      if (activeChannel?.id !== id) {
        activeChannel = null
        activeSubscription = null
      }
      if (!id) return
      api.channels
        .get(id)
        .then(async (channel) => {
          if (Number(filters.channel) !== channel.id) return
          activeChannel = channel
          const sub = channel.subscription_id
            ? await api.subscriptions.get(channel.subscription_id).catch(() => null)
            : null
          if (Number(filters.channel) === channel.id) activeSubscription = sub
        })
        .catch(() => {})
    })
  })

  $effect(() => {
    const external = router.query.q ?? ''
    untrack(() => {
      if (external !== search.trim()) search = external
    })
  })

  $effect(() => {
    const value = search.trim()
    const timer = setTimeout(() => {
      if (value !== (router.query.q ?? '')) updateQuery({ q: value })
    }, 250)
    return () => clearTimeout(timer)
  })

  onMount(() => {
    api.channels
      .list({ per_page: 500 })
      .then((res) => (channels = res.items))
      .catch(() => {})
  })

  /** @param {string} key */
  function sortBy(key) {
    if (filters.sort === key) updateQuery({ order: filters.order === 'desc' ? 'asc' : 'desc' })
    else updateQuery({ sort: key, order: key === 'title' ? 'asc' : 'desc' })
  }

  /** @param {number} page */
  function goTo(page) {
    updateQuery({ page: page > 1 ? page : null })
    window.scrollTo({ top: 0 })
  }

  /** @param {string} key */
  function removeToken(key) {
    if (key === 'q') search = ''
    updateQuery({ [key]: '' })
  }

  function reset() {
    search = ''
    updateQuery({ q: '', type: '', watched: '', channel: '' })
  }
</script>

<svelte:head>
  <title>{activeChannel ? `${activeChannel.name} · ` : ''}Library · YouHoard</title>
</svelte:head>

{#if filters.channel && activeChannel}
  <ChannelBand channel={activeChannel} subscription={activeSubscription} onclear={() => updateQuery({ channel: '' })} />
{/if}

<header class="ph lib-h">
  <h1>Library</h1>
  <div class="ph-r">
    <Segmented
      label="Layout"
      class="view"
      value={prefs.view}
      options={[
        { value: 'grid', label: 'Grid', icon: 'grid' },
        { value: 'list', label: 'List', icon: 'list' }
      ]}
      onchange={(value) => prefs.setView(value === 'list' ? 'list' : 'grid')}
    />
  </div>
</header>

<div class="lib-bar">
  <div class="toolbar">
    <SearchField label="Search the library" placeholder="Search titles, channels, video IDs" kbd="/" bind:value={search} />
    <div class="filters">
      <SelectField label="Type" value={filters.type} options={TYPE_OPTIONS} onchange={(value) => updateQuery({ type: value })} />
      <SelectField
        label="Watched"
        value={filters.watched}
        options={WATCHED_OPTIONS}
        onchange={(value) => updateQuery({ watched: value })}
      />
      <SelectField
        label="Channel"
        value={filters.channel}
        options={channelOptions}
        onchange={(value) => updateQuery({ channel: value })}
      />
      <SelectField
        label="Sort"
        value={filters.sort}
        options={SORT_OPTIONS}
        onchange={(value) => updateQuery({ sort: value, order: value === 'title' ? 'asc' : 'desc' })}
      />
      <button
        type="button"
        class="btn icon"
        aria-label={filters.order === 'desc' ? 'Descending; switch to ascending' : 'Ascending; switch to descending'}
        title={filters.order === 'desc' ? 'Newest / largest first' : 'Oldest / smallest first'}
        onclick={() => updateQuery({ order: filters.order === 'desc' ? 'asc' : 'desc' })}
      >
        <Icon name={filters.order === 'desc' ? 'down' : 'up'} />
      </button>
    </div>
  </div>
  <FilterTabs label="Status" value={filters.status} {tabs} onchange={(value) => updateQuery({ status: value })} />
</div>

{#if tokens.length}
  <div class="resbar">
    {#each tokens as token (token.key)}
      <span class="token">
        {token.label}
        <button type="button" aria-label="Remove filter {token.label}" onclick={() => removeToken(token.key)}>
          <Icon name="x" />
        </button>
      </span>
    {/each}
    <button type="button" class="btn sm quiet" onclick={reset}>Reset</button>
  </div>
{/if}

{#if videos.error}
  <div class="empty">
    <b>Couldn't load the library</b>
    {videos.error}
    <div><button type="button" class="btn sm" onclick={() => videos.run(() => api.videos.list(listQuery(filters)))}>Try again</button></div>
  </div>
{:else if videos.data && items.length === 0}
  {#if filtered || filters.status}
    <div class="empty"><b>No matches</b>No videos match these filters.</div>
  {:else}
    <div class="empty">
      <b>Nothing here yet</b>
      <button type="button" class="btn" onclick={() => openAdd()}><Icon name="plus" />Add a video, channel or playlist</button>
    </div>
  {/if}
{:else if prefs.view === 'grid'}
  <div class="grid" aria-busy={videos.loading}>
    {#each cells as cell (cell.video.id)}
      {#if cell.group}<div class="grp"><h2>{cell.group}</h2></div>{/if}
      <VideoTile video={cell.video} />
    {/each}
  </div>
{:else}
  <VideoTable videos={items} sort={filters.sort} order={filters.order} onsort={sortBy} />
{/if}

<Pager label="Pages" page={filters.page} {pages} onpage={goTo} />
