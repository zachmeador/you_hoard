<script>
  /** @import { Subscription } from '../lib/types' */
  import { untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { Loader } from '../lib/loader.svelte.js'
  import { poll } from '../lib/poll.js'
  import { queue } from '../lib/queue.svelte.js'
  import { checkNow, removeSubscription, setEnabled } from '../lib/subactions.js'
  import { openAdd, ui } from '../lib/ui.svelte.js'
  import Icon from '../components/Icon.svelte'
  import SearchField from '../components/SearchField.svelte'
  import SelectField from '../components/SelectField.svelte'
  import SubscriptionRow from '../components/SubscriptionRow.svelte'

  /** @type {Loader<{ items: Subscription[] }>} */
  const subs = new Loader()
  let query = $state('')
  let kind = $state('')
  let policy = $state('')
  let status = $state('')

  const all = $derived(subs.data?.items ?? [])
  const problems = $derived(all.filter(hasProblem))
  const checking = $derived(all.some((s) => s.checking))
  const list = $derived(
    all.filter((s) => {
      if (query.trim() && !s.title.toLowerCase().includes(query.trim().toLowerCase())) return false
      if (kind && s.kind !== kind) return false
      if (policy && s.download_policy !== policy) return false
      if (status === 'on' && !s.enabled) return false
      if (status === 'off' && s.enabled) return false
      if (status === 'problems' && !hasProblem(s)) return false
      return true
    })
  )
  const filtered = $derived(Boolean(query.trim() || kind || policy || status))

  /** @param {Subscription} s */
  function hasProblem(s) {
    return s.counts.failed > 0 || s.last_check?.status === 'failed'
  }

  $effect(() => {
    void ui.subscriptionsVersion
    void queue.signature
    untrack(() => subs.run(() => api.subscriptions.list(), { quiet: !!subs.data }))
  })

  $effect(() => {
    if (!checking) return
    return poll(() => subs.run(() => api.subscriptions.list(), { quiet: true }), 3000, { immediate: false })
  })

  /** @param {Subscription} sub @param {boolean} enabled */
  async function toggle(sub, enabled) {
    await setEnabled(sub, enabled)
    await subs.run(() => api.subscriptions.list(), { quiet: true })
  }

  /** @param {Subscription} sub @param {boolean} full */
  async function check(sub, full) {
    if (await checkNow(sub, full)) await subs.run(() => api.subscriptions.list(), { quiet: true })
  }

  /** @param {Subscription} sub */
  async function remove(sub) {
    if (await removeSubscription(sub)) await subs.run(() => api.subscriptions.list(), { quiet: true })
  }
</script>

<svelte:head>
  <title>Subscriptions · YouHoard</title>
</svelte:head>

<header class="ph">
  <h1>Subscriptions</h1>
  <div class="ph-r">
    <button type="button" class="btn" onclick={() => openAdd()}><Icon name="plus" />Add subscription</button>
  </div>
</header>

<div class="toolbar" style="padding-bottom: 10px">
  <SearchField label="Filter subscriptions" placeholder="Filter sources" bind:value={query} />
  <div class="filters">
    <SelectField
      label="Kind"
      value={kind}
      options={[
        { value: '', label: 'All' },
        { value: 'channel', label: 'Channels' },
        { value: 'playlist', label: 'Playlists' }
      ]}
      onchange={(value) => (kind = value)}
    />
    <SelectField
      label="Policy"
      value={policy}
      options={[
        { value: '', label: 'Any' },
        { value: 'none', label: 'Track only' },
        { value: 'new', label: 'New uploads' },
        { value: 'recent', label: 'Latest N' },
        { value: 'all', label: 'Everything' }
      ]}
      onchange={(value) => (policy = value)}
    />
    <SelectField
      label="State"
      value={status}
      options={[
        { value: '', label: `Any (${all.length})` },
        { value: 'on', label: `Enabled (${all.filter((s) => s.enabled).length})` },
        { value: 'off', label: `Paused (${all.filter((s) => !s.enabled).length})` },
        { value: 'problems', label: `Has problems (${problems.length})` }
      ]}
      onchange={(value) => (status = value)}
    />
  </div>
</div>

{#if subs.error}
  <div class="empty"><b>Couldn't load subscriptions</b>{subs.error}</div>
{:else if subs.data && all.length === 0}
  <div class="empty">
    <b>No subscriptions yet</b>
    <button type="button" class="btn" onclick={() => openAdd()}><Icon name="plus" />Add a channel or playlist</button>
  </div>
{:else if subs.data && list.length === 0}
  <div class="empty"><b>No matches</b>No subscriptions match these filters.</div>
{:else if subs.data}
  <table class="tbl subs stack">
    <thead>
      <tr>
        <th class="c-src">Source</th>
        <th class="c-pol">Policy</th>
        <th class="c-hold">Archived</th>
        <th class="c-last">Last check</th>
        <th class="c-next">Next</th>
        <th class="c-on">On</th>
        <th class="c-act"><span class="sr">Actions</span></th>
      </tr>
    </thead>
    <tbody>
      {#each list as sub (sub.id)}
        <SubscriptionRow
          {sub}
          ontoggle={(enabled) => toggle(sub, enabled)}
          oncheck={(full) => check(sub, full)}
          onremove={() => remove(sub)}
        />
      {/each}
    </tbody>
  </table>
  {#if filtered}<p class="tfoot">{list.length} of {all.length} sources shown</p>{/if}
{/if}
