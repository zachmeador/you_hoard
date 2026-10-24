<script>
  /** @import { Entry, Page, Subscription, SubscriptionCounts, Video } from '../lib/types' */
  import { onMount, untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import {
    CONTENT_TYPES,
    POLICIES,
    STATUS,
    VIDEO_TYPES,
    duration,
    int,
    interval,
    languages,
    plural,
    policySummary,
    qualityLabel
  } from '../lib/format.js'
  import { Loader } from '../lib/loader.svelte.js'
  import { poll } from '../lib/poll.js'
  import { queue } from '../lib/queue.svelte.js'
  import { href, navigate, pageParam, router, updateQuery } from '../lib/router.svelte.js'
  import { notify } from '../lib/toasts.svelte.js'
  import CheckStatus from '../components/CheckStatus.svelte'
  import Pagination from '../components/Pagination.svelte'
  import SearchBox from '../components/SearchBox.svelte'
  import StatusBadge from '../components/StatusBadge.svelte'
  import SubscriptionActions from '../components/SubscriptionActions.svelte'
  import Time from '../components/Time.svelte'
  import VideoDialog from '../components/VideoDialog.svelte'

  /** @type {{ id: number }} */
  let { id } = $props()

  const PER_PAGE = 50
  const ENTRY_STATUSES = ['not_selected', 'missing', 'queued', 'downloading', 'archived', 'failed', 'deleted']
  const DOWNLOADABLE = ['not_selected', 'missing', 'failed']
  /** @type {[keyof SubscriptionCounts, string, string | null][]} */
  const COUNT_FILTERS = [
    ['entries', 'entries', ''],
    ['archived', 'archived', 'archived'],
    ['queued', 'queued', 'queued'],
    ['failed', 'failed', 'failed'],
    ['not_selected', 'not selected', 'not_selected'],
    ['removed', 'removed from source', null]
  ]

  const filters = $derived({
    status: router.query.status ?? '',
    type: router.query.type ?? '',
    q: router.query.q ?? '',
    page: pageParam(router.query.page)
  })
  const search = $derived(filters.q)

  /** @type {Loader<Subscription>} */
  const sub = new Loader()
  /** @type {Loader<Page<Entry>>} */
  const entries = new Loader()
  /** @type {number | null} */
  let openVideoId = $state(null)
  let busyEntry = $state('')
  let wasChecking = false

  const checking = $derived(Boolean(sub.data?.checking))
  const active = $derived(
    checking || (entries.data?.items.some((e) => e.status === 'queued' || e.status === 'downloading') ?? false)
  )

  /** @param {boolean} [quiet] */
  function loadSub(quiet = false) {
    return sub.run(() => api.subscriptions.get(id), { quiet })
  }

  /** @param {typeof filters} f */
  function fetchEntries(f) {
    return api.subscriptions.entries(id, {
      status: f.status,
      video_type: f.type,
      q: f.q,
      page: f.page,
      per_page: PER_PAGE
    })
  }

  function refreshEntries() {
    return entries.run(() => fetchEntries(filters), { quiet: true })
  }

  onMount(() => {
    loadSub()
  })

  $effect(() => {
    const f = filters
    untrack(() => entries.run(() => fetchEntries(f)))
  })

  $effect(() => {
    if (!active) return
    return poll(() => Promise.all([loadSub(true), refreshEntries()]), 3000, { immediate: false })
  })

  $effect(() => {
    const now = checking
    if (wasChecking && !now) untrack(refreshEntries)
    wasChecking = now
  })

  /** @param {Entry} entry */
  async function downloadEntry(entry) {
    busyEntry = entry.youtube_id
    try {
      const res = await api.subscriptions.downloadEntry(id, entry.youtube_id)
      entry.status = 'queued'
      entry.video_id = res.video_id
      notify.success(`Queued “${entry.title ?? entry.youtube_id}”`)
      queue.refresh().catch(() => {})
      loadSub(true)
    } catch (e) {
      notify.error(e)
    } finally {
      busyEntry = ''
    }
  }

  /** @param {Video} video */
  function videoChanged(video) {
    const entry = entries.data?.items.find((e) => e.video_id === video.id)
    if (entry) entry.status = video.status
  }

  /** @param {Event & { currentTarget: HTMLSelectElement }} event */
  function selectValue(event) {
    return event.currentTarget.value
  }
</script>

<svelte:head>
  <title>{sub.data?.title ?? 'Subscription'} · YouHoard</title>
</svelte:head>

{#if sub.data}
  {@const s = sub.data}
  <header class="head">
    <div class="page-head">
      <h1 class="page-title">{s.title}</h1>
      <div class="cluster">
        <span class="badge badge-info">{s.kind}</span>
        <span class="badge">{policySummary(s.download_policy, s.recent_count)}</span>
        {#if !s.enabled}<span class="badge badge-muted">Paused</span>{/if}
      </div>
    </div>
    <p class="dots muted small">
      {#if s.owner_name}<span>by {s.owner_name}</span>{/if}
      {#if s.channel}<a href={href('/', { channel: s.channel.id })}>Show videos</a>{/if}
      <a href={s.url} target="_blank" rel="noopener noreferrer">Open on YouTube ↗</a>
      <span>subscribed <Time value={s.created_at} /></span>
    </p>
    <SubscriptionActions
      sub={s}
      onupdate={(updated) => (sub.data = updated)}
      ondeleted={() => navigate('/subscriptions')}
    />
  </header>

  <div class="overview">
    <section class="panel" aria-labelledby="settings-title">
      <h2 id="settings-title" class="section-title">Settings</h2>
      <dl class="kv">
        <dt>Policy</dt>
        <dd>
          {POLICIES[s.download_policy]?.label ?? s.download_policy}{s.download_policy === 'recent'
            ? ` (N = ${s.recent_count})`
            : ''}
          <span class="muted">· {POLICIES[s.download_policy]?.help}</span>
        </dd>
        {#if s.kind === 'channel'}
          <dt>Content</dt>
          <dd>{s.content_types.map((t) => CONTENT_TYPES[t] ?? t).join(', ') || 'None'}</dd>
        {/if}
        <dt>Quality</dt>
        <dd>{s.quality ? qualityLabel(s.quality) : 'Library default'}</dd>
        <dt>Subtitles</dt>
        <dd>{s.subtitle_languages == null ? 'Library default' : languages(s.subtitle_languages)}</dd>
        <dt>Comments</dt>
        <dd>{s.download_comments == null ? 'Library default' : s.download_comments ? 'Download' : 'Skip'}</dd>
        <dt>Checks</dt>
        <dd>{interval(s.check_interval_hours)}</dd>
      </dl>
    </section>

    <section class="panel stack" aria-labelledby="status-title">
      <h2 id="status-title" class="section-title">Status</h2>
      <CheckStatus sub={s} />
      <div class="count-buttons" role="group" aria-label="Filter the inventory by status">
        {#each COUNT_FILTERS as [key, label, status] (key)}
          {#if status === null}
            <span class="count-btn"><strong>{int(s.counts[key])}</strong> {label}</span>
          {:else}
            <button
              type="button"
              class="count-btn"
              aria-pressed={filters.status === status}
              onclick={() => updateQuery({ status })}
            >
              <strong>{int(s.counts[key])}</strong>
              {label}
            </button>
          {/if}
        {/each}
      </div>
    </section>
  </div>
{:else if sub.error}
  <div class="form-error error-bar" role="alert">
    <span>{sub.error}</span>
    <button type="button" class="btn btn-secondary btn-sm" onclick={() => loadSub()}>Try again</button>
  </div>
{:else}
  <p class="loading-line"><span class="spinner"></span> Loading subscription…</p>
{/if}

<section class="inventory" aria-labelledby="inventory-title">
  <div class="page-head">
    <h2 id="inventory-title" class="section-title">Inventory</h2>
    {#if entries.data}<span class="muted small">{plural(entries.data.total, 'entry', 'entries')}</span>{/if}
  </div>

  <div class="toolbar">
    <SearchBox value={search} label="Search entries" placeholder="Search entries…" onsearch={(q) => updateQuery({ q })} />
    <label class="sr-only" for="entry-status">Status</label>
    <select id="entry-status" value={filters.status} onchange={(e) => updateQuery({ status: selectValue(e) })}>
      <option value="">All statuses</option>
      {#each ENTRY_STATUSES as status (status)}
        <option value={status}>{STATUS[status].label}</option>
      {/each}
    </select>
    <label class="sr-only" for="entry-type">Type</label>
    <select id="entry-type" value={filters.type} onchange={(e) => updateQuery({ type: selectValue(e) })}>
      <option value="">All types</option>
      <option value="video">Videos</option>
      <option value="short">Shorts</option>
      <option value="live">Live</option>
    </select>
  </div>

  {#if entries.error}
    <div class="form-error error-bar" role="alert">
      <span>{entries.error}</span>
      <button type="button" class="btn btn-secondary btn-sm" onclick={() => entries.run(() => fetchEntries(filters))}>
        Try again
      </button>
    </div>
  {/if}

  {#if entries.data}
    {#if entries.data.items.length === 0}
      <div class="empty">
        {filters.status || filters.type || filters.q
          ? 'No entries match these filters.'
          : checking
            ? 'Listing the source… entries appear as the check runs.'
            : 'No entries yet. Run a check to list what the source has.'}
      </div>
    {:else}
      <ul class="rows" class:stale={entries.loading}>
        {#each entries.data.items as entry (entry.youtube_id)}
          {@const title = entry.title ?? entry.youtube_id}
          {@const titleId = `entry-${entry.youtube_id}`}
          <li class="row entry" class:gone={!!entry.removed_at}>
            <span class="pos muted small">#{entry.position}</span>
            <div class="grow">
              {#if entry.video_id}
                {@const videoId = entry.video_id}
                <button type="button" class="link-btn entry-title" id={titleId} onclick={() => (openVideoId = videoId)}>
                  {title}
                </button>
              {:else}
                <span class="entry-title" id={titleId}>{title}</span>
              {/if}
              <div class="dots muted small">
                {#if entry.video_type !== 'video'}<span>{VIDEO_TYPES[entry.video_type]}</span>{/if}
                {#if entry.duration}<span>{duration(entry.duration)}</span>{/if}
                {#if entry.live_status && entry.live_status !== 'not_live'}
                  <span>{entry.live_status.replaceAll('_', ' ')}</span>
                {/if}
                <span>seen <Time value={entry.first_seen_at} /></span>
                {#if entry.removed_at}
                  <span class="warn-text">removed from source <Time value={entry.removed_at} /></span>
                {/if}
              </div>
            </div>
            <div class="entry-actions">
              <StatusBadge status={entry.status} />
              {#if DOWNLOADABLE.includes(entry.status)}
                <button
                  type="button"
                  class="btn btn-secondary btn-sm"
                  aria-describedby={titleId}
                  disabled={busyEntry === entry.youtube_id}
                  onclick={() => downloadEntry(entry)}
                >
                  Download
                </button>
              {/if}
              <a
                class="ext-link"
                href="https://www.youtube.com/watch?v={encodeURIComponent(entry.youtube_id)}"
                target="_blank"
                rel="noopener noreferrer"
                aria-label="Open {title} on YouTube">↗</a
              >
            </div>
          </li>
        {/each}
      </ul>
    {/if}
    <Pagination
      page={filters.page}
      total={entries.data.total}
      perPage={entries.data.per_page || PER_PAGE}
      label="Inventory pages"
      onpage={(page) => updateQuery({ page: page > 1 ? page : null })}
    />
  {:else if entries.loading}
    <p class="loading-line"><span class="spinner"></span> Loading inventory…</p>
  {/if}
</section>

{#if openVideoId}
  <VideoDialog id={openVideoId} onchange={videoChanged} onclose={() => (openVideoId = null)} />
{/if}

<style>
  .head {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin-bottom: var(--space-4);
  }

  .head .page-head {
    margin-bottom: 0;
  }

  .overview {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr));
    gap: var(--space-3);
    margin-bottom: var(--space-6);
  }

  .overview .section-title {
    margin-bottom: var(--space-2);
  }

  .entry {
    flex-wrap: wrap;
  }

  .entry .grow {
    flex-basis: 220px;
  }

  .entry.gone .entry-title {
    text-decoration: line-through;
    text-decoration-color: var(--text-muted);
  }

  .pos {
    min-width: 2.75rem;
  }

  .entry-title {
    display: block;
    overflow-wrap: anywhere;
  }

  .entry-actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-left: auto;
  }

  @media (max-width: 640px) {
    .entry-actions {
      margin-left: calc(2.75rem + var(--space-3));
    }
  }
</style>
