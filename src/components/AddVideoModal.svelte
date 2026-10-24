<script>
  import Dialog from './Dialog.svelte'
  import { qualityOptions } from '../lib/quality.js'
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
      
      window.dispatchEvent(new Event('library-changed'))

    } catch (error) {
      window.youHoard.showToast(error.message, 'error')
    } finally {
      submitting = false
    }
  }

  function handleCancel() {
    if (submitting) return
    show = false
    url = ''
    quality = '1080p'
  }

</script>

{#if show}
  <Dialog bind:show label="Add video" busy={submitting}>
    <div class="modal-content">
      <div class="modal-header">
        <h3>Add Video</h3>
        <button class="modal-close" aria-label="Close" on:click={handleCancel} disabled={submitting}>&times;</button>
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
              {#each qualityOptions as option}
                <option value={option.value}>{option.label}</option>
              {/each}
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
  </Dialog>
{/if} 