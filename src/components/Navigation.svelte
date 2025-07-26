<script>
  import { createEventDispatcher } from 'svelte'
  import { link } from 'svelte-spa-router'
  import { authApi } from '../stores/auth.js'
  
  const dispatch = createEventDispatcher()
  
  let showUserDropdown = false
  let animationCooldown = false

  function handleLogoHover() {
    if (!animationCooldown) {
      createEmojiExplosion()
      animationCooldown = true
      setTimeout(() => {
        animationCooldown = false
      }, 1000)
    }
  }

  function createEmojiExplosion() {
    const dumpsterEmojis = ['🗑️', '🪣', '♻️', '🚮', '🗂️']
    const numEmojis = 8
    const logoElement = document.querySelector('.nav-logo')
    
    if (!logoElement) return
    
    const rect = logoElement.getBoundingClientRect()
    const centerX = rect.left + rect.width / 2
    const centerY = rect.top + rect.height / 2

    for (let i = 0; i < numEmojis; i++) {
      const emoji = document.createElement('div')
      emoji.className = 'emoji-particle'
      emoji.textContent = dumpsterEmojis[Math.floor(Math.random() * dumpsterEmojis.length)]
      
      emoji.style.left = centerX + 'px'
      emoji.style.top = centerY + 'px'
      
      const angle = (i / numEmojis) * 2 * Math.PI + (Math.random() - 0.5) * 0.5
      const distance = 80 + Math.random() * 40
      const randomX = Math.cos(angle) * distance
      const randomY = Math.sin(angle) * distance - Math.random() * 30
      
      emoji.style.setProperty('--random-x', randomX + 'px')
      emoji.style.setProperty('--random-y', randomY + 'px')
      
      document.body.appendChild(emoji)
      
      setTimeout(() => {
        if (emoji.parentNode) {
          emoji.parentNode.removeChild(emoji)
        }
      }, 2000)
    }
  }

  function toggleUserDropdown() {
    showUserDropdown = !showUserDropdown
  }

  function handleClickOutside(event) {
    if (!event.target.closest('.user-menu')) {
      showUserDropdown = false
    }
  }

  function handleLogout() {
    authApi.logout()
    showUserDropdown = false
  }
</script>

<svelte:document on:click={handleClickOutside} />

<nav class="navbar">
  <div class="nav-container">
    <div class="nav-brand">
      <a href="/" class="nav-logo" use:link on:mouseenter={handleLogoHover}>
        YouHoard
      </a>
    </div>
    
    <div class="nav-menu">
      <a href="/" class="nav-link" use:link>Home</a>
      <a href="/videos" class="nav-link" use:link>Videos</a>
      <a href="/channels" class="nav-link" use:link>Channels</a>
      <a href="/subscriptions" class="nav-link" use:link>Subscriptions</a>
      <a href="/downloads" class="nav-link" use:link>Downloads</a>
      <a href="/settings" class="nav-link" use:link>Settings</a>
    </div>
    
    <div class="nav-actions">
      <button class="btn btn-primary" on:click={() => dispatch('addVideo')}>
        + Add Video
      </button>
      <div class="user-menu">
        <button class="btn btn-ghost" on:click={toggleUserDropdown}>
          Menu
        </button>
        <div class="dropdown-menu" class:show={showUserDropdown}>
          <button class="dropdown-item" on:click={handleLogout}>Logout</button>
        </div>
      </div>
    </div>
  </div>
</nav> 