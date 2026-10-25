<script>
  import { NAV } from '../lib/nav.js'
  import { prefs } from '../lib/prefs.svelte.js'
  import { queue } from '../lib/queue.svelte.js'
  import { href, matchRoute, router, sectionOf } from '../lib/router.svelte.js'
  import { system } from '../lib/system.svelte.js'
  import { focusSearch, openAdd } from '../lib/ui.svelte.js'
  import Icon from './Icon.svelte'

  const section = $derived(sectionOf(matchRoute(router.path)))
  const problems = $derived(system.problems.join('. '))
</script>

<header class="topbar">
  <nav class="topnav" aria-label="Main">
    {#each NAV as item (item.key)}
      <a href={href(`/${item.key}`)} aria-current={section === item.key ? 'page' : undefined}>
        {item.label}
        {#if item.key === 'queue' && queue.counts.running > 0}
          <span class="n">{queue.counts.running}</span>
        {:else if item.key === 'system' && problems}
          <span class="dot warn" role="img" aria-label={problems} title={problems}></span>
        {/if}
      </a>
    {/each}
  </nav>
  <div class="tb-acts">
    <button type="button" aria-label="Search the library" onclick={focusSearch}><Icon name="search" /></button>
    <button
      type="button"
      aria-label="Switch to {prefs.theme === 'light' ? 'dark' : 'light'} theme"
      onclick={() => prefs.toggleTheme()}
    >
      <Icon name={prefs.theme === 'light' ? 'moon' : 'sun'} />
    </button>
    <button type="button" class="tb-add" title="Add a video, channel or playlist (A)" onclick={() => openAdd()}>
      <Icon name="plus" /><span>Add</span>
    </button>
  </div>
</header>
