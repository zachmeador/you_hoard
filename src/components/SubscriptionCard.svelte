<script>
  import { createEventDispatcher } from 'svelte'
  
  export let subscription
  export let nextCheckText = 'Not scheduled'
  
  const dispatch = createEventDispatcher()
  
  function formatDate(dateString) {
    if (!dateString) return 'Never'
    
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now - date
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMins / 60)
    const diffDays = Math.floor(diffHours / 24)
    
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    
    return date.toLocaleDateString()
  }
  
  function formatQuality(quality) {
    if (!quality) return 'Default'
    return quality.replace('p', 'p')
  }
  
  function formatContentTypes(types) {
    if (!types || !Array.isArray(types)) return 'All'
    
    const typeMap = {
      'video': 'Videos',
      'short': 'Shorts', 
      'live': 'Lives'
    }
    
    return types.map(type => typeMap[type] || type).join(', ')
  }
  
  function getStatusColor(subscription) {
    if (!subscription.enabled) return 'inactive'
    if (subscription.next_check && new Date(subscription.next_check) < new Date()) return 'overdue'
    return 'active'
  }
  
  function handleAction(action) {
    dispatch('action', {
      action,
      subscriptionId: subscription.id
    })
  }
</script>

<div class="subscription-card card">
  <div class="card-header">
    <div class="subscription-header">
      <div class="channel-info">
        <h3 class="channel-name">{subscription.channel_name}</h3>
        <div class="subscription-meta">
          <span class="subscription-type">{subscription.subscription_type}</span>
          <span class="content-types">{formatContentTypes(subscription.content_types)}</span>
        </div>
      </div>
      <div class="status-indicator">
        <span class="status-dot {getStatusColor(subscription)}"></span>
        <span class="status-text">{subscription.enabled ? 'Active' : 'Paused'}</span>
      </div>
    </div>
  </div>
  
  <div class="card-body">
    <div class="subscription-stats">
      <div class="stat-row">
        <span class="stat-label">Quality:</span>
        <span class="stat-value">{formatQuality(subscription.quality_preference)}</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Auto-download:</span>
        <span class="stat-value {subscription.auto_download ? 'enabled' : 'disabled'}">
          {subscription.auto_download ? 'Enabled' : 'Disabled'}
        </span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Last check:</span>
        <span class="stat-value">{formatDate(subscription.last_check)}</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Next check:</span>
        <span class="stat-value next-check">{nextCheckText}</span>
      </div>
      {#if subscription.new_videos_count > 0}
        <div class="stat-row">
          <span class="stat-label">New videos:</span>
          <span class="stat-value new-videos">{subscription.new_videos_count}</span>
        </div>
      {/if}
    </div>
    
    <div class="schedule-info">
      <div class="schedule-label">Schedule:</div>
      <div class="schedule-value">{subscription.check_frequency || '0 * * * *'}</div>
      <div class="schedule-description">
        {#if subscription.check_frequency === '0 * * * *'}
          Every hour
        {:else if subscription.check_frequency === '0 */6 * * *'}
          Every 6 hours
        {:else if subscription.check_frequency === '0 0 * * *'}
          Daily
        {:else if subscription.check_frequency === '0 0 * * 0'}
          Weekly
        {:else}
          Custom schedule
        {/if}
      </div>
    </div>
  </div>
  
  <div class="card-footer">
    <div class="action-buttons">
      <button 
        class="btn btn-sm btn-secondary"
        on:click={() => handleAction('check')}
        disabled={!subscription.enabled}
        title="Check for new content now"
      >
        Check Now
      </button>
      
      {#if subscription.enabled}
        <button 
          class="btn btn-sm btn-ghost"
          on:click={() => handleAction('pause')}
          title="Pause this subscription"
        >
          Pause
        </button>
      {:else}
        <button 
          class="btn btn-sm btn-primary"
          on:click={() => handleAction('resume')}
          title="Resume this subscription"
        >
          Resume
        </button>
      {/if}
      
      <button 
        class="btn btn-sm btn-ghost"
        on:click={() => handleAction('edit')}
        title="Edit subscription settings"
      >
        Edit
      </button>
      
      <button 
        class="btn btn-sm btn-ghost delete-btn"
        on:click={() => handleAction('delete')}
        title="Delete this subscription"
      >
        Delete
      </button>
    </div>
  </div>
</div>

<style>
  .subscription-card {
    transition: all 0.3s ease;
  }
  
  .subscription-card:hover {
    transform: translateY(-2px);
  }
  
  .subscription-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--space-3);
  }
  
  .channel-info {
    flex: 1;
    min-width: 0;
  }
  
  .channel-name {
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--terminal-green);
    margin: 0 0 var(--space-1) 0;
    font-family: var(--font-mono);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  
  .subscription-meta {
    display: flex;
    gap: var(--space-2);
    font-size: 0.75rem;
    color: var(--text-secondary);
    font-family: var(--font-mono);
  }
  
  .subscription-type {
    text-transform: capitalize;
    background: var(--surface-hover);
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
  }
  
  .content-types {
    background: var(--surface-hover);
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
  }
  
  .status-indicator {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 0.75rem;
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
    background: var(--text-muted);
    box-shadow: 0 0 8px var(--text-muted);
  }
  
  .status-dot.overdue {
    background: var(--warning);
    box-shadow: 0 0 8px var(--warning);
  }
  
  .subscription-stats {
    margin-bottom: var(--space-4);
  }
  
  .stat-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-1) 0;
    font-size: 0.875rem;
    font-family: var(--font-mono);
  }
  
  .stat-label {
    color: var(--text-secondary);
  }
  
  .stat-value {
    color: var(--text-primary);
    font-weight: 500;
  }
  
  .stat-value.enabled {
    color: var(--success);
  }
  
  .stat-value.disabled {
    color: var(--text-muted);
  }
  
  .stat-value.new-videos {
    color: var(--terminal-green);
    font-weight: 600;
  }
  
  .stat-value.next-check {
    color: var(--terminal-amber);
  }
  
  .schedule-info {
    background: var(--surface-hover);
    border-radius: var(--radius);
    padding: var(--space-3);
    margin-bottom: var(--space-4);
  }
  
  .schedule-label {
    font-size: 0.75rem;
    color: var(--text-secondary);
    font-family: var(--font-mono);
    margin-bottom: var(--space-1);
  }
  
  .schedule-value {
    font-family: var(--font-mono);
    font-size: 0.875rem;
    color: var(--text-primary);
    background: var(--surface);
    padding: var(--space-2);
    border-radius: var(--radius-sm);
    margin-bottom: var(--space-1);
  }
  
  .schedule-description {
    font-size: 0.75rem;
    color: var(--terminal-green);
    font-family: var(--font-mono);
  }
  
  .action-buttons {
    display: flex;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  
  .action-buttons .btn {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
  }
  
  .delete-btn:hover {
    color: var(--error);
    border-color: var(--error);
    box-shadow: 0 0 8px rgba(255, 51, 68, 0.3);
  }
  
  @media (max-width: 768px) {
    .subscription-header {
      flex-direction: column;
      gap: var(--space-2);
    }
    
    .action-buttons {
      flex-direction: column;
    }
    
    .action-buttons .btn {
      flex: none;
    }
  }
</style> 