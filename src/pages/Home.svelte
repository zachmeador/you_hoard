<script>
  import { onMount } from 'svelte'
  
  let stats = {
    totalVideos: '-',
    totalChannels: '-', 
    totalSubscriptions: '-',
    storageUsed: '-'
  }
  
  let recentDownloads = []
  let activeSubscriptions = []
  let schedulerStatus = null
  let loading = true

  onMount(async () => {
    await loadDashboardData()
  })

  async function loadDashboardData() {
    try {
      await Promise.all([
        loadStats(),
        loadRecentDownloads(),
        loadActiveSubscriptions(),
        loadSchedulerStatus()
      ])
    } catch (error) {
      console.error('Failed to load dashboard data:', error)
      window.youHoard.showToast('Failed to load dashboard data', 'error')
    } finally {
      loading = false
    }
  }

  async function loadStats() {
    try {
      const [videosResponse, channelsResponse, subscriptionsResponse] = await Promise.all([
        window.youHoard.apiCall('/api/videos?per_page=1'),
        window.youHoard.apiCall('/api/channels?per_page=1'),
        window.youHoard.apiCall('/api/subscriptions?per_page=1')
      ])
      
      stats = {
        totalVideos: videosResponse.total || 0,
        totalChannels: channelsResponse.total || 0,
        totalSubscriptions: subscriptionsResponse.total || 0,
        storageUsed: 'N/A' // TODO: Calculate from video file sizes
      }
    } catch (error) {
      console.error('Failed to load stats:', error)
    }
  }

  async function loadRecentDownloads() {
    try {
      const response = await window.youHoard.apiCall('/api/downloads?per_page=5')
      recentDownloads = response.downloads || []
    } catch (error) {
      console.error('Failed to load recent downloads:', error)
      recentDownloads = []
    }
  }

  async function loadActiveSubscriptions() {
    try {
      const response = await window.youHoard.apiCall('/api/subscriptions?enabled_only=true&per_page=5')
      activeSubscriptions = response.subscriptions || []
    } catch (error) {
      console.error('Failed to load active subscriptions:', error)
      activeSubscriptions = []
    }
  }

  async function loadSchedulerStatus() {
    try {
      const response = await window.youHoard.apiCall('/api/subscriptions/scheduler/status')
      schedulerStatus = response
    } catch (error) {
      console.error('Failed to load scheduler status:', error)
      schedulerStatus = null
    }
  }
</script>

<div class="page-header">
  <h1 class="page-title">Dashboard</h1>
  <p class="page-subtitle">Welcome to You Hoard - Your personal YouTube archive</p>
</div>

<!-- Stats Grid -->
<div class="stats-grid">
  <div class="stat-card">
    <div class="stat-value">{stats.totalVideos}</div>
    <div class="stat-label">Total Videos</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{stats.totalChannels}</div>
    <div class="stat-label">Channels</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{stats.totalSubscriptions}</div>
    <div class="stat-label">Subscriptions</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{stats.storageUsed}</div>
    <div class="stat-label">Storage Used</div>
  </div>
</div>

<!-- Quick Actions -->
<div class="grid grid-2">
  <!-- Recent Downloads -->
  <div class="card">
    <div class="card-header">
      <h3>Recent Downloads</h3>
    </div>
    <div class="card-body">
      <div class="recent-list">
        {#if loading}
          <div class="loading-placeholder">Loading...</div>
        {:else if recentDownloads.length > 0}
          {#each recentDownloads as download}
            <div class="recent-item">
              <div class="recent-item-info">
                <h4>{download.video_title || 'Unknown Video'}</h4>
                <p>Progress: {Math.round(download.progress || 0)}%</p>
              </div>
              <div class="recent-item-status status-{download.status}">
                {download.status}
              </div>
            </div>
          {/each}
        {:else}
          <div class="loading-placeholder">No recent downloads</div>
        {/if}
      </div>
    </div>
    <div class="card-footer">
      <a href="#/downloads" class="btn btn-secondary btn-sm">View All Downloads</a>
    </div>
  </div>

  <!-- Active Subscriptions -->
  <div class="card">
    <div class="card-header">
      <h3>Active Subscriptions</h3>
    </div>
    <div class="card-body">
      <div class="recent-list">
        {#if loading}
          <div class="loading-placeholder">Loading...</div>
        {:else if activeSubscriptions.length > 0}
          {#each activeSubscriptions as sub}
            <div class="recent-item">
              <div class="recent-item-info">
                <h4>{sub.channel_name}</h4>
                <p>Last check: {window.youHoard.formatRelativeTime(sub.last_check)}</p>
              </div>
              <div class="recent-item-status status-completed">
                Active
              </div>
            </div>
          {/each}
        {:else}
          <div class="loading-placeholder">No active subscriptions</div>
        {/if}
      </div>
    </div>
    <div class="card-footer">
      <a href="#/subscriptions" class="btn btn-secondary btn-sm">Manage Subscriptions</a>
    </div>
  </div>
</div>

<!-- Scheduler Status -->
<div class="card mb-6">
  <div class="card-header">
    <h3>Scheduler Status</h3>
  </div>
  <div class="card-body">
    {#if loading}
      <div class="loading-placeholder">Loading scheduler status...</div>
    {:else if schedulerStatus}
      <div class="scheduler-info">
        <div class="scheduler-status-indicator" class:running={schedulerStatus.scheduler_running}></div>
        <div>
          <strong>Scheduler Status:</strong> {schedulerStatus.scheduler_running ? 'Running' : 'Stopped'}
          <br>
          <small>{schedulerStatus.total_jobs} scheduled job(s)</small>
        </div>
      </div>
      
      {#if schedulerStatus.scheduled_subscriptions && schedulerStatus.scheduled_subscriptions.length > 0}
        <div class="scheduler-jobs">
          {#each schedulerStatus.scheduled_subscriptions.slice(0, 3) as job}
            <div class="scheduler-job">
              <div class="scheduler-job-info">
                Subscription {job.subscription_id}
              </div>
              <div class="scheduler-job-next">
                Next: {job.next_run_time ? new Date(job.next_run_time).toLocaleString() : 'Unknown'}
              </div>
            </div>
          {/each}
        </div>
      {/if}
    {:else}
      <div class="loading-placeholder">Failed to load scheduler status</div>
    {/if}
  </div>
</div>

<style>
  .recent-list {
    min-height: 150px;
  }

  .recent-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-1) 0;
    border-bottom: 1px solid var(--border);
  }

  .recent-item:last-child {
    border-bottom: none;
  }

  .recent-item-info h4 {
    font-size: 0.875rem;
    font-weight: 500;
    margin-bottom: var(--space-1);
  }

  .recent-item-info p {
    font-size: 0.75rem;
    color: var(--text-secondary);
    margin: 0;
  }

  .recent-item-status {
    font-size: 0.75rem;
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
    font-weight: 500;
  }

  .status-completed {
    background: rgba(0, 255, 136, 0.2);
    color: var(--terminal-green);
    border: 1px solid rgba(0, 255, 136, 0.3);
  }

  .status-downloading {
    background: rgba(0, 170, 255, 0.2);
    color: #00aaff;
    border: 1px solid rgba(0, 170, 255, 0.3);
  }

  .status-pending {
    background: rgba(255, 170, 0, 0.2);
    color: var(--terminal-amber);
    border: 1px solid rgba(255, 170, 0, 0.3);
  }

  .status-failed {
    background: rgba(255, 51, 68, 0.2);
    color: var(--error);
    border: 1px solid rgba(255, 51, 68, 0.3);
  }

  .loading-placeholder {
    text-align: center;
    color: var(--text-secondary);
    padding: var(--space-4) 0;
  }

  .scheduler-info {
    display: flex;
    align-items: center;
    gap: var(--space-4);
    margin-bottom: var(--space-4);
  }

  .scheduler-status-indicator {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--error);
  }

  .scheduler-status-indicator.running {
    background: var(--success);
  }

  .scheduler-jobs {
    display: grid;
    gap: var(--space-2);
  }

  .scheduler-job {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-2);
    background: var(--surface-hover);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    transition: all 0.2s ease;
  }

  .scheduler-job:hover {
    border-color: var(--terminal-green);
    box-shadow: var(--glow-primary);
  }

  .scheduler-job-info {
    font-size: 0.875rem;
  }

  .scheduler-job-next {
    font-size: 0.75rem;
    color: var(--text-secondary);
  }
</style> 