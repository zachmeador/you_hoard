<script>
  import { onMount } from 'svelte'
  import VideoCard from '../components/VideoCard.svelte'
  import VideoDetailModal from '../components/VideoDetailModal.svelte'
  import Pagination from '../components/Pagination.svelte'
  import SearchFilters from '../components/SearchFilters.svelte'
  
  let videos = []
  let channels = []
  let loading = true
  let selectedVideo = null
  let showVideoDetail = false
  
  // Pagination state
  let currentPage = 1
  let totalPages = 1
  let totalVideos = 0
  let perPage = 20
  
  // Filter state
  let filters = {
    search: '',
    status: '',
    channelId: ''
  }

  // Reactive statement to reload videos when filters or pagination change
  $: if (currentPage || filters) {
    loadVideos()
  }

  onMount(async () => {
    await loadChannels()
    await loadVideos()
  })

  async function loadChannels() {
    try {
      const response = await window.youHoard.apiCall('/api/channels?per_page=100')
      channels = response.channels || []
    } catch (error) {
      console.error('Failed to load channels:', error)
    }
  }

  async function loadVideos() {
    loading = true
    
    try {
      const params = new URLSearchParams({
        page: currentPage,
        per_page: perPage
      })
      
      // Add filters
      if (filters.search) params.append('search', filters.search)
      if (filters.status) params.append('status', filters.status)
      if (filters.channelId) params.append('channel_id', filters.channelId)
      
      const response = await window.youHoard.apiCall(`/api/videos?${params}`)
      
      videos = response.videos || []
      totalVideos = response.total || 0
      totalPages = Math.ceil(totalVideos / perPage)
      
    } catch (error) {
      console.error('Failed to load videos:', error)
      window.youHoard.showToast('Failed to load videos', 'error')
      videos = []
    } finally {
      loading = false
    }
  }

  function handleSearch(searchText) {
    filters.search = searchText
    currentPage = 1
  }

  function handleStatusFilter(status) {
    filters.status = status
    currentPage = 1
  }

  function handleChannelFilter(channelId) {
    filters.channelId = channelId
    currentPage = 1
  }

  function handleClearFilters() {
    filters = { search: '', status: '', channelId: '' }
    currentPage = 1
  }

  function handlePageChange(page) {
    currentPage = page
  }

  async function handleVideoClick(video) {
    try {
      // Get full video details
      const fullVideo = await window.youHoard.apiCall(`/api/videos/${video.id}`)
      selectedVideo = fullVideo
      showVideoDetail = true
    } catch (error) {
      console.error('Failed to load video details:', error)
      window.youHoard.showToast('Failed to load video details', 'error')
    }
  }

  async function handleVideoAction(event) {
    const { action, videoId } = event.detail
    
    if (action === 'download') {
      try {
        await window.youHoard.apiCall(`/api/videos/${videoId}/download`, {
          method: 'POST',
          body: JSON.stringify({ priority: 5 })
        })
        window.youHoard.showToast('Video queued for download', 'success')
        await loadVideos() // Refresh the list
      } catch (error) {
        window.youHoard.showToast('Failed to queue download', 'error')
      }
    } else if (action === 'delete') {
      if (confirm('Are you sure you want to delete this video? This action cannot be undone.')) {
        try {
          await window.youHoard.apiCall(`/api/videos/${videoId}`, { method: 'DELETE' })
          window.youHoard.showToast('Video deleted successfully', 'success')
          await loadVideos() // Refresh the list
        } catch (error) {
          window.youHoard.showToast('Failed to delete video', 'error')
        }
      }
    }
    
    showVideoDetail = false
  }
</script>

<div class="page-header">
  <h1 class="page-title">Videos</h1>
  <p class="page-subtitle">Browse and manage your downloaded videos</p>
</div>

<SearchFilters 
  {channels}
  on:search={e => handleSearch(e.detail)}
  on:statusFilter={e => handleStatusFilter(e.detail)}
  on:channelFilter={e => handleChannelFilter(e.detail)}
  on:clearFilters={handleClearFilters}
/>

<!-- Videos Grid -->
<div class="videos-grid">
  {#if loading}
    <div class="loading-placeholder" style="grid-column: 1 / -1;">
      Loading videos...
    </div>
  {:else if videos.length === 0}
    <div class="loading-placeholder" style="grid-column: 1 / -1;">
      No videos found. Try adjusting your filters or 
      <button class="btn-link" on:click={() => window.youHoard.showModal('add-video-modal')}>
        add some videos
      </button>!
    </div>
  {:else}
    {#each videos as video (video.id)}
      <VideoCard {video} on:click={() => handleVideoClick(video)} />
    {/each}
  {/if}
</div>

{#if totalVideos > perPage}
  <Pagination 
    {currentPage}
    {totalPages}
    {totalVideos}
    {perPage}
    on:pageChange={e => handlePageChange(e.detail)}
  />
{/if}

<VideoDetailModal 
  bind:show={showVideoDetail} 
  video={selectedVideo}
  on:action={handleVideoAction}
/>

<style>
  .videos-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: var(--space-4);
    margin-bottom: var(--space-6);
  }

  .loading-placeholder {
    text-align: center;
    color: var(--text-secondary);
    padding: var(--space-8) var(--space-4);
  }

  .btn-link {
    background: none;
    border: none;
    color: var(--terminal-green);
    text-decoration: underline;
    cursor: pointer;
    font-family: inherit;
    font-size: inherit;
  }

  .btn-link:hover {
    text-shadow: 0 0 5px var(--primary-glow);
  }

  @media (max-width: 768px) {
    .videos-grid {
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
         }
   }
 </style> 