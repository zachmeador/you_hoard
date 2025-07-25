<script>
  export let show = false
  
  let url = ''
  let quality = '1080p'
  let submitting = false

  async function handleSubmit() {
    if (!url.trim()) return

    submitting = true
    
    try {
      await window.youHoard.apiCall('/api/videos', {
        method: 'POST',
        body: JSON.stringify({ url: url.trim(), quality })
      })

      window.youHoard.showToast('Video added successfully!', 'success')
      show = false
      url = ''
      quality = '1080p'
      
      // Refresh current page if it's videos
      if (window.location.hash === '#/videos') {
        window.location.reload()
      }

    } catch (error) {
      window.youHoard.showToast('Failed to add video', 'error')
    } finally {
      submitting = false
    }
  }

  function handleCancel() {
    show = false
    url = ''
    quality = '1080p'
  }

  function handleKeydown(event) {
    if (event.key === 'Escape') {
      handleCancel()
    }
  }

  function handleBackdropClick(event) {
    if (event.target === event.currentTarget) {
      handleCancel()
    }
  }
</script>

<svelte:window on:keydown={handleKeydown} />

{#if show}
  <div class="modal show" on:click={handleBackdropClick}>
    <div class="modal-content">
      <div class="modal-header">
        <h3>Add Video</h3>
        <button class="modal-close" on:click={handleCancel}>&times;</button>
      </div>
      <div class="modal-body">
        <form on:submit|preventDefault={handleSubmit}>
          <div class="form-group">
            <label for="video-url">YouTube URL</label>
            <input 
              type="url" 
              id="video-url" 
              bind:value={url}
              placeholder="https://www.youtube.com/watch?v=..." 
              required
              disabled={submitting}
            >
          </div>
          <div class="form-group">
            <label for="video-quality">Quality</label>
            <select id="video-quality" bind:value={quality} disabled={submitting}>
              <option value="1080p">1080p</option>
              <option value="720p">720p</option>
              <option value="480p">480p</option>
              <option value="best">Best Available</option>
            </select>
          </div>
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" on:click={handleCancel} disabled={submitting}>
              Cancel
            </button>
            <button type="submit" class="btn btn-primary" disabled={submitting}>
              {#if submitting}
                <span class="spinner"></span>Adding...
              {:else}
                Add Video
              {/if}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
{/if} 