<script>
  /** @type {{ src: string | null | undefined, alt?: string }} */
  let { src, alt = '' } = $props()

  let failedSrc = $state('')
</script>

{#if src && failedSrc !== src}
  <img class="thumb-img" {src} {alt} loading="lazy" decoding="async" onerror={() => (failedSrc = src ?? '')} />
{:else}
  <div class="thumb-placeholder" aria-hidden="true">▶</div>
{/if}

<style>
  .thumb-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .thumb-placeholder {
    width: 100%;
    height: 100%;
    display: grid;
    place-items: center;
    color: var(--border);
    font-size: 1.75rem;
    background:
      repeating-linear-gradient(135deg, transparent 0 10px, rgb(255 255 255 / 0.02) 10px 20px),
      var(--surface-hover);
  }
</style>
