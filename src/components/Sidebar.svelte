<script>
  /** @import { Channel, Page } from '../lib/types' */
  import { untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { auth } from '../lib/auth.svelte.js'
  import { bytes, int } from '../lib/format.js'
  import { Loader } from '../lib/loader.svelte.js'
  import { NAV } from '../lib/nav.js'
  import { prefs } from '../lib/prefs.svelte.js'
  import { queue } from '../lib/queue.svelte.js'
  import { href, matchRoute, router, sectionOf } from '../lib/router.svelte.js'
  import { system } from '../lib/system.svelte.js'
  import { openAdd, ui } from '../lib/ui.svelte.js'
  import Icon from './Icon.svelte'
  import Segmented from './Segmented.svelte'

  const PER_PAGE = 100

  const section = $derived(sectionOf(matchRoute(router.path)))
  const activeChannel = $derived(section === 'library' ? router.query.channel : undefined)

  /** @type {Loader<Page<Channel>>} */
  const first = new Loader()
  /** @type {Channel[]} */
  let more = $state([])
  let query = $state('')
  let filter = $state('')
  let generation = 0

  const channels = $derived([...(first.data?.items ?? []), ...more])
  const remaining = $derived(Math.max(0, (first.data?.total ?? 0) - channels.length))

  $effect(() => {
    const value = query.trim()
    const timer = setTimeout(() => (filter = value), 200)
    return () => clearTimeout(timer)
  })

  $effect(() => {
    const q = filter
    const sort = prefs.channelSort
    void ui.channelsVersion
    untrack(() => {
      generation++
      more = []
      first.run(() => api.channels.list({ q, sort, per_page: PER_PAGE }))
    })
  })

  async function loadMore() {
    const mine = generation
    const page = Math.floor(channels.length / PER_PAGE) + 1
    try {
      const res = await api.channels.list({ q: filter, sort: prefs.channelSort, page, per_page: PER_PAGE })
      if (mine === generation) more = [...more, ...res.items]
    } catch {
      // the next click tries again
    }
  }
</script>

<aside class="side" aria-label="Sidebar">
  <button type="button" class="side-add" title="Add a video, channel or playlist (A)" onclick={() => openAdd()}>
    <Icon name="plus" /><span>Add</span>
  </button>
  <nav class="nav" aria-label="Main">
    {#each NAV as item (item.key)}
      <a href={href(`/${item.key}`)} aria-current={section === item.key ? 'page' : undefined}>
        <Icon name={item.icon} /><span>{item.label}</span>
        <span class="n">
          {#if item.key === 'queue' && queue.counts.running > 0}
            <span class="nrun">{queue.counts.running} running</span>
          {:else if item.key === 'system' && system.problems.length > 0}
            <span class="dot warn" role="img" aria-label={system.problems.join('. ')} title={system.problems.join('. ')}></span>
          {/if}
        </span>
      </a>
    {/each}
  </nav>
  <div class="side-sec">
    <div class="side-h">
      <span class="label">Channels</span>
      {#if first.data}<span class="count">{int(first.data.total)}</span>{/if}
      <Segmented
        label="Sort channels"
        value={prefs.channelSort}
        options={[
          { value: 'name', label: 'A–Z' },
          { value: 'size', label: 'Size' }
        ]}
        onchange={(value) => prefs.setChannelSort(value === 'size' ? 'size' : 'name')}
      />
    </div>
    <label class="chan-filter">
      <Icon name="search" />
      <input type="search" placeholder="Filter channels" aria-label="Filter channels" bind:value={query} />
    </label>
    <ul class="chan-list">
      {#each channels as channel (channel.id)}
        <li>
          <a
            href={href('/library', { channel: channel.id })}
            aria-current={activeChannel === String(channel.id) ? 'true' : undefined}
            title={channel.name}
          >
            <span class="nm">{channel.name}</span>
            <span class="n">{prefs.channelSort === 'size' ? bytes(channel.archived_size) : int(channel.archived_count)}</span>
          </a>
        </li>
      {/each}
      {#if remaining > 0}
        <li class="chan-more">
          <button type="button" onclick={loadMore}>{int(remaining)} more</button>
        </li>
      {/if}
    </ul>
  </div>
  <div class="side-foot">
    <div class="foot-row">
      <span class="who">{auth.username}</span>
      <button
        type="button"
        class="btn icon sm quiet"
        aria-label="Switch to {prefs.theme === 'light' ? 'dark' : 'light'} theme"
        onclick={() => prefs.toggleTheme()}
      >
        <Icon name={prefs.theme === 'light' ? 'moon' : 'sun'} />
      </button>
      <button type="button" class="btn sm quiet" onclick={() => auth.logout()}>Log out</button>
    </div>
  </div>
</aside>
