<script>
  import { int } from '../lib/format.js'
  import Icon from './Icon.svelte'

  /** @type {{ label: string, page: number, pages: number, onpage: (page: number) => void }} */
  let { label, page, pages, onpage } = $props()
</script>

{#if pages > 1}
  <nav class="pager" aria-label={label}>
    <button type="button" class="btn sm" disabled={page <= 1} onclick={() => onpage(page - 1)}>
      <Icon name="left" />Previous
    </button>
    <span>Page <b>{int(page)}</b> of {int(pages)}</span>
    <button type="button" class="btn sm" disabled={page >= pages} onclick={() => onpage(page + 1)}>
      Next<Icon name="right" />
    </button>
  </nav>
{/if}
