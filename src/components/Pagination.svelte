<script>
  import { createEventDispatcher } from 'svelte'
  
  export let currentPage = 1
  export let totalPages = 1
  export let totalVideos = 0
  export let perPage = 20
  
  const dispatch = createEventDispatcher()
  
  $: start = ((currentPage - 1) * perPage) + 1
  $: end = Math.min(currentPage * perPage, totalVideos)
  $: pageNumbers = generatePageNumbers(currentPage, totalPages)
  
  function generatePageNumbers(current, total) {
    const pages = []
    const showPages = 5
    let startPage = Math.max(1, current - Math.floor(showPages / 2))
    let endPage = Math.min(total, startPage + showPages - 1)
    
    if (endPage - startPage < showPages - 1) {
      startPage = Math.max(1, endPage - showPages + 1)
    }
    
    for (let i = startPage; i <= endPage; i++) {
      pages.push(i)
    }
    
    return pages
  }
  
  function goToPage(page) {
    if (page >= 1 && page <= totalPages && page !== currentPage) {
      dispatch('pageChange', page)
    }
  }
  
  function goToPrev() {
    if (currentPage > 1) {
      goToPage(currentPage - 1)
    }
  }
  
  function goToNext() {
    if (currentPage < totalPages) {
      goToPage(currentPage + 1)
    }
  }
</script>

<div class="pagination-wrapper">
  <div class="pagination-info">
    <span>Showing {start}-{end} of {totalVideos} videos</span>
  </div>
  <div class="pagination-controls">
    <button 
      class="btn btn-secondary" 
      disabled={currentPage === 1}
      on:click={goToPrev}
    >
      Previous
    </button>
    
    <div class="page-numbers">
      {#each pageNumbers as page}
        <button 
          class="page-number" 
          class:active={page === currentPage}
          on:click={() => goToPage(page)}
        >
          {page}
        </button>
      {/each}
    </div>
    
    <button 
      class="btn btn-secondary" 
      disabled={currentPage >= totalPages}
      on:click={goToNext}
    >
      Next
    </button>
  </div>
</div>

<style>
  .pagination-wrapper {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-4) 0;
    border-top: 1px solid var(--border);
  }

  .pagination-controls {
    display: flex;
    gap: var(--space-2);
    align-items: center;
  }

  .page-numbers {
    display: flex;
    gap: var(--space-1);
    margin: 0 var(--space-2);
  }

  .page-number {
    padding: var(--space-1) var(--space-2);
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-primary);
    border-radius: var(--radius-sm);
    font-size: 0.875rem;
    transition: all 0.2s ease;
    cursor: pointer;
    font-family: var(--font-mono);
  }

  .page-number:hover {
    border-color: var(--terminal-green);
    background: var(--surface-hover);
    box-shadow: var(--glow-primary);
  }

  .page-number.active {
    background: var(--terminal-green);
    border-color: var(--terminal-green);
    color: var(--background);
  }

  .pagination-info {
    font-size: 0.875rem;
    color: var(--text-secondary);
    font-family: var(--font-mono);
  }

  @media (max-width: 768px) {
    .pagination-wrapper {
      flex-direction: column;
      gap: var(--space-3);
    }
  }
</style> 