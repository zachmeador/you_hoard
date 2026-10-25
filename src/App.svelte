<script>
  import { onMount, untrack } from 'svelte'
  import { auth } from './lib/auth.svelte.js'
  import { poll } from './lib/poll.js'
  import { queue } from './lib/queue.svelte.js'
  import { matchRoute, router } from './lib/router.svelte.js'
  import { librarySettings } from './lib/settings.svelte.js'
  import { system } from './lib/system.svelte.js'
  import { focusSearch, openAdd, ui } from './lib/ui.svelte.js'
  import AddDialog from './components/AddDialog.svelte'
  import ConfirmHost from './components/ConfirmHost.svelte'
  import Sidebar from './components/Sidebar.svelte'
  import TabBar from './components/TabBar.svelte'
  import Toasts from './components/Toasts.svelte'
  import TopBar from './components/TopBar.svelte'
  import Auth from './pages/Auth.svelte'
  import Library from './pages/Library.svelte'
  import NotFound from './pages/NotFound.svelte'
  import Queue from './pages/Queue.svelte'
  import SubscriptionDetail from './pages/SubscriptionDetail.svelte'
  import Subscriptions from './pages/Subscriptions.svelte'
  import System from './pages/System.svelte'
  import Video from './pages/Video.svelte'

  const route = $derived(matchRoute(router.path))
  const running = $derived(queue.counts.running > 0)

  onMount(() => {
    auth.check()
  })

  $effect(() => {
    if (auth.phase !== 'ready') {
      untrack(() => (ui.addOpen = false))
      return
    }
    untrack(() => librarySettings.load().catch(() => {}))
    return poll(() => system.refresh(), 60_000)
  })

  $effect(() => {
    if (auth.phase !== 'ready') return
    return poll(() => queue.refresh(), running ? 2000 : 5000)
  })

  /** @param {KeyboardEvent} event */
  function onkeydown(event) {
    if (auth.phase !== 'ready' || event.metaKey || event.ctrlKey || event.altKey) return
    const target = event.target
    const typing =
      target instanceof HTMLElement &&
      (target.isContentEditable || /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName))
    if (typing || document.querySelector('dialog[open]')) return
    if (event.key === '/') {
      event.preventDefault()
      focusSearch()
    } else if (event.key === 'a') {
      event.preventDefault()
      openAdd()
    }
  }
</script>

<svelte:window {onkeydown} />

{#if auth.phase === 'ready'}
  <div class="app">
    <Sidebar />
    <TopBar />
    <main class="main" id="main">
      {#key router.path}
        {#if route.name === 'library'}
          <Library />
        {:else if route.name === 'video'}
          <Video id={route.id} />
        {:else if route.name === 'subscriptions'}
          <Subscriptions />
        {:else if route.name === 'subscription'}
          <SubscriptionDetail id={route.id} />
        {:else if route.name === 'queue'}
          <Queue />
        {:else if route.name === 'system'}
          <System />
        {:else}
          <NotFound />
        {/if}
      {/key}
    </main>
    <TabBar />
  </div>
  {#if ui.addOpen}
    {#key ui.addSeq}
      <AddDialog />
    {/key}
  {/if}
{:else if auth.phase === 'setup' || auth.phase === 'login'}
  <Auth mode={auth.phase} />
{:else if auth.phase === 'offline'}
  <div class="splash">
    <p class="error-text" role="alert">Can't reach the server: {auth.error}</p>
    <button type="button" class="btn" onclick={() => auth.check()}>Try again</button>
  </div>
{:else}
  <div class="splash" aria-busy="true">
    <p class="muted">Loading…</p>
  </div>
{/if}

<ConfirmHost />
<Toasts />
