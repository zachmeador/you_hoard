<script>
  import Icon from './Icon.svelte'

  /** @type {{ src: string | null }} */
  let { src } = $props()

  let failed = $state('')
</script>

<div class="plate">
  {#if src && failed !== src}
    <img {src} alt="" loading="lazy" onerror={() => (failed = src ?? '')} />
  {:else}
    <Icon name="play" class="empty" />
  {/if}
</div>
