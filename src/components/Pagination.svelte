<script>
  import { int } from '../lib/format.js'

  /** @type {{ page: number, total: number, perPage: number, onpage: (page: number) => void, label?: string }} */
  let { page, total, perPage, onpage, label = 'Pages' } = $props()

  const pages = $derived(Math.max(1, Math.ceil(total / perPage)))
  const from = $derived(total === 0 ? 0 : Math.min(total, (page - 1) * perPage + 1))
  const to = $derived(Math.min(total, page * perPage))
</script>

{#if pages > 1 || page > 1}
  <nav class="pagination" aria-label={label}>
    <span class="muted small">{int(from)}–{int(to)} of {int(total)}</span>
    <div class="pager">
      <button type="button" class="btn btn-secondary btn-sm" aria-label="First page" disabled={page <= 1} onclick={() => onpage(1)}>«</button>
      <button type="button" class="btn btn-secondary btn-sm" disabled={page <= 1} onclick={() => onpage(page - 1)}>
        <span aria-hidden="true">‹</span> Previous
      </button>
      <span class="small nowrap">Page {page} / {pages}</span>
      <button type="button" class="btn btn-secondary btn-sm" disabled={page >= pages} onclick={() => onpage(page + 1)}>
        Next <span aria-hidden="true">›</span>
      </button>
      <button type="button" class="btn btn-secondary btn-sm" aria-label="Last page" disabled={page >= pages} onclick={() => onpage(pages)}>»</button>
    </div>
  </nav>
{/if}

<style>
  .pagination {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2) var(--space-4);
    margin-top: var(--space-4);
  }

  .pager {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  @media (max-width: 640px) {
    .pagination {
      justify-content: center;
    }
  }
</style>
