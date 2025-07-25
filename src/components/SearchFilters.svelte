<script>
  import { createEventDispatcher } from 'svelte'
  
  export let channels = []
  
  const dispatch = createEventDispatcher()
  
  let searchText = ''
  let selectedStatus = ''
  let selectedChannel = ''
  
  function handleSearch() {
    dispatch('search', searchText.trim())
  }
  
  function handleStatusChange() {
    dispatch('statusFilter', selectedStatus)
  }
  
  function handleChannelChange() {
    dispatch('channelFilter', selectedChannel)
  }
  
  function handleClearFilters() {
    searchText = ''
    selectedStatus = ''
    selectedChannel = ''
    dispatch('clearFilters')
  }
  
  function handleKeydown(event) {
    if (event.key === 'Enter') {
      handleSearch()
    }
  }
</script>

<div class="card mb-6">
  <div class="card-body">
    <div class="filters-row">
      <div class="search-group">
        <input 
          type="text" 
          placeholder="Search videos..." 
          class="search-input"
          bind:value={searchText}
          on:keydown={handleKeydown}
        >
        <button class="btn btn-primary" on:click={handleSearch}>Search</button>
      </div>
      
      <div class="filter-group">
        <select class="filter-select" bind:value={selectedStatus} on:change={handleStatusChange}>
          <option value="">All Status</option>
          <option value="completed">Downloaded</option>
          <option value="downloading">Downloading</option>
          <option value="pending">Pending</option>
          <option value="failed">Failed</option>
        </select>
        
        <select class="filter-select" bind:value={selectedChannel} on:change={handleChannelChange}>
          <option value="">All Channels</option>
          {#each channels as channel}
            <option value={channel.id}>{channel.name}</option>
          {/each}
        </select>
        
        <button class="btn btn-secondary" on:click={handleClearFilters}>Clear</button>
      </div>
    </div>
  </div>
</div>

<style>
  .filters-row {
    display: flex;
    gap: var(--space-4);
    align-items: center;
    flex-wrap: wrap;
  }

  .search-group {
    display: flex;
    gap: var(--space-2);
    flex: 1;
    min-width: 300px;
  }

  .search-input {
    flex: 1;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    color: var(--text-primary);
    font-size: 0.875rem;
    font-family: var(--font-mono);
  }

  .search-input:focus {
    outline: none;
    border-color: var(--terminal-green);
    box-shadow: var(--glow-primary);
  }

  .filter-group {
    display: flex;
    gap: var(--space-2);
    align-items: center;
  }

  .filter-select {
    padding: var(--space-2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    color: var(--text-primary);
    font-size: 0.875rem;
    min-width: 120px;
    font-family: var(--font-mono);
  }

  .filter-select:focus {
    outline: none;
    border-color: var(--terminal-green);
    box-shadow: var(--glow-primary);
  }

  @media (max-width: 768px) {
    .filters-row {
      flex-direction: column;
      align-items: stretch;
    }
    
    .search-group {
      min-width: unset;
    }
  }
</style> 