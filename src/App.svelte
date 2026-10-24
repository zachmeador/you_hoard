<script>
  import { onMount, untrack } from 'svelte'
  import { auth } from './lib/auth.svelte.js'
  import { poll } from './lib/poll.js'
  import { queue } from './lib/queue.svelte.js'
  import { matchRoute, router } from './lib/router.svelte.js'
  import { librarySettings } from './lib/settings.svelte.js'
  import { ui } from './lib/ui.svelte.js'
  import AddVideoDialog from './components/AddVideoDialog.svelte'
  import ConfirmHost from './components/ConfirmHost.svelte'
  import Navigation from './components/Navigation.svelte'
  import Toasts from './components/Toasts.svelte'
  import Auth from './pages/Auth.svelte'
  import Channels from './pages/Channels.svelte'
  import Library from './pages/Library.svelte'
  import NotFound from './pages/NotFound.svelte'
  import Queue from './pages/Queue.svelte'
  import Settings from './pages/Settings.svelte'
  import SubscriptionDetail from './pages/SubscriptionDetail.svelte'
  import Subscriptions from './pages/Subscriptions.svelte'

  const route = $derived(matchRoute(router.path))

  onMount(() => {
    auth.check()
  })

  $effect(() => {
    if (auth.phase !== 'ready') {
      untrack(() => (ui.addVideoOpen = false))
      return
    }
    untrack(() => librarySettings.load().catch(() => {}))
    return poll(() => queue.refresh(), 5000)
  })
</script>

{#if auth.phase === 'ready'}
  <Navigation />
  <main class="app-main">
    {#key router.path}
      {#if route.name === 'library'}
        <Library />
      {:else if route.name === 'channels'}
        <Channels />
      {:else if route.name === 'subscriptions'}
        <Subscriptions />
      {:else if route.name === 'subscription'}
        <SubscriptionDetail id={route.id} />
      {:else if route.name === 'queue'}
        <Queue />
      {:else if route.name === 'settings'}
        <Settings />
      {:else}
        <NotFound />
      {/if}
    {/key}
  </main>
  {#if ui.addVideoOpen}
    <AddVideoDialog onclose={() => (ui.addVideoOpen = false)} />
  {/if}
{:else if auth.phase === 'setup' || auth.phase === 'login'}
  <Auth mode={auth.phase} />
{:else if auth.phase === 'offline'}
  <div class="splash">
    <p class="nav-brand">YouHoard</p>
    <p class="error-text">Can't reach the server: {auth.error}</p>
    <button type="button" class="btn btn-secondary" onclick={() => auth.check()}>Try again</button>
  </div>
{:else}
  <div class="splash" aria-busy="true">
    <p class="nav-brand">YouHoard</p>
    <p class="muted"><span class="spinner"></span> Loading…</p>
  </div>
{/if}

<ConfirmHost />
<Toasts />

<style>
  .splash {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-4);
    min-height: 100vh;
    padding: var(--space-4);
    text-align: center;
  }

  .nav-brand {
    font-size: 2rem;
    font-weight: 700;
    color: var(--terminal-green);
    text-shadow: 0 0 10px var(--primary-glow);
  }
</style>
