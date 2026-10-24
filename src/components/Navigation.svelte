<script>
  import { auth } from '../lib/auth.svelte.js'
  import { queue } from '../lib/queue.svelte.js'
  import { router } from '../lib/router.svelte.js'
  import { ui } from '../lib/ui.svelte.js'

  const LINKS = [
    { path: '/', label: 'Library' },
    { path: '/channels', label: 'Channels' },
    { path: '/subscriptions', label: 'Subscriptions' },
    { path: '/queue', label: 'Queue' },
    { path: '/settings', label: 'Settings' }
  ]

  const DUMPSTER_EMOJIS = ['🗑️', '🪣', '♻️', '🚮', '🗂️']

  /** @type {{ id: number, emoji: string, x: number, y: number, dx: number, dy: number }[]} */
  let particles = $state.raw([])
  /** @type {HTMLAnchorElement | undefined} */
  let logo = $state()
  let coolingDown = false
  let nextId = 0

  function explode() {
    if (coolingDown || !logo || matchMedia('(prefers-reduced-motion: reduce)').matches) return
    coolingDown = true
    setTimeout(() => (coolingDown = false), 1000)

    const rect = logo.getBoundingClientRect()
    const x = rect.left + rect.width / 2
    const y = rect.top + rect.height / 2
    const count = 8
    const batch = Array.from({ length: count }, (_, i) => {
      const angle = (i / count) * 2 * Math.PI + (Math.random() - 0.5) * 0.5
      const distance = 80 + Math.random() * 40
      return {
        id: nextId++,
        emoji: DUMPSTER_EMOJIS[Math.floor(Math.random() * DUMPSTER_EMOJIS.length)],
        x,
        y,
        dx: Math.cos(angle) * distance,
        dy: Math.sin(angle) * distance - Math.random() * 30
      }
    })
    particles = [...particles, ...batch]
    const ids = new Set(batch.map((p) => p.id))
    setTimeout(() => (particles = particles.filter((p) => !ids.has(p.id))), 2000)
  }
</script>

<header class="navbar">
  <div class="nav-container">
    <a href="#/" class="nav-logo" bind:this={logo} onmouseenter={explode}>YouHoard</a>

    <nav class="nav-menu" aria-label="Main">
      {#each LINKS as link (link.path)}
        {@const current = router.path === link.path}
        {@const badge = link.label === 'Queue' && queue.active > 0}
        <a
          href="#{link.path}"
          class="nav-link"
          class:active={current || (link.path !== '/' && router.path.startsWith(`${link.path}/`))}
          aria-current={current ? 'page' : undefined}
          aria-describedby={badge ? 'queue-activity' : undefined}
        >
          {link.label}
          {#if badge}
            <span class="nav-badge" class:running={queue.counts.running > 0} aria-hidden="true">{queue.active}</span>
          {/if}
        </a>
      {/each}
    </nav>
    <span id="queue-activity" hidden>{queue.counts.running} running, {queue.counts.queued} queued</span>

    <div class="nav-actions">
      <button type="button" class="btn btn-primary btn-sm" onclick={() => (ui.addVideoOpen = true)}>
        <span aria-hidden="true">+</span> Add video
      </button>
      {#if auth.username}<span class="user">{auth.username}</span>{/if}
      <button type="button" class="btn btn-ghost btn-sm" onclick={() => auth.logout()}>Log out</button>
    </div>
  </div>
</header>

{#each particles as p (p.id)}
  <span
    class="emoji-particle"
    aria-hidden="true"
    style:left="{p.x}px"
    style:top="{p.y}px"
    style:--random-x="{p.dx}px"
    style:--random-y="{p.dy}px">{p.emoji}</span
  >
{/each}

<style>
  .navbar {
    background: rgb(26 26 26 / 0.95);
    border-bottom: 1px solid var(--border);
    box-shadow: var(--shadow-sm);
    position: sticky;
    top: 0;
    z-index: 100;
    backdrop-filter: blur(10px);
  }

  .nav-container {
    max-width: var(--content-width);
    margin: 0 auto;
    padding: 0 var(--space-4);
    display: flex;
    align-items: center;
    gap: var(--space-6);
    height: 56px;
  }

  .nav-logo {
    font-size: 1.35rem;
    font-weight: 700;
    color: var(--terminal-green);
    text-decoration: none;
    transition: transform 0.3s ease, text-shadow 0.3s ease;
    text-shadow: 0 0 10px var(--primary-glow);
    font-family: var(--font-mono);
  }

  .nav-logo:hover {
    text-decoration: none;
    text-shadow: 0 0 20px var(--primary-glow);
    transform: scale(1.05);
  }

  .nav-menu {
    display: flex;
    gap: var(--space-6);
    flex: 1;
    min-width: 0;
  }

  .nav-link {
    color: var(--text-secondary);
    font-weight: 500;
    transition: color 0.2s, text-shadow 0.2s;
    position: relative;
    padding: var(--space-2) 0;
    white-space: nowrap;
  }

  .nav-link:hover,
  .nav-link.active {
    color: var(--terminal-green);
    text-decoration: none;
    text-shadow: 0 0 5px var(--primary-glow);
  }

  .nav-link::after {
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    width: 0;
    height: 1px;
    background: var(--terminal-green);
    transition: width 0.3s ease;
    box-shadow: 0 0 5px var(--primary-glow);
  }

  .nav-link:hover::after,
  .nav-link.active::after {
    width: 100%;
  }

  .nav-badge {
    display: inline-block;
    min-width: 1.3rem;
    margin-left: 0.3rem;
    padding: 0 0.35rem;
    border: 1px solid rgb(255 170 0 / 0.5);
    border-radius: 999px;
    color: var(--warning);
    font-size: 0.6875rem;
    font-weight: 700;
    line-height: 1.45;
    text-align: center;
    text-shadow: none;
    vertical-align: 1px;
  }

  .nav-badge.running {
    color: var(--info);
    border-color: rgb(0 170 255 / 0.55);
    box-shadow: 0 0 8px rgb(0 170 255 / 0.35);
  }

  .nav-actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-left: auto;
  }

  .user {
    margin-left: var(--space-2);
    color: var(--text-muted);
    font-size: 0.75rem;
  }

  @media (max-width: 1100px) {
    .user {
      display: none;
    }
  }

  .emoji-particle {
    position: fixed;
    pointer-events: none;
    font-size: 1.2rem;
    z-index: 1000;
    translate: -50% -50%;
    animation: fly-away 2s ease-out forwards;
  }

  @keyframes fly-away {
    0% {
      transform: translate(0, 0) scale(1) rotate(0deg);
      opacity: 1;
    }
    100% {
      transform: translate(var(--random-x, 100px), var(--random-y, -100px)) scale(0.2) rotate(360deg);
      opacity: 0;
    }
  }

  @media (max-width: 860px) {
    .nav-container {
      flex-wrap: wrap;
      height: auto;
      gap: 0 var(--space-4);
      padding: var(--space-2) var(--space-3) 0;
    }

    .nav-menu {
      order: 3;
      flex: 1 0 100%;
      gap: var(--space-4);
      overflow-x: auto;
      scrollbar-width: none;
    }

    .nav-menu::-webkit-scrollbar {
      display: none;
    }
  }
</style>
