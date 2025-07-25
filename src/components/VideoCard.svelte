<script>
  import { createEventDispatcher } from 'svelte'
  
  export let video
  
  const dispatch = createEventDispatcher()
  
  function handleClick() {
    dispatch('click', video)
  }
</script>

<div class="video-card" on:click={handleClick} on:keydown={e => e.key === 'Enter' && handleClick()} tabindex="0" role="button">
  <div class="video-thumbnail">
    {#if video.thumbnail_url}
      <img src={video.thumbnail_url} alt={video.title} loading="lazy" onerror="this.style.display='none'">
    {:else}
      🎬
    {/if}
    <div class="video-status-badge status-{video.download_status}">
      {video.download_status}
    </div>
  </div>
  <div class="video-info">
    <div class="video-title">{video.title}</div>
    <div class="video-meta">
      <span class="video-channel">{video.channel_name || 'Unknown Channel'}</span>
      <span class="video-duration">{window.youHoard.formatDuration(video.duration)}</span>
    </div>
  </div>
</div>

<style>
  .video-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    transition: all 0.2s ease;
    cursor: pointer;
  }

  .video-card:hover,
  .video-card:focus {
    border-color: var(--primary);
    box-shadow: var(--glow-primary);
    transform: translateY(-2px);
    outline: none;
  }

  .video-thumbnail {
    width: 100%;
    height: 180px;
    background: var(--surface-hover);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 2rem;
    color: var(--text-secondary);
    position: relative;
  }

  .video-thumbnail img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .video-status-badge {
    position: absolute;
    top: var(--space-2);
    right: var(--space-2);
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
    font-size: 0.75rem;
    font-weight: 500;
    text-transform: uppercase;
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

  .video-info {
    padding: var(--space-3);
  }

  .video-title {
    font-size: 0.875rem;
    font-weight: 600;
    line-height: 1.4;
    margin-bottom: var(--space-2);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .video-meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.75rem;
    color: var(--text-secondary);
  }

  .video-channel {
    font-weight: 500;
  }

  .video-duration {
    font-family: var(--font-mono);
  }
</style> 