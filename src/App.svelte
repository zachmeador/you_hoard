<script>
  import { onMount } from 'svelte'
  import Router from 'svelte-spa-router'
  import { authStore, authApi } from './stores/auth.js'
  import Home from './pages/Home.svelte'
  import Videos from './pages/Videos.svelte'
  import Channels from './pages/Channels.svelte'
  import Subscriptions from './pages/Subscriptions.svelte'
  import Downloads from './pages/Downloads.svelte'
  import Settings from './pages/Settings.svelte'
  import Navigation from './components/Navigation.svelte'
  import AddVideoModal from './components/AddVideoModal.svelte'
  import LoginForm from './components/LoginForm.svelte'
  import ToastContainer from './components/ToastContainer.svelte'

  const routes = {
    '/': Home,
    '/videos': Videos,
    '/channels': Channels,
    '/subscriptions': Subscriptions,
    '/downloads': Downloads,
    '/settings': Settings
  }

  let showAddVideoModal = false

  onMount(() => {
    authApi.init()
  })

  // Global utilities
  window.youHoard = {
    showModal: (modalId) => {
      if (modalId === 'add-video-modal') showAddVideoModal = true
    },
    hideModal: (modalId) => {
      if (modalId === 'add-video-modal') showAddVideoModal = false
    },
    showToast: (message, type = 'info', duration = 5000) => {
      document.dispatchEvent(new CustomEvent('show-toast', {
        detail: { message, type, duration }
      }))
    },
    apiCall: async (url, options = {}) => {
      const config = { 
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        ...options
      }
      
      try {
        const response = await fetch(url, config)
        
        if (!response.ok) {
          if (response.status === 401) {
            authApi.logout() // Force re-login
            throw new Error('Authentication required')
          }
          throw new Error(`HTTP error! status: ${response.status}`)
        }
        
        return await response.json()
      } catch (error) {
        console.error('API call failed:', error)
        window.youHoard.showToast(`Error: ${error.message}`, 'error')
        throw error
      }
    },
    formatFileSize: (bytes) => {
      if (bytes === 0) return '0 Bytes'
      const k = 1024
      const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB']
      const i = Math.floor(Math.log(bytes) / Math.log(k))
      return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
    },
    formatDuration: (seconds) => {
      if (!seconds) return 'Unknown'
      const hours = Math.floor(seconds / 3600)
      const minutes = Math.floor((seconds % 3600) / 60)
      const secs = Math.floor(seconds % 60)
      if (hours > 0) {
        return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
      }
      return `${minutes}:${secs.toString().padStart(2, '0')}`
    },
    formatDate: (dateString) => {
      if (!dateString) return 'Unknown'
      const date = new Date(dateString)
      return date.toLocaleDateString('en-US', {
        year: 'numeric', month: 'short', day: 'numeric'
      })
    },
    formatRelativeTime: (dateString) => {
      if (!dateString) return 'Unknown'
      const date = new Date(dateString)
      const now = new Date()
      const diffInSeconds = Math.floor((now - date) / 1000)
      if (diffInSeconds < 60) return 'Just now'
      if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)} minutes ago`
      if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)} hours ago`
      if (diffInSeconds < 2592000) return `${Math.floor(diffInSeconds / 86400)} days ago`
      return window.youHoard.formatDate(dateString)
    },
    escapeHtml: (text) => {
      if (!text) return ''
      const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }
      return text.replace(/[&<>"']/g, m => map[m])
    }
  }
</script>

{#if $authStore.loading}
  <div class="auth-loading">
    <div class="spinner"></div>
    <p>Loading...</p>
  </div>
{:else if $authStore.isAuthenticated}
  <!-- Full app when authenticated -->
  <Navigation on:addVideo={() => showAddVideoModal = true} />
  <main class="main-content">
    <Router {routes} />
  </main>
  <AddVideoModal bind:show={showAddVideoModal} />
{:else}
  <!-- Login form when not authenticated -->
  <LoginForm />
{/if}

<ToastContainer />

<style>
  :global(body) {
    margin: 0;
    padding: 0;
  }
  
  .auth-loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100vh;
    gap: var(--space-4);
    color: var(--text-secondary);
  }
</style> 