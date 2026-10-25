<script>
  /** @import { Overrides } from '../lib/overrides.js' */
  /** @import { DownloadPolicy, Entry, Page, Subscription, VideoType } from '../lib/types' */
  import { untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { dmy, int, interval, rel, whenShort } from '../lib/format.js'
  import { ENTRIES_PER_PAGE, loadEntries } from '../lib/entries.js'
  import { Loader } from '../lib/loader.svelte.js'
  import { overridesOf, subscriptionOverrides } from '../lib/overrides.js'
  import { poll } from '../lib/poll.js'
  import { queue } from '../lib/queue.svelte.js'
  import { href, navigate, pageParam, router, updateQuery } from '../lib/router.svelte.js'
  import { librarySettings } from '../lib/settings.svelte.js'
  import { checkNow, removeSubscription, setEnabled } from '../lib/subactions.js'
  import { notify } from '../lib/toasts.svelte.js'
  import { clock, subscriptionsChanged, ui } from '../lib/ui.svelte.js'
  import Avatar from '../components/Avatar.svelte'
  import FieldSelect from '../components/FieldSelect.svelte'
  import FilterTabs from '../components/FilterTabs.svelte'
  import HoldBar from '../components/HoldBar.svelte'
  import Icon from '../components/Icon.svelte'
  import InventoryTable from '../components/InventoryTable.svelte'
  import LastCheck from '../components/LastCheck.svelte'
  import OverrideFields from '../components/OverrideFields.svelte'
  import Pager from '../components/Pager.svelte'
  import PolicyFields from '../components/PolicyFields.svelte'
  import SearchField from '../components/SearchField.svelte'
  import SelectField from '../components/SelectField.svelte'

  /**
   * @typedef {{
   *   policy: DownloadPolicy,
   *   recentCount: number,
   *   types: VideoType[],
   *   interval: number,
   *   overrides: Overrides
   * }} Draft
   */

  /** @type {{ id: number }} */
  let { id } = $props()

  /** @type {Loader<Subscription>} */
  const sub = new Loader()
  /** @type {Loader<Page<Entry>>} */
  const entries = new Loader()
  let draft = $state(/** @type {Draft | null} */ (null))
  let dirty = $state(false)
  let saving = $state(false)
  let busyEntry = $state('')
  let search = $state(untrack(() => router.query.q ?? ''))

  const filters = $derived({
    status: router.query.status ?? '',
    type: router.query.type ?? '',
    q: router.query.q ?? '',
    page: pageParam(router.query.page)
  })
  const s = $derived(sub.data)
  const items = $derived(entries.data?.items ?? [])
  const pages = $derived(Math.max(1, Math.ceil((entries.data?.total ?? 0) / ENTRIES_PER_PAGE)))
  const intervals = $derived.by(() => {
    const hours = librarySettings.options.check_intervals
    const all = draft && !hours.includes(draft.interval) ? [...hours, draft.interval].sort((a, b) => a - b) : hours
    return all.map((h) => ({ value: h, label: interval(h) }))
  })
  const valid = $derived(!draft || s?.kind !== 'channel' || draft.types.length > 0)
  const tabs = $derived(
    s
      ? [
          { value: '', label: 'All', count: s.counts.entries },
          { value: 'archived', label: 'Archived', count: s.counts.archived },
          { value: 'queued', label: 'Queued', count: s.counts.queued },
          { value: 'failed', label: 'Failed', count: s.counts.failed },
          { value: 'not_selected', label: 'Not selected', count: s.counts.not_selected },
          { value: 'removed', label: 'Removed from source', count: s.counts.removed, gone: true }
        ]
      : []
  )

  /** @param {Subscription} subscription @returns {Draft} */
  function draftOf(subscription) {
    return {
      policy: subscription.download_policy,
      recentCount: subscription.recent_count,
      types: [...subscription.content_types],
      interval: subscription.check_interval_hours,
      overrides: overridesOf(subscription)
    }
  }

  function loadSub(quiet = true) {
    return sub.run(() => api.subscriptions.get(id), { quiet })
  }

  /** @param {boolean} quiet */
  function loadList(quiet) {
    const f = filters
    return entries.run(() => loadEntries(id, f), { quiet })
  }

  let lastKey = ''
  $effect(() => {
    const f = filters
    const version = ui.subscriptionsVersion
    void queue.signature
    const key = JSON.stringify(f) + version
    untrack(() => {
      const quiet = key === lastKey
      lastKey = key
      sub.run(() => api.subscriptions.get(id), { quiet: !!sub.data })
      entries.run(() => loadEntries(id, f), { quiet })
    })
  })

  $effect(() => {
    if (!s?.checking) return
    return poll(() => Promise.all([loadSub(true), loadList(true)]), 3000, { immediate: false })
  })

  $effect(() => {
    const current = sub.data
    if (current && !dirty) untrack(() => (draft = draftOf(current)))
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

  function markDirty() {
    dirty = true
  }

  function discard() {
    if (sub.data) draft = draftOf(sub.data)
    dirty = false
  }

  async function save() {
    const d = draft
    const current = sub.data
    if (!d || !current) return
    saving = true
    try {
      const updated = await api.subscriptions.update(id, {
        download_policy: d.policy,
        recent_count: Math.min(1000, Math.max(1, Math.round(Number(d.recentCount) || 1))),
        ...(current.kind === 'channel' ? { content_types: d.types } : {}),
        check_interval_hours: d.interval,
        ...subscriptionOverrides(d.overrides)
      })
      sub.data = updated
      dirty = false
      draft = draftOf(updated)
      notify.success('Subscription saved')
      subscriptionsChanged()
    } catch (e) {
      notify.error(e)
    } finally {
      saving = false
    }
  }

  /** @param {boolean} enabled */
  async function toggle(enabled) {
    if (!s) return
    const updated = await setEnabled(s, enabled)
    if (updated) sub.data = updated
    else await loadSub()
  }

  /** @param {boolean} full */
  async function check(full) {
    if (!s) return
    if (await checkNow(s, full)) await loadSub()
  }

  async function remove() {
    if (s && (await removeSubscription(s))) navigate('/subscriptions')
  }

  /** @param {Entry} entry */
  async function downloadEntry(entry) {
    busyEntry = entry.youtube_id
    try {
      const res = await api.subscriptions.downloadEntry(id, entry.youtube_id)
      entry.status = 'queued'
      entry.video_id = res.video_id
      notify.success(`Queued “${entry.title ?? entry.youtube_id}”`)
      queue.refresh().catch(() => {})
      loadSub()
    } catch (e) {
      notify.error(e)
    } finally {
      busyEntry = ''
    }
  }

  /** @param {number} page */
  function goTo(page) {
    updateQuery({ page: page > 1 ? page : null })
    window.scrollTo({ top: 0 })
  }
</script>

<svelte:head>
  <title>{s ? `${s.title} · ` : ''}YouHoard</title>
</svelte:head>

{#if sub.error && !s}
  <div class="empty">
    <b>{sub.error}</b>
    <a class="lnk" href={href('/subscriptions')}>Back to subscriptions</a>
  </div>
{:else if s}
  <nav class="crumbs" aria-label="Breadcrumb">
    <a href={href('/subscriptions')}>Subscriptions</a>
    <span class="sep">/</span>
    <span class="cur">{s.title}</span>
  </nav>

  <header class="sd-head">
    <div class="who">
      <Avatar name={s.title} src={s.channel?.avatar_url} large playlist={s.kind === 'playlist'} />
      <div style="min-width: 0">
        <h1>{s.title}</h1>
        <p class="meta">
          <span>{s.kind === 'playlist' ? `Playlist by ${s.owner_name ?? 'unknown'}` : 'Channel'}</span>
          <span class="mono">{s.youtube_id}</span>
          <span>subscribed {dmy(s.created_at)}</span>
          {#if s.channel}
            <a class="lnk" href={href('/library', { channel: s.channel.id })}>Show in library</a>
          {/if}
          <a class="lnk" href={s.url} target="_blank" rel="noopener noreferrer">YouTube ↗</a>
        </p>
      </div>
    </div>
    <div class="acts">
      <label class="enabled">
        <input type="checkbox" class="sw" checked={s.enabled} onchange={(event) => toggle(event.currentTarget.checked)} />
        {s.enabled ? 'Enabled' : 'Paused'}
      </label>
      <button type="button" class="btn" disabled={s.checking} onclick={() => check(false)}>
        <Icon name="refresh" />Check now
      </button>
      <button type="button" class="btn" disabled={s.checking} onclick={() => check(true)}>Full rescan</button>
      <button type="button" class="btn danger" onclick={remove}><Icon name="trash" />Delete</button>
    </div>
  </header>

  <div class="sd-grid">
    <section aria-labelledby="pol-h">
      <h2 class="label" id="pol-h">Download policy</h2>
      {#if draft}
        <PolicyFields
          kind={s.kind}
          bind:policy={draft.policy}
          bind:recentCount={draft.recentCount}
          bind:types={draft.types}
          onchange={markDirty}
        />
        <div class="ovr">
          <OverrideFields bind:value={draft.overrides} onchange={markDirty} />
          <FieldSelect
            label="Check interval"
            value={draft.interval}
            options={intervals}
            onchange={(value) => {
              if (draft) draft.interval = Number(value)
              markDirty()
            }}
          />
        </div>
        <div class="savebar" class:on={dirty}>
          <span>Unsaved changes</span>
          <button type="button" class="btn sm quiet" onclick={discard}>Discard</button>
          <button type="button" class="btn sm primary" disabled={saving || !valid} onclick={save}>Save</button>
        </div>
      {/if}
    </section>
    <section aria-labelledby="chk-h">
      <h2 class="label" id="chk-h">Checks</h2>
      <dl class="chk-block">
        <dt>Last check</dt>
        <dd><LastCheck sub={s} /></dd>
        <dt>Next check</dt>
        <dd>
          {#if !s.enabled}Paused
          {:else if s.next_check_at}{whenShort(s.next_check_at, clock.now)} <span class="muted">({rel(s.next_check_at, clock.now)})</span>
          {:else}—{/if}
        </dd>
      </dl>
    </section>
  </div>

  <section class="holdings" aria-labelledby="hold-h">
    <div class="head">
      <h2 class="label" id="hold-h">Archived</h2>
      <span class="muted"><b>{int(s.counts.archived)}</b> of {int(s.counts.entries)} entries</span>
    </div>
    <HoldBar counts={s.counts} big />
    <div class="legend">
      <span><i></i>Archived</span>
      <span><i class="g"></i>Archived, removed from source</span>
      <span><i class="q"></i>Queued</span>
      <span><i class="f"></i>Failed</span>
      {#if s.counts.deleted}<span><i class="d"></i>Files removed</span>{/if}
      <span><i class="n"></i>Not selected</span>
    </div>
    <FilterTabs
      class="inv-tabs"
      label="Filter entries"
      value={filters.status}
      {tabs}
      onchange={(value) => updateQuery({ status: value })}
    />
  </section>

  <div class="toolbar" style="padding: 10px 0 4px">
    <SearchField label="Search entries" placeholder="Search entries" bind:value={search} />
    <div class="filters">
      <SelectField
        label="Type"
        value={filters.type}
        options={[
          { value: '', label: 'All' },
          { value: 'video', label: 'Videos' },
          { value: 'short', label: 'Shorts' },
          { value: 'live', label: 'Streams' }
        ]}
        onchange={(value) => updateQuery({ type: value })}
      />
    </div>
  </div>

  {#if entries.error}
    <div class="empty"><b>Couldn't load entries</b>{entries.error}</div>
  {:else if entries.data && items.length === 0}
    <div class="empty"><b>No matches</b>No entries match these filters.</div>
  {:else if entries.data}
    <InventoryTable entries={items} kind={s.kind} busy={busyEntry} ondownload={downloadEntry} />
    <Pager label="Inventory pages" page={filters.page} {pages} onpage={goTo} />
  {/if}
{/if}
