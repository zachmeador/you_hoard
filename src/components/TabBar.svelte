<script>
  import { NAV } from '../lib/nav.js'
  import { queue } from '../lib/queue.svelte.js'
  import { href, matchRoute, router, sectionOf } from '../lib/router.svelte.js'
  import { system } from '../lib/system.svelte.js'
  import Icon from './Icon.svelte'

  const section = $derived(sectionOf(matchRoute(router.path)))
  const problems = $derived(system.problems.join('. '))
</script>

<nav class="tabbar" aria-label="Main">
  {#each NAV as item (item.key)}
    <a href={href(`/${item.key}`)} aria-current={section === item.key ? 'page' : undefined}>
      <Icon name={item.icon} /><span>{item.short}<span class="sr">{item.label.slice(item.short.length)}</span></span>
      {#if item.key === 'queue' && queue.counts.running > 0}
        <span class="badge" role="img" aria-label="{queue.counts.running} running">{queue.counts.running}</span>
      {:else if item.key === 'system' && problems}
        <span class="dot warn" role="img" aria-label={problems} title={problems}></span>
      {/if}
    </a>
  {/each}
</nav>
