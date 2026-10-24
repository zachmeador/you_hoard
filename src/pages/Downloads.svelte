<script>
  import { onMount } from 'svelte'

  let jobs = []
  let counts = { active_count: 0, queued_count: 0, failed_count: 0 }
  let loading = true
  let error = ''
  let status = ''
  let offset = 0
  let busy = false
  const limit = 50

  onMount(() => {
    load()
    const timer = setInterval(() => load(true), 3000)
    return () => clearInterval(timer)
  })

  async function load(quiet = false) {
    if (!quiet) loading = true
    try {
      const params = new URLSearchParams({ limit, offset })
      if (status) params.set('status', status)
      const result = await window.youHoard.apiCall(`/api/downloads?${params}`)
      jobs = result.downloads
      counts = result
      error = ''
    } catch (err) {
      error = err.message
    } finally {
      loading = false
    }
  }

  async function action(path, method = 'POST') {
    busy = true
    try {
      const result = await window.youHoard.apiCall(`/api/downloads/${path}`, { method })
      window.youHoard.showToast(result.message, 'success')
      await load(true)
      window.dispatchEvent(new Event('library-changed'))
    } catch (err) {
      window.youHoard.showToast(err.message, 'error')
    } finally {
      busy = false
    }
  }

  function title(job) {
    return job.video_title || job.channel_name || `Job #${job.id}`
  }
</script>

<div class="page-header">
  <h1 class="page-title">Downloads</h1>
  <p class="page-subtitle">{counts.active_count} running · {counts.queued_count} queued · {counts.failed_count} failed. Updates every 3 seconds.</p>
</div>

<div class="toolbar">
  <label>Show
    <select bind:value={status} on:change={() => { offset = 0; load() }}>
      <option value="">All jobs</option>
      <option value="downloading">Downloading</option>
      <option value="processing">Checking sources</option>
      <option value="queued">Queued</option>
      <option value="failed">Failed</option>
      <option value="paused">Paused</option>
      <option value="completed">Completed</option>
    </select>
  </label>
  <button class="btn btn-secondary btn-sm" on:click={() => load()} disabled={loading}>Refresh</button>
  <button class="btn btn-secondary btn-sm" on:click={() => action('retry-all-failed')} disabled={busy || !counts.failed_count}>Retry failed</button>
  <button class="btn btn-ghost btn-sm" on:click={() => action('clear-completed')} disabled={busy}>Clear completed history</button>
</div>

{#if error}
  <p class="error-message" role="alert">Could not refresh the queue: {error} <button class="btn btn-secondary btn-sm" on:click={() => load()}>Retry</button></p>
{/if}

{#if loading}
  <p>Loading queue…</p>
{:else if !jobs.length && !error}
  <div class="card"><div class="card-body">
    <h3>{status ? 'No matching jobs' : 'Nothing queued yet'}</h3>
    <p>Add a video above, or <a href="#/subscriptions">check a subscription</a>. Completed files stay in your library when you clear this history.</p>
  </div></div>
{:else}
  <div class="jobs">
    {#each jobs as job (job.id)}
      <article class="card">
        <div class="card-body">
          <div class="job-heading">
            <div>
              <h3>{title(job)}</h3>
              <small>#{job.id} · {job.job_type === 'download' ? 'Video download' : job.job_type === 'subscription_discovery' ? 'Subscription check' : 'Metadata'}{job.quality ? ` · ${job.quality}` : ''}</small>
            </div>
            <strong class:failed={job.status === 'failed'}>{job.status}</strong>
          </div>
          {#if job.status === 'downloading'}
            <progress max="100" value={job.progress} aria-label="Download progress for {title(job)}"></progress>
            <small>{Math.round(job.progress)}%{job.speed ? ` · ${window.youHoard.formatFileSize(job.speed)}/s` : ''}{job.eta != null ? ` · ~${job.eta}s left` : ''} — includes merging and postprocessing</small>
          {:else if job.job_type === 'subscription_discovery' && job.status === 'completed'}
            <p>{job.result_data?.videos_found || 0} checked · {job.result_data?.videos_added || 0} new · {job.result_data?.videos_queued || 0} queued</p>
          {/if}
          {#if job.error_message}<pre class="failed">{job.error_message}</pre>{/if}
          {#if job.result_data?.errors?.length}
            <details><summary class="failed">{job.result_data.errors.length} entries had errors</summary><pre>{job.result_data.errors.join('\n')}</pre></details>
          {/if}
          <div class="job-actions">
            {#if job.status === 'queued'}
              <button class="btn btn-secondary btn-sm" disabled={busy} on:click={() => action(`${job.id}/pause`)}>Pause queued job</button>
            {:else if job.status === 'paused'}
              <button class="btn btn-primary btn-sm" disabled={busy} on:click={() => action(`${job.id}/resume`)}>Resume</button>
            {:else if job.status === 'failed'}
              <button class="btn btn-primary btn-sm" disabled={busy} on:click={() => action(`${job.id}/retry`)}>Retry</button>
            {/if}
            {#if job.status === 'completed' && job.job_type === 'download'}
              <a class="btn btn-secondary btn-sm" href="/api/videos/{job.video_id}/file" target="_blank" rel="noreferrer">Open local video</a>
            {/if}
            {#if !['downloading', 'processing'].includes(job.status)}
              <button class="btn btn-ghost btn-sm" disabled={busy} on:click={() => action(job.id, 'DELETE')}>Remove job</button>
            {/if}
          </div>
        </div>
      </article>
    {/each}
  </div>
{/if}

<div class="toolbar">
  <button class="btn btn-secondary btn-sm" disabled={offset === 0 || loading} on:click={() => { offset = Math.max(0, offset - limit); load() }}>Previous</button>
  <span>Jobs {jobs.length ? offset + 1 : 0}–{offset + jobs.length}</span>
  <button class="btn btn-secondary btn-sm" disabled={jobs.length < limit || loading} on:click={() => { offset += limit; load() }}>Next</button>
</div>
<p class="page-subtitle">Only queued work can be paused or cancelled. Active downloads and checks must finish; removing a completed job never deletes its video.</p>

<style>
  .toolbar, .job-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); margin-bottom: var(--space-4); }
  .toolbar label { display: flex; align-items: center; gap: var(--space-2); }
  select { background: var(--surface); color: var(--text-primary); padding: var(--space-2); border: 1px solid var(--border); }
  .jobs { display: grid; gap: var(--space-3); margin-bottom: var(--space-4); }
  .job-heading { display: flex; justify-content: space-between; gap: var(--space-3); margin-bottom: var(--space-3); }
  h3 { margin: 0; overflow-wrap: anywhere; }
  small { color: var(--text-secondary); }
  progress { width: 100%; accent-color: var(--terminal-green); }
  pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 0.85rem; margin: var(--space-3) 0; }
  .failed, .error-message { color: var(--error); }
  .job-actions { margin: var(--space-3) 0 0; }
  @media (max-width: 600px) { .job-heading { flex-direction: column; } }
</style>
