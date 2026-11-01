<script>
  /** @import { ActivityEvent, EventGroup, EventList, EventQuery } from '../lib/types' */
  import { untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { ACTORS, eventWords } from '../lib/events.js'
  import { hm, JOB_KINDS, rel } from '../lib/format.js'
  import { Loader } from '../lib/loader.svelte.js'
  import { poll } from '../lib/poll.js'
  import { href, router, updateQuery } from '../lib/router.svelte.js'
  import { notify } from '../lib/toasts.svelte.js'
  import { clock } from '../lib/ui.svelte.js'
  import FilterTabs from '../components/FilterTabs.svelte'
  import Icon from '../components/Icon.svelte'

  const PAGE = 50
  /** Pages one poll may fetch to catch up with events that came in faster than it ran. */
  const CATCH_UP = 10
  /** @type {{ value: EventGroup | '', label: string }[]} */
  const GROUPS = [
    { value: '', label: 'All' },
    { value: 'jobs', label: 'Jobs' },
    { value: 'youtube', label: 'YouTube' },
    { value: 'app', label: 'App' }
  ]

  /** @param {string | undefined} value */
  function idParam(value) {
    const n = Number(value)
    return Number.isInteger(n) && n > 0 ? n : null
  }

  const group = $derived(GROUPS.find((g) => g.value === router.query.group)?.value ?? '')
  const job = $derived(idParam(router.query.job))
  const video = $derived(idParam(router.query.video))
  const subscription = $derived(idParam(router.query.subscription))
  /** What the list is limited to, as the API names it. @type {EventQuery} */
  const scope = $derived({ job_id: job, video_id: video, subscription_id: subscription, group })

  /** @type {Loader<EventList>} */
  const feed = new Loader()
  let older = $state(false)

  const events = $derived(feed.data?.items ?? [])
  /** What the list is narrowed to, each with a way to clear it. */
  const tokens = $derived.by(() => {
    /** @type {{ key: string, label: string }[]} */
    const list = []
    if (job != null) {
      const kind = events.find((event) => event.job_id === job)?.job_kind
      list.push({ key: 'job', label: kind ? `${JOB_KINDS[kind]} job #${job}` : `Job #${job}` })
    }
    if (video != null) {
      list.push({ key: 'video', label: named('Video', events.find((event) => event.video?.id === video)?.video, video) })
    }
    if (subscription != null) {
      const found = events.find((event) => event.subscription?.id === subscription)?.subscription
      list.push({ key: 'subscription', label: named('Subscription', found, subscription) })
    }
    return list
  })

  /**
   * How a token names a video or subscription: by its title once an event has shown it, or its number
   * until then.
   * @param {string} word
   * @param {{ title: string | null } | null | undefined} found
   * @param {number} id
   */
  function named(word, found, id) {
    if (!found) return `${word} #${id}`
    return found.title ? `${word} “${found.title}”` : `Removed ${word.toLowerCase()}`
  }

  /**
   * What an event is about: its video, else its subscription, else a library rescan. One whose row
   * is gone says so and has no link.
   * @param {ActivityEvent} event
   * @returns {{ title: string, link: string | null } | null}
   */
  function itemOf(event) {
    if (event.video) {
      const { id, title } = event.video
      return title ? { title, link: href(`/video/${id}`) } : { title: 'Removed video', link: null }
    }
    if (event.subscription) {
      const { id, title } = event.subscription
      return title ? { title, link: href(`/subscriptions/${id}`) } : { title: 'Removed subscription', link: null }
    }
    return event.job_kind === 'scan' ? { title: 'Library rescan', link: null } : null
  }

  /**
   * The newest events. A page is enough on a first load; a poll walks back until it reaches `known`,
   * the newest event already loaded, so a burst of events leaves no gap.
   * @param {EventQuery} q
   * @param {number} known
   */
  async function newest(q, known) {
    /** @type {ActivityEvent[]} */
    const items = []
    /** @type {number | undefined} */
    let before
    /** @type {number | null} */
    let next = null
    for (let pages = 0; pages < CATCH_UP; pages++) {
      const page = await api.events.list({ ...q, before, limit: PAGE })
      items.push(...page.items)
      next = page.next_before
      if (next === null || (page.items.at(-1)?.id ?? 0) <= known) return { items, next, joined: true }
      before = next
    }
    return { items, next, joined: false }
  }

  /**
   * Loads the newest events. A quiet load, a poll, adds them to the pages already loaded; a burst too
   * large to catch up with starts the list over.
   * @param {boolean} quiet
   */
  function load(quiet) {
    const q = scope
    const known = (quiet && feed.data?.items[0]?.id) || Infinity
    return feed.run(
      async () => {
        const { items, next, joined } = await newest(q, known)
        // read after the requests: an "Older" page may have been added meanwhile
        const have = quiet && joined ? (feed.data?.items ?? []) : []
        if (!have.length) return { items, next_before: next }
        const fresh = new Set(items.map((event) => event.id))
        return {
          items: [...items, ...have.filter((event) => !fresh.has(event.id))],
          next_before: next === null ? null : (feed.data?.next_before ?? null)
        }
      },
      { quiet }
    )
  }

  async function loadOlder() {
    const cursor = feed.data?.next_before
    if (cursor == null || older) return
    const q = scope
    older = true
    try {
      const page = await api.events.list({ ...q, before: cursor, limit: PAGE })
      // the list may have been started over, or limited differently, while the page loaded
      if (q === scope && feed.data?.next_before === cursor) {
        feed.data = { items: [...feed.data.items, ...page.items], next_before: page.next_before }
      }
    } catch (e) {
      notify.error(e)
    } finally {
      older = false
    }
  }

  $effect(() => {
    void scope
    untrack(() => {
      feed.data = undefined
      feed.error = ''
      load(false)
    })
    return poll(() => load(true), 5000, { immediate: false })
  })
</script>

<svelte:head>
  <title>Activity · YouHoard</title>
</svelte:head>

<header class="ph"><h1>Activity</h1></header>

<FilterTabs label="Events" value={group} tabs={GROUPS} onchange={(value) => updateQuery({ group: value })} />

{#if tokens.length}
  <div class="resbar">
    {#each tokens as token (token.key)}
      <span class="token">
        <span class="lbl">{token.label}</span>
        <button type="button" aria-label="Remove filter {token.label}" onclick={() => updateQuery({ [token.key]: '' })}>
          <Icon name="x" />
        </button>
      </span>
    {/each}
  </div>
{/if}

{#if feed.error && !feed.data}
  <div class="empty">
    <b>Couldn't load the activity</b>
    {feed.error}
    <div><button type="button" class="btn sm" onclick={() => load(false)}>Try again</button></div>
  </div>
{:else if feed.data && events.length === 0}
  {#if group || tokens.length}
    <div class="empty"><b>No matches</b>No events match these filters.</div>
  {:else}
    <div class="empty"><b>Nothing here yet</b></div>
  {/if}
{:else if feed.data}
  <table class="tbl q log stack">
    <thead>
      <tr>
        <th class="c-when">When</th>
        <th>Event</th>
        <th class="c-by">By</th>
      </tr>
    </thead>
    <tbody>
      {#each events as event (event.id)}
        {@const item = itemOf(event)}
        {@const who = ACTORS[event.actor]}
        <tr>
          <td class="c-when"><b>{hm(event.at)}</b><span>{rel(event.at, clock.now)}</span></td>
          <td class="c-main keep">
            <div>
              <span class="ttl">{eventWords(event.event, event.reason)}</span>
              {#if item}
                <span class="sep">·</span>
                {#if item.link}
                  <a class="of" href={item.link}>{item.title}</a>
                {:else}
                  <span class="of removed">{item.title}</span>
                {/if}
              {/if}
            </div>
            {#if event.detail}<div class="why">{event.detail}</div>{/if}
            <div class="m-meta">{hm(event.at)} · {rel(event.at, clock.now)} · {who}</div>
          </td>
          <td class="c-by">{who}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if feed.data.next_before !== null}
    <div class="pager">
      <button type="button" class="btn sm" disabled={older} onclick={loadOlder}>Older<Icon name="down" /></button>
    </div>
  {/if}
{:else}
  <p class="muted nothing" role="status">Loading…</p>
{/if}
