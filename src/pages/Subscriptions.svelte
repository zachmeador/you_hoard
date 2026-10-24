<script>
  /** @import { Subscription } from '../lib/types' */
  import { onMount } from 'svelte'
  import { api } from '../lib/api.js'
  import { CONTENT_TYPES, POLICIES, int, interval, plural, policySummary, qualityLabel } from '../lib/format.js'
  import { Loader } from '../lib/loader.svelte.js'
  import { poll } from '../lib/poll.js'
  import { href } from '../lib/router.svelte.js'
  import AddSubscriptionDialog from '../components/AddSubscriptionDialog.svelte'
  import CheckStatus from '../components/CheckStatus.svelte'
  import SubscriptionActions from '../components/SubscriptionActions.svelte'

  /** @type {Loader<{ items: Subscription[] }>} */
  const subs = new Loader()
  let adding = $state(false)

  const anyChecking = $derived(subs.data?.items.some((s) => s.checking) ?? false)

  /** @param {boolean} [quiet] */
  function load(quiet = false) {
    return subs.run(() => api.subscriptions.list(), { quiet })
  }

  onMount(() => {
    load()
  })

  $effect(() => {
    if (anyChecking) return poll(() => load(true), 3000, { immediate: false })
  })

  /** @param {Subscription} updated */
  function replace(updated) {
    const items = subs.data?.items
    if (!items) return
    const i = items.findIndex((s) => s.id === updated.id)
    if (i !== -1) items[i] = updated
    else items.unshift(updated)
  }

  /** @param {number} id */
  function removeItem(id) {
    const items = subs.data?.items
    if (!items) return
    const i = items.findIndex((s) => s.id === id)
    if (i !== -1) items.splice(i, 1)
  }
</script>

<svelte:head>
  <title>Subscriptions · YouHoard</title>
</svelte:head>

<div class="page-head">
  <div class="cluster">
    <h1 class="page-title">Subscriptions</h1>
    {#if subs.data}<span class="muted">{plural(subs.data.items.length, 'subscription')}</span>{/if}
  </div>
  <button type="button" class="btn btn-primary" onclick={() => (adding = true)}>Add subscription</button>
</div>

{#if subs.error}
  <div class="form-error error-bar" role="alert">
    <span>{subs.error}</span>
    <button type="button" class="btn btn-secondary btn-sm" onclick={() => load()}>Try again</button>
  </div>
{/if}

{#if subs.data}
  {#if subs.data.items.length === 0}
    <div class="empty">
      No subscriptions yet. Subscribe to a channel or playlist to track it and download new uploads automatically.
    </div>
  {:else}
    <div class="sub-grid">
      {#each subs.data.items as sub (sub.id)}
        <article class="panel sub" class:paused={!sub.enabled} aria-labelledby="sub-{sub.id}-title">
          <div class="sub-head">
            <h2 id="sub-{sub.id}-title" class="sub-title"><a href="#/subscriptions/{sub.id}">{sub.title}</a></h2>
            <div class="cluster">
              <span class="badge badge-info">{sub.kind}</span>
              <span class="badge" title={POLICIES[sub.download_policy]?.help}>
                {policySummary(sub.download_policy, sub.recent_count)}
              </span>
              {#if !sub.enabled}<span class="badge badge-muted">Paused</span>{/if}
            </div>
          </div>

          <p class="dots muted small">
            {#if sub.kind === 'playlist' && sub.owner_name}<span>by {sub.owner_name}</span>{/if}
            {#if sub.channel}
              <a href={href('/', { channel: sub.channel.id })}>
                {sub.kind === 'channel' ? 'Show videos' : sub.channel.name}
              </a>
            {/if}
            {#if sub.kind === 'channel'}
              <span>{sub.content_types.map((t) => CONTENT_TYPES[t] ?? t).join(', ') || 'No content types'}</span>
            {/if}
            <span>{sub.quality ? qualityLabel(sub.quality) : 'Default quality'}</span>
            <span>{interval(sub.check_interval_hours)}</span>
          </p>

          <div class="counts">
            <span><strong>{int(sub.counts.entries)}</strong> entries</span>
            <span><strong>{int(sub.counts.archived)}</strong> archived</span>
            <span><strong>{int(sub.counts.queued)}</strong> queued</span>
            <span class:error-text={sub.counts.failed > 0}><strong>{int(sub.counts.failed)}</strong> failed</span>
            <span><strong>{int(sub.counts.not_selected)}</strong> not selected</span>
            <span><strong>{int(sub.counts.removed)}</strong> removed</span>
          </div>

          <CheckStatus {sub} />
          <SubscriptionActions {sub} onupdate={replace} ondeleted={() => removeItem(sub.id)} />
        </article>
      {/each}
    </div>
  {/if}
{:else if subs.loading}
  <p class="loading-line"><span class="spinner"></span> Loading subscriptions…</p>
{/if}

{#if adding}
  <AddSubscriptionDialog onclose={() => (adding = false)} oncreated={replace} />
{/if}

<style>
  .sub-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 440px), 1fr));
    gap: var(--space-3);
  }

  .sub {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    transition: border-color 0.2s, box-shadow 0.2s;
  }

  .sub:hover {
    border-color: var(--terminal-green);
    box-shadow: var(--glow-primary);
  }

  .sub.paused {
    border-style: dashed;
  }

  .sub-head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-1) var(--space-3);
  }

  .sub-title {
    font-size: 0.95rem;
    min-width: 0;
    overflow-wrap: anywhere;
  }
</style>
