<script>
  import { createEventDispatcher } from 'svelte'
  
  export let show = false
  
  const dispatch = createEventDispatcher()
  
  let form = {
    source_url: '',
    subscription_type: 'channel',
    enabled: true,
    auto_download: true,
    quality_preference: '720p',
    download_comments: false,
    subtitle_languages: [],
    check_frequency: '0 * * * *',
    latest_n_videos: 20,
    content_types: ['video']
  }
  
  let loading = false
  let error = null
  
  const qualityOptions = [
    { value: '240p', label: '240p (Low)' },
    { value: '360p', label: '360p' },
    { value: '480p', label: '480p' },
    { value: '720p', label: '720p (HD)' },
    { value: '1080p', label: '1080p (Full HD)' },
    { value: '1440p', label: '1440p (2K)' },
    { value: '2160p', label: '2160p (4K)' },
    { value: 'best', label: 'Best Available' }
  ]
  
  const scheduleOptions = [
    { value: '*/30 * * * *', label: 'Every 30 minutes' },
    { value: '0 * * * *', label: 'Every hour' },
    { value: '0 */3 * * *', label: 'Every 3 hours' },
    { value: '0 */6 * * *', label: 'Every 6 hours' },
    { value: '0 */12 * * *', label: 'Every 12 hours' },
    { value: '0 0 * * *', label: 'Daily' },
    { value: '0 0 * * 0', label: 'Weekly' }
  ]
  
  const contentTypeOptions = [
    { value: 'video', label: 'Regular Videos' },
    { value: 'short', label: 'YouTube Shorts' },
    { value: 'live', label: 'Live Streams' }
  ]
  
  const commonLanguages = [
    'en', 'es', 'fr', 'de', 'it', 'pt', 'ru', 'ja', 'ko', 'zh', 'ar', 'hi'
  ]
  
  $: if (show) {
    error = null
  }
  
  function detectSubscriptionType(url) {
    const normalized = url.toLowerCase();
    if (normalized.includes('playlist?list=') || normalized.includes('/playlist?')) {
      form.subscription_type = 'playlist';
    } else if (normalized.includes('/channel/') || normalized.includes('/c/') || normalized.includes('/@') || normalized.includes('/user/')) {
      form.subscription_type = 'channel';
    } else {
      // Default to channel or show warning
      form.subscription_type = 'channel';
    }
  }
  
  function handleUrlChange() {
    detectSubscriptionType(form.source_url)
  }
  
  function handleContentTypeChange(type, checked) {
    if (checked) {
      form.content_types = [...form.content_types, type]
    } else {
      form.content_types = form.content_types.filter(t => t !== type)
    }
  }
  
  function handleLanguageChange(lang, checked) {
    if (checked) {
      form.subtitle_languages = [...form.subtitle_languages, lang]
    } else {
      form.subtitle_languages = form.subtitle_languages.filter(l => l !== lang)
    }
  }
  
  async function handleSubmit() {
    if (!form.source_url.trim()) {
      error = 'URL is required'
      return
    }
    
    if (form.content_types.length === 0) {
      error = 'At least one content type must be selected'
      return
    }
    
    loading = true
    error = null
    
    try {
      console.log('Making API call to create subscription...')
      
      // Add a timeout to the API call
      const timeoutPromise = new Promise((_, reject) => 
        setTimeout(() => reject(new Error('Request timed out after 60 seconds')), 65000)
      )
      
      const apiPromise = window.youHoard.apiCall('/api/subscriptions', {
        method: 'POST',
        body: JSON.stringify(form)
      })
      
      const result = await Promise.race([apiPromise, timeoutPromise])
      console.log('Subscription created successfully:', result)
      
      dispatch('created')
      resetForm()
    } catch (err) {
      console.error('Failed to create subscription:', err)
      if (err.message.includes('timed out')) {
        error = 'Request timed out. The YouTube URL might be invalid or the server is busy. Please try again.'
      } else if (err.message.includes('HTTP error')) {
        error = `Server error: ${err.message}. Please check the YouTube URL and try again.`
      } else {
        error = err.message || 'Failed to create subscription'
      }
    } finally {
      loading = false
    }
  }
  
  function handleCancel() {
    show = false
    resetForm()
  }
  
  function resetForm() {
    form = {
      source_url: '',
      subscription_type: 'channel',
      enabled: true,
      auto_download: true,
      quality_preference: '720p',
      download_comments: false,
      subtitle_languages: [],
      check_frequency: '0 * * * *',
      latest_n_videos: 20,
      content_types: ['video']
    }
    error = null
  }
</script>

{#if show}
  <div class="modal show">
    <div class="modal-content large-modal">
      <div class="modal-header">
        <h3>Add Subscription</h3>
        <button class="modal-close" on:click={handleCancel}>&times;</button>
      </div>
      
      <div class="modal-body">
        {#if error}
          <div class="error-message">
            {error}
          </div>
        {/if}
        
        <form on:submit|preventDefault={handleSubmit}>
          <!-- URL and Type -->
          <div class="form-section">
            <h4>Source</h4>
            <div class="form-group">
              <label for="source_url">YouTube URL *</label>
              <input
                id="source_url"
                type="url"
                bind:value={form.source_url}
                on:input={handleUrlChange}
                placeholder="https://www.youtube.com/channel/... or https://www.youtube.com/playlist?..."
                required
              />
              <div class="field-help">
                Paste a YouTube channel URL or playlist URL
              </div>
            </div>
            
            <div class="form-group">
              <label for="subscription_type">Type</label>
              <select id="subscription_type" bind:value={form.subscription_type}>
                <option value="channel">Channel</option>
                <option value="playlist">Playlist</option>
              </select>
            </div>
          </div>
          
          <!-- Content Preferences -->
          <div class="form-section">
            <h4>Content Preferences</h4>
            <div class="form-group">
              <fieldset>
                <legend>Content Types *</legend>
                <div class="checkbox-group">
                  {#each contentTypeOptions as option}
                    <label class="checkbox-label">
                      <input
                        type="checkbox"
                        checked={form.content_types.includes(option.value)}
                        on:change={e => handleContentTypeChange(option.value, e.target.checked)}
                      />
                      {option.label}
                    </label>
                  {/each}
                </div>
                <div class="field-help">
                  Select which types of content to include in this subscription
                </div>
              </fieldset>
            </div>
            
            <div class="form-group">
              <label for="latest_n_videos">Max Videos per Check</label>
              <input
                id="latest_n_videos"
                type="number"
                bind:value={form.latest_n_videos}
                min="1"
                max="200"
              />
              <div class="field-help">
                Maximum number of latest videos to check (1-200)
              </div>
            </div>
          </div>
          
          <!-- Download Settings -->
          <div class="form-section">
            <h4>Download Settings</h4>
            <div class="form-group">
              <label class="checkbox-label">
                <input type="checkbox" bind:checked={form.auto_download} />
                Auto-download new videos
              </label>
              <div class="field-help">
                Automatically download new videos when found
              </div>
            </div>
            
            <div class="form-group">
              <label for="quality_preference">Quality Preference</label>
              <select id="quality_preference" bind:value={form.quality_preference}>
                {#each qualityOptions as option}
                  <option value={option.value}>{option.label}</option>
                {/each}
              </select>
            </div>
            
            <div class="form-group">
              <label class="checkbox-label">
                <input type="checkbox" bind:checked={form.download_comments} />
                Download comments
              </label>
            </div>
            
            <div class="form-group">
              <fieldset>
                <legend>Subtitle Languages</legend>
                <div class="checkbox-group multi-column">
                  {#each commonLanguages as lang}
                    <label class="checkbox-label">
                      <input
                        type="checkbox"
                        checked={form.subtitle_languages.includes(lang)}
                        on:change={e => handleLanguageChange(lang, e.target.checked)}
                      />
                      {lang.toUpperCase()}
                    </label>
                  {/each}
                </div>
                <div class="field-help">
                  Select languages for subtitle downloads (leave empty for none)
                </div>
              </fieldset>
            </div>
          </div>
          
          <!-- Schedule Settings -->
          <div class="form-section">
            <h4>Schedule Settings</h4>
            <div class="form-group">
              <label for="check_frequency">Check Frequency</label>
              <select id="check_frequency" bind:value={form.check_frequency}>
                {#each scheduleOptions as option}
                  <option value={option.value}>{option.label}</option>
                {/each}
              </select>
              <div class="field-help">
                How often to check for new content
              </div>
            </div>
            
            <div class="form-group">
              <label class="checkbox-label">
                <input type="checkbox" bind:checked={form.enabled} />
                Enable subscription immediately
              </label>
              <div class="field-help">
                Start monitoring this subscription right away
              </div>
            </div>
          </div>
        </form>
      </div>
      
      <div class="modal-footer">
        <button type="button" class="btn btn-ghost" on:click={handleCancel} disabled={loading}>
          Cancel
        </button>
        <button type="button" class="btn btn-primary" on:click={handleSubmit} disabled={loading}>
          {#if loading}
            <div class="spinner"></div>
            Creating...
          {:else}
            Create Subscription
          {/if}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .large-modal {
    max-width: 600px;
    width: 95%;
  }
  
  .form-section {
    margin-bottom: var(--space-6);
    padding-bottom: var(--space-4);
    border-bottom: 1px solid var(--border);
  }
  
  .form-section:last-child {
    border-bottom: none;
    margin-bottom: 0;
  }
  
  .form-section h4 {
    color: var(--terminal-green);
    font-family: var(--font-mono);
    font-size: 1rem;
    margin-bottom: var(--space-4);
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  
  .form-section h4::before {
    content: '>';
    color: var(--terminal-amber);
  }
  
  .checkbox-group {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  
  .checkbox-group.multi-column {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(80px, 1fr));
    gap: var(--space-2);
  }
  
  .checkbox-label {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-family: var(--font-mono);
    font-size: 0.875rem;
    cursor: pointer;
    padding: var(--space-1);
    border-radius: var(--radius-sm);
    transition: background-color 0.2s;
  }
  
  .checkbox-label:hover {
    background: var(--surface-hover);
  }
  
  .checkbox-label input[type="checkbox"] {
    width: auto;
    margin: 0;
  }
  
  .field-help {
    font-size: 0.75rem;
    color: var(--text-muted);
    margin-top: var(--space-1);
    font-family: var(--font-mono);
  }
  
  fieldset {
    border: none;
    padding: 0;
    margin: 0;
  }
  
  legend {
    font-family: var(--font-mono);
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--terminal-green);
    margin-bottom: var(--space-1);
    padding: 0;
  }
  
  .error-message {
    background: rgba(255, 51, 68, 0.1);
    border: 1px solid var(--error);
    border-radius: var(--radius);
    padding: var(--space-3);
    margin-bottom: var(--space-4);
    color: var(--error);
    font-family: var(--font-mono);
    font-size: 0.875rem;
  }
  
  .modal-footer {
    display: flex;
    gap: var(--space-2);
    justify-content: flex-end;
    padding: var(--space-6);
    border-top: 1px solid var(--border);
    background: var(--surface-hover);
  }
  
  @media (max-width: 768px) {
    .large-modal {
      width: 95%;
      max-height: 95vh;
      margin: 2.5vh auto;
    }
    
    .checkbox-group.multi-column {
      grid-template-columns: repeat(auto-fit, minmax(60px, 1fr));
    }
    
    .modal-footer {
      flex-direction: column;
    }
  }
</style> 