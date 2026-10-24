<script>
  /** @import { Channel, Page } from '../lib/types' */
  import { untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { bytes, compact, int, plural } from '../lib/format.js'
  import { Loader } from '../lib/loader.svelte.js'
  import { href, pageParam, router, updateQuery } from '../lib/router.svelte.js'
  import Pagination from '../components/Pagination.svelte'
  import SearchBox from '../components/SearchBox.svelte'

  const PER_PAGE = 50

  const filters = $derived({ q: router.query.q ?? '', page: pageParam(router.query.page) })
  const search = $derived(filters.q)

  /** @type {Loader<Page<Channel>>} */
  const channels = new Loader()

  /** @param {typeof filters} f */
  function fetchChannels(f) {
    return api.channels.list({ q: f.q, page: f.page, per_page: PER_PAGE })
  }

  $effect(() => {
    const f = filters
    untrack(() => channels.run(() => fetchChannels(f)))
  })
</script>

<svelte:head>
  <title>Channels · YouHoard</title>
</svelte:head>

<div class="page-head">
  <h1 class="page-title">Channels</h1>
  {#if channels.data}<span class="muted">{plural(channels.data.total, 'channel')}</span>{/if}
</div>

<div class="toolbar">
  <SearchBox value={search} label="Search channels" placeholder="Search channels…" onsearch={(q) => updateQuery({ q })} />
</div>

{#if channels.error}
  <div class="form-error error-bar" role="alert">
    <span>{channels.error}</span>
    <button type="button" class="btn btn-secondary btn-sm" onclick={() => channels.run(() => fetchChannels(filters))}>
      Try again
    </button>
  </div>
{/if}

{#if channels.data}
  {#if channels.data.items.length === 0}
    <div class="empty">
      {filters.q ? 'No channels match.' : 'No channels yet. They appear once videos from them are in the library.'}
    </div>
  {:else}
    <ul class="rows" class:stale={channels.loading}>
      {#each channels.data.items as channel (channel.id)}
        <li class="row channel">
          <div class="who">
            <div class="cluster">
              <a class="name" href={href('/', { channel: channel.id })}>{channel.name}</a>
              {#if channel.subscription_id}
                <a class="badge badge-ok" href="#/subscriptions/{channel.subscription_id}">Subscribed</a>
              {/if}
            </div>
            {#if channel.handle || channel.subscriber_count != null}
              <p class="dots muted small">
                {#if channel.handle}<span>{channel.handle}</span>{/if}
                {#if channel.subscriber_count != null}<span>{compact(channel.subscriber_count)} subscribers</span>{/if}
              </p>
            {/if}
          </div>
          <dl class="stats">
            <div>
              <dt>Videos</dt>
              <dd>{int(channel.video_count)}</dd>
            </div>
            <div>
              <dt>Archived</dt>
              <dd>{int(channel.archived_count)}</dd>
            </div>
            <div>
              <dt>Size</dt>
              <dd>{bytes(channel.archived_size)}</dd>
            </div>
          </dl>
          <a
            class="ext-link"
            href={channel.youtube_url}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Open {channel.name} on YouTube">↗</a
          >
        </li>
      {/each}
    </ul>
  {/if}
  <Pagination
    page={filters.page}
    total={channels.data.total}
    perPage={channels.data.per_page || PER_PAGE}
    label="Channel pages"
    onpage={(page) => updateQuery({ page: page > 1 ? page : null })}
  />
{:else if channels.loading}
  <p class="loading-line"><span class="spinner"></span> Loading channels…</p>
{/if}

<style>
  .channel {
    flex-wrap: wrap;
  }

  .who {
    flex: 1 1 240px;
    min-width: 0;
  }

  .name {
    font-weight: 600;
    overflow-wrap: anywhere;
  }

  .stats {
    display: flex;
    gap: var(--space-4);
  }

  .stats div {
    min-width: 4.5rem;
    text-align: right;
  }

  .stats dt {
    font-size: 0.6875rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }

  .stats dd {
    font-weight: 600;
  }

  @media (max-width: 640px) {
    .stats {
      flex: 1;
    }

    .stats div {
      min-width: 0;
      text-align: left;
    }
  }
</style>
