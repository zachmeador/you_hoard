<script>
  import { initials } from '../lib/format.js'
  import Icon from './Icon.svelte'

  /** @type {{ name?: string, src?: string | null, large?: boolean, playlist?: boolean }} */
  let { name = '', src = null, large = false, playlist = false } = $props()

  let failed = $state('')
</script>

<span class="avatar" class:lg={large} class:pl={playlist} aria-hidden="true">
  {#if playlist}
    <Icon name="playlist" />
  {:else if src && failed !== src}
    <img {src} alt="" loading="lazy" onerror={() => (failed = src ?? '')} />
  {:else}
    {initials(name)}
  {/if}
</span>
