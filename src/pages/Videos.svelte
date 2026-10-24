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
  let mounted = false
  let loadRequest = 0
  let error = ''
  
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

  $: if (mounted && (currentPage || filters)) {
    loadVideos()
  }

  onMount(() => {
    mounted = true
    loadChannels()
    const timer = setInterval(() => {
      if (videos.some(video => ['pending', 'downloading'].includes(video.download_status))) loadVideos(true)
    }, 3000)
    return () => {
      mounted = false
      clearInterval(timer)
    }
  })

  async function loadChannels() {
    try {
      const response = await window.youHoard.apiCall('/api/channels?per_page=100')
      channels = response.channels || []
    } catch (error) {
      console.error('Failed to load channels:', error)
    }
  }

  async function loadVideos(quiet = false) {
    const requestId = ++loadRequest
    if (!quiet) loading = true
    
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
      
      if (!mounted || requestId !== loadRequest) return
      videos = response.videos || []
      totalVideos = response.total || 0
      totalPages = Math.max(1, Math.ceil(totalVideos / perPage))
      error = ''
      if (selectedVideo) selectedVideo = videos.find(video => video.id === selectedVideo.id) || selectedVideo
      
    } catch (err) {
      if (mounted && requestId === loadRequest) error = err.message
    } finally {
      if (mounted && requestId === loadRequest) loading = false
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
        window.youHoard.showToast(error.message, 'error')
      }
    } else if (action === 'delete') {
      if (confirm('Remove this video’s local files? Its record is kept so subscriptions will not download it again.')) {
        try {
          await window.youHoard.apiCall(`/api/videos/${videoId}`, { method: 'DELETE' })
          window.youHoard.showToast('Local files removed; video remains remembered', 'success')
          await loadVideos() // Refresh the list
        } catch (error) {
          window.youHoard.showToast(error.message, 'error')
        }
      }
    }
    
    showVideoDetail = false
  }
</script>

<svelte:window on:library-changed={() => { loadChannels(); loadVideos(true) }} />

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

{#if error}
  <p role="alert">Could not load videos: {error} <button class="btn btn-secondary" on:click={() => loadVideos()}>Retry</button></p>
{/if}

<!-- Videos Grid -->
<div class="videos-grid">
  {#if loading}
    <div class="loading-placeholder" style="grid-column: 1 / -1;">
      Loading videos...
    </div>
  {:else if videos.length === 0 && !error}
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