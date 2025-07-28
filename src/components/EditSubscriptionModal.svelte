<script>
  import { createEventDispatcher } from 'svelte'
  
  export let show = false
  export let subscription = null
  
  const dispatch = createEventDispatcher()
  
  let form = {}
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
  
  // Reactive statement to populate form when subscription changes
  $: if (subscription && show) {
    populateForm()
    error = null
  }
  
  function populateForm() {
    form = {
      enabled: subscription.enabled ?? true,
      auto_download: subscription.auto_download ?? true,
      quality_preference: subscription.quality_preference || '720p',
      download_comments: subscription.download_comments ?? false,
      subtitle_languages: subscription.subtitle_languages || [],
      check_frequency: subscription.check_frequency || '0 * * * *',
      latest_n_videos: subscription.latest_n_videos || 20,
      content_types: subscription.content_types || ['video']
    }
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
    if (!subscription?.id) {
      error = 'No subscription selected'
      return
    }
    
    if (form.content_types.length === 0) {
      error = 'At least one content type must be selected'
      return
    }
    
    loading = true
    error = null
    
    try {
      await window.youHoard.apiCall(`/api/subscriptions/${subscription.id}`, {
        method: 'PUT',
        body: JSON.stringify(form)
      })
      
      dispatch('updated')
    } catch (err) {
      error = err.message || 'Failed to update subscription'
    } finally {
      loading = false
    }
  }
  
  function handleCancel() {
    show = false
    error = null
  }
</script>

{#if show && subscription}
  <div class="modal show">
    <div class="modal-content large-modal">
      <div class="modal-header">
        <h3>Edit Subscription</h3>
        <button class="modal-close" on:click={handleCancel}>&times;</button>
      </div>
      
      <div class="modal-body">
        {#if error}
          <div class="error-message">
            {error}
          </div>
        {/if}
        
        <!-- Subscription Info -->
        <div class="subscription-info">
          <div class="info-row">
            <span class="info-label">Channel:</span>
            <span class="info-value">{subscription.channel_name}</span>
          </div>
          <div class="info-row">
            <span class="info-label">Type:</span>
            <span class="info-value">{subscription.subscription_type}</span>
          </div>
          <div class="info-row">
            <span class="info-label">URL:</span>
            <span class="info-value url">{subscription.source_url}</span>
          </div>
        </div>
        
        <form on:submit|preventDefault={handleSubmit}>
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
                         checked={form.content_types?.includes(option.value)}
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
                         checked={form.subtitle_languages?.includes(lang)}
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
                Enable subscription
              </label>
              <div class="field-help">
                Enable or disable automatic monitoring
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
            Updating...
          {:else}
            Update Subscription
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
  
  .subscription-info {
    background: var(--surface-hover);
    border-radius: var(--radius);
    padding: var(--space-4);
    margin-bottom: var(--space-6);
  }
  
  .info-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: var(--space-2);
    font-family: var(--font-mono);
    font-size: 0.875rem;
  }
  
  .info-row:last-child {
    margin-bottom: 0;
  }
  
  .info-label {
    color: var(--text-secondary);
    min-width: 80px;
  }
  
  .info-value {
    color: var(--text-primary);
    font-weight: 500;
    text-align: right;
    flex: 1;
    margin-left: var(--space-2);
  }
  
  .info-value.url {
    word-break: break-all;
    font-size: 0.75rem;
    color: var(--terminal-green);
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
    
    .info-row {
      flex-direction: column;
      gap: var(--space-1);
    }
    
    .info-value {
      text-align: left;
      margin-left: 0;
    }
  }
</style> 