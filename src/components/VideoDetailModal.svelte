<script>
  import { createEventDispatcher } from 'svelte'
  
  export let show = false
  export let video = null
  
  const dispatch = createEventDispatcher()
  
  function handleClose() {
    show = false
  }
  
  function handleBackdropClick(event) {
    if (event.target === event.currentTarget) {
      handleClose()
    }
  }
  
  function handleKeydown(event) {
    if (event.key === 'Escape') {
      handleClose()
    }
  }
  
  function handleAction(action) {
    dispatch('action', { action, videoId: video.id })
  }
  
  function getStatusDescription(status) {
    const descriptions = {
      'completed': 'Video has been successfully downloaded',
      'downloading': 'Video is currently being downloaded',
      'pending': 'Video is waiting to be downloaded',
      'failed': 'Download failed - try downloading again'
    }
    return descriptions[status] || 'Unknown status'
  }
  
  function formatNumber(num) {
    if (!num) return 'Unknown'
    if (num >= 1000000) {
      return (num / 1000000).toFixed(1) + 'M'
    } else if (num >= 1000) {
      return (num / 1000).toFixed(1) + 'K'
    }
    return num.toString()
  }
</script>

<svelte:window on:keydown={handleKeydown} />

{#if show && video}
  <div class="modal show" on:click={handleBackdropClick}>
    <div class="modal-content modal-large">
      <div class="modal-header">
        <h3>{video.title}</h3>
        <button class="modal-close" on:click={handleClose}>&times;</button>
      </div>
      <div class="modal-body">
        <div class="video-detail-grid">
          <div class="video-detail-main">
            <div class="detail-section">
              <h4>Description</h4>
              <p>
                {video.description ? 
                  (video.description.length > 500 ? 
                    video.description.substring(0, 500) + '...' : 
                    video.description) : 
                  'No description available'}
              </p>
            </div>
            
            <div class="detail-section">
              <h4>Video Information</h4>
              <div class="detail-meta">
                <span class="label">Channel:</span>
                <span>{video.channel_name}</span>
                
                <span class="label">Duration:</span>
                <span>{window.youHoard.formatDuration(video.duration)}</span>
                
                <span class="label">Upload Date:</span>
                <span>{video.upload_date ? window.youHoard.formatDate(video.upload_date) : 'Unknown'}</span>
                
                <span class="label">Views:</span>
                <span>{formatNumber(video.view_count)}</span>
                
                <span class="label">Likes:</span>
                <span>{formatNumber(video.like_count)}</span>
              </div>
            </div>
          </div>
          
          <div class="video-detail-sidebar">
            <div class="detail-section">
              <h4>Download Status</h4>
              <div class="video-status-badge status-{video.download_status}">
                {video.download_status}
              </div>
              <p class="status-description">
                {getStatusDescription(video.download_status)}
              </p>
            </div>
            
            <div class="detail-section">
              <h4>File Information</h4>
              <div class="detail-meta">
                <span class="label">Size:</span>
                <span>{video.file_size ? window.youHoard.formatFileSize(video.file_size) : 'N/A'}</span>
                
                <span class="label">Quality:</span>
                <span>{video.quality || 'N/A'}</span>
                
                <span class="label">Path:</span>
                <span class="file-path">
                  {video.file_path || 'N/A'}
                </span>
              </div>
            </div>
            
            <div class="detail-section">
              <h4>Actions</h4>
              <div class="detail-actions">
                {#if video.download_status === 'pending' || video.download_status === 'failed'}
                  <button class="btn btn-primary btn-sm" on:click={() => handleAction('download')}>
                    Download
                  </button>
                {/if}
                <a 
                  href="https://www.youtube.com/watch?v={video.youtube_id}" 
                  target="_blank" 
                  rel="noopener noreferrer"
                  class="btn btn-secondary btn-sm"
                >
                  View on YouTube
                </a>
                <button class="btn btn-error btn-sm" on:click={() => handleAction('delete')}>
                  Delete
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
{/if}

<style>
  .modal-large {
    max-width: 800px;
  }

  .video-detail-grid {
    display: grid;
    grid-template-columns: 1fr 300px;
    gap: var(--space-6);
  }

  .video-detail-main {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }

  .video-detail-sidebar {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }

  .detail-section {
    background: var(--surface-hover);
    padding: var(--space-3);
    border-radius: var(--radius);
    border: 1px solid var(--border);
  }

  .detail-section h4 {
    margin-bottom: var(--space-2);
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--terminal-green);
    font-family: var(--font-mono);
  }

  .detail-meta {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: var(--space-2) var(--space-3);
    font-size: 0.875rem;
  }

  .detail-meta .label {
    font-weight: 500;
    color: var(--text-secondary);
    font-family: var(--font-mono);
  }

  .file-path {
    word-break: break-all;
    font-family: var(--font-mono);
    font-size: 0.75rem;
  }

  .status-description {
    margin-top: var(--space-2);
    font-size: 0.875rem;
    color: var(--text-secondary);
  }

  .detail-actions {
    display: flex;
    gap: var(--space-2);
    flex-wrap: wrap;
  }

  .video-status-badge {
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
    font-size: 0.75rem;
    font-weight: 500;
    text-transform: uppercase;
    display: inline-block;
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

  .btn-error {
    background: var(--error);
    color: white;
    border-color: var(--error);
  }

  .btn-error:hover {
    background: #cc2233;
    border-color: #cc2233;
  }

  @media (max-width: 768px) {
    .video-detail-grid {
      grid-template-columns: 1fr;
    }
  }
</style> 