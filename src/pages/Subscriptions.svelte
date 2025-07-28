<script>
  import { onMount } from 'svelte'
  import SubscriptionCard from '../components/SubscriptionCard.svelte'
  import AddSubscriptionModal from '../components/AddSubscriptionModal.svelte'
  import EditSubscriptionModal from '../components/EditSubscriptionModal.svelte'
  import Pagination from '../components/Pagination.svelte'
  
  let subscriptions = []
  let loading = true
  let showAddModal = false
  let showEditModal = false
  let selectedSubscription = null
  let schedulerStatus = null
  let ytdlpStatus = null
  
  // Pagination state
  let currentPage = 1
  let totalPages = 1
  let totalSubscriptions = 0
  let perPage = 12
  
  // Filter state
  let filters = {
    enabledOnly: false,
    search: ''
  }

  // Reactive statement to reload subscriptions when filters or pagination change
  $: if (currentPage || filters) {
    loadSubscriptions()
  }

  onMount(async () => {
    await loadSubscriptions()
    await loadSchedulerStatus()
    await loadYTDLPStatus()
    
    // Poll status every 30 seconds
    setInterval(() => {
      loadSchedulerStatus()
      loadYTDLPStatus()
    }, 30000)
  })

  async function loadSubscriptions() {
    loading = true
    
    try {
      const params = new URLSearchParams({
        page: currentPage,
        per_page: perPage,
        enabled_only: filters.enabledOnly
      })
      
      const response = await window.youHoard.apiCall(`/api/subscriptions?${params}`)
      
      subscriptions = response.subscriptions || []
      totalSubscriptions = response.total || 0
      totalPages = Math.ceil(totalSubscriptions / perPage)
      
    } catch (error) {
      console.error('Failed to load subscriptions:', error)
      window.youHoard.showToast('Failed to load subscriptions', 'error')
      subscriptions = []
    } finally {
      loading = false
    }
  }

  async function loadSchedulerStatus() {
    try {
      schedulerStatus = await window.youHoard.apiCall('/api/subscriptions/scheduler/status')
    } catch (error) {
      console.error('Failed to load scheduler status:', error)
    }
  }

  async function loadYTDLPStatus() {
    try {
      ytdlpStatus = await window.youHoard.apiCall('/api/subscriptions/ytdlp/status')
    } catch (error) {
      console.error('Failed to load yt-dlp status:', error)
    }
  }

  function handleFilterChange() {
    currentPage = 1
    loadSubscriptions()
  }

  function handlePageChange(page) {
    currentPage = page
  }

  function handleAddSubscription() {
    showAddModal = true
  }

  function handleEditSubscription(subscription) {
    selectedSubscription = subscription
    showEditModal = true
  }

  async function handleSubscriptionAction(event) {
    const { action, subscriptionId } = event.detail
    
    try {
      if (action === 'check') {
        window.youHoard.showToast('Checking subscription for new content...', 'warning')
        const result = await window.youHoard.apiCall(`/api/subscriptions/${subscriptionId}/check`, {
          method: 'POST'
        })
        
        if (result.new_videos.length > 0) {
          window.youHoard.showToast(`Found ${result.new_videos.length} new videos!`, 'success')
        } else {
          window.youHoard.showToast('No new videos found', 'warning')
        }
        
        await loadSubscriptions()
      } else if (action === 'pause') {
        await window.youHoard.apiCall(`/api/subscriptions/${subscriptionId}/pause`, {
          method: 'POST'
        })
        window.youHoard.showToast('Subscription paused', 'success')
        await loadSubscriptions()
      } else if (action === 'resume') {
        await window.youHoard.apiCall(`/api/subscriptions/${subscriptionId}/resume`, {
          method: 'POST'
        })
        window.youHoard.showToast('Subscription resumed', 'success')
        await loadSubscriptions()
      } else if (action === 'delete') {
        if (confirm('Are you sure you want to delete this subscription? This action cannot be undone.')) {
          await window.youHoard.apiCall(`/api/subscriptions/${subscriptionId}`, {
            method: 'DELETE'
          })
          window.youHoard.showToast('Subscription deleted', 'success')
          await loadSubscriptions()
        }
      } else if (action === 'edit') {
        const subscription = subscriptions.find(s => s.id === subscriptionId)
        if (subscription) {
          handleEditSubscription(subscription)
        }
      }
    } catch (error) {
      console.error(`Failed to ${action} subscription:`, error)
      window.youHoard.showToast(`Failed to ${action} subscription`, 'error')
    }
  }

  async function handleSubscriptionCreated() {
    showAddModal = false
    await loadSubscriptions()
    await loadSchedulerStatus()
    await loadYTDLPStatus()
    window.youHoard.showToast('Subscription created successfully', 'success')
  }

  async function handleSubscriptionUpdated() {
    showEditModal = false
    selectedSubscription = null
    await loadSubscriptions()
    await loadSchedulerStatus()
    await loadYTDLPStatus()
    window.youHoard.showToast('Subscription updated successfully', 'success')
  }

  function formatNextCheck(nextCheck) {
    if (!nextCheck) return 'Not scheduled'
    
    const date = new Date(nextCheck)
    const now = new Date()
    const diff = date - now
    
    if (diff < 0) return 'Overdue'
    
    const minutes = Math.floor(diff / 60000)
    const hours = Math.floor(minutes / 60)
    const days = Math.floor(hours / 24)
    
    if (days > 0) return `in ${days}d ${hours % 24}h`
    if (hours > 0) return `in ${hours}h ${minutes % 60}m`
    if (minutes > 0) return `in ${minutes}m`
    return 'Soon'
  }
</script>

<div class="page-header">
  <div class="header-content">
    <div>
      <h1 class="page-title">Subscriptions</h1>
      <p class="page-subtitle">Manage your YouTube channel and playlist subscriptions</p>
    </div>
    <button class="btn btn-primary" on:click={handleAddSubscription}>
      <span>+</span> Add Subscription
    </button>
  </div>
</div>

<!-- Status Section -->
<div class="status-section mb-6">
  {#if schedulerStatus}
    <div class="status-card card">
      <div class="card-body">
        <div class="status-content">
          <div class="status-info">
            <h3>Scheduler</h3>
            <div class="status-indicator">
              <span class="status-dot {schedulerStatus.scheduler_running ? 'active' : 'inactive'}"></span>
              {schedulerStatus.scheduler_running ? 'Running' : 'Stopped'}
            </div>
          </div>
          <div class="status-stats">
            <div class="stat">
              <span class="stat-value">{schedulerStatus.total_jobs}</span>
              <span class="stat-label">Jobs</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  {/if}

  {#if ytdlpStatus}
    <div class="status-card card">
      <div class="card-body">
        <div class="status-content">
          <div class="status-info">
            <h3>YouTube Service</h3>
            <div class="status-indicator">
              <span class="status-dot {ytdlpStatus.is_backing_off ? 'inactive' : 'active'}"></span>
              {#if ytdlpStatus.is_backing_off}
                Backing off
              {:else if ytdlpStatus.failure_count > 0}
                Recovering
              {:else}
                Ready
              {/if}
            </div>
          </div>
          <div class="status-stats">
            <div class="stat">
              <span class="stat-value">{ytdlpStatus.failure_count}</span>
              <span class="stat-label">Failures</span>
            </div>
            {#if ytdlpStatus.next_available_in > 0}
              <div class="stat">
                <span class="stat-value">{Math.ceil(ytdlpStatus.next_available_in)}s</span>
                <span class="stat-label">Wait Time</span>
              </div>
            {/if}
          </div>
        </div>
      </div>
    </div>
  {/if}
</div>

<!-- Filters -->
<div class="filters-section card mb-6">
  <div class="card-body">
    <div class="filters-grid">
      <div class="filter-group">
        <label>
          <input 
            type="checkbox" 
            bind:checked={filters.enabledOnly}
            on:change={handleFilterChange}
          />
          Show enabled only
        </label>
      </div>
      <div class="filter-group">
        <input 
          type="text" 
          placeholder="Search subscriptions..."
          bind:value={filters.search}
          on:input={handleFilterChange}
          class="search-input"
        />
      </div>
    </div>
  </div>
</div>

<!-- Subscriptions Grid -->
<div class="subscriptions-grid">
  {#if loading}
    <div class="loading-placeholder" style="grid-column: 1 / -1;">
      <div class="spinner"></div>
      Loading subscriptions...
    </div>
  {:else if subscriptions.length === 0}
    <div class="empty-state" style="grid-column: 1 / -1;">
      <div class="empty-content">
        <h3>No subscriptions found</h3>
        <p>Start by adding your first YouTube channel or playlist subscription.</p>
        <button class="btn btn-primary" on:click={handleAddSubscription}>
          Add Your First Subscription
        </button>
      </div>
    </div>
  {:else}
    {#each subscriptions as subscription (subscription.id)}
      <SubscriptionCard 
        {subscription}
        nextCheckText={formatNextCheck(subscription.next_check)}
        on:action={handleSubscriptionAction}
      />
    {/each}
  {/if}
</div>

{#if totalSubscriptions > perPage}
  <Pagination 
    {currentPage}
    {totalPages}
    {totalSubscriptions}
    {perPage}
    on:pageChange={e => handlePageChange(e.detail)}
  />
{/if}

<!-- Modals -->
<AddSubscriptionModal 
  bind:show={showAddModal}
  on:created={handleSubscriptionCreated}
/>

<EditSubscriptionModal 
  bind:show={showEditModal}
  subscription={selectedSubscription}
  on:updated={handleSubscriptionUpdated}
/>

<style>
  .header-content {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--space-4);
  }

  .status-section {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: var(--space-4);
  }

  .status-card .status-content {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-4);
  }

  .status-info h3 {
    margin: 0 0 var(--space-2) 0;
    color: var(--terminal-green);
    font-family: var(--font-mono);
    font-size: 1.1rem;
  }

  .status-indicator {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-family: var(--font-mono);
  }

  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
  }

  .status-dot.active {
    background: var(--success);
    box-shadow: 0 0 8px var(--success);
  }

  .status-dot.inactive {
    background: var(--error);
    box-shadow: 0 0 8px var(--error);
  }

  .status-stats {
    display: flex;
    gap: var(--space-6);
  }

  .stat {
    text-align: center;
  }

  .stat-value {
    display: block;
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--terminal-green);
    font-family: var(--font-mono);
    line-height: 1;
  }

  .stat-label {
    font-size: 0.75rem;
    color: var(--text-secondary);
    font-family: var(--font-mono);
  }

  .filters-grid {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: var(--space-4);
    align-items: center;
  }

  .filter-group label {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-family: var(--font-mono);
    font-size: 0.875rem;
    cursor: pointer;
  }

  .search-input {
    width: 100%;
    max-width: 300px;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    color: var(--text-primary);
    font-family: var(--font-mono);
    font-size: 0.875rem;
  }

  .search-input:focus {
    outline: none;
    border-color: var(--terminal-green);
    box-shadow: var(--glow-primary);
  }

  .subscriptions-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
    gap: var(--space-6);
    margin-bottom: var(--space-6);
  }

  .loading-placeholder {
    text-align: center;
    color: var(--text-secondary);
    padding: var(--space-8) var(--space-4);
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    font-family: var(--font-mono);
  }

  .empty-state {
    text-align: center;
    padding: var(--space-12) var(--space-4);
  }

  .empty-content h3 {
    color: var(--terminal-green);
    font-family: var(--font-mono);
    margin-bottom: var(--space-2);
  }

  .empty-content p {
    color: var(--text-secondary);
    margin-bottom: var(--space-6);
    font-family: var(--font-mono);
  }

  @media (max-width: 768px) {
    .header-content {
      flex-direction: column;
      align-items: stretch;
    }

    .subscriptions-grid {
      grid-template-columns: 1fr;
    }

    .filters-grid {
      grid-template-columns: 1fr;
      gap: var(--space-3);
    }

    .status-section {
      grid-template-columns: 1fr;
    }

    .status-card .status-content {
      flex-direction: column;
      align-items: flex-start;
      gap: var(--space-3);
    }
  }
</style> 