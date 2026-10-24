<script>
  /** @import { Job, JobList, JobStatus } from '../lib/types' */
  import { untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import {
    JOB_KINDS,
    STATUS,
    bytes,
    dateTime,
    eta,
    int,
    jobResultSummary,
    parseTime,
    percent,
    plural,
    speed
  } from '../lib/format.js'
  import { Loader } from '../lib/loader.svelte.js'
  import { poll } from '../lib/poll.js'
  import { queue } from '../lib/queue.svelte.js'
  import { pageParam, router, updateQuery } from '../lib/router.svelte.js'
  import { notify } from '../lib/toasts.svelte.js'
  import { clock } from '../lib/ui.svelte.js'
  import Pagination from '../components/Pagination.svelte'
  import StatusBadge from '../components/StatusBadge.svelte'
  import Time from '../components/Time.svelte'
  import VideoDialog from '../components/VideoDialog.svelte'

  const PER_PAGE = 50
  /** @type {JobStatus[]} */
  const STATUSES = ['running', 'queued', 'paused', 'failed', 'completed', 'cancelled']
  const KINDS = /** @type {const} */ (['download', 'check', 'scan'])
  const CANCELLABLE = ['queued', 'paused', 'running']
  const FINISHED = ['completed', 'failed', 'cancelled']
  /** @type {Record<'cancel' | 'retry' | 'pause' | 'resume', string>} */
  const ACTION_MESSAGES = {
    cancel: 'Job cancelled',
    retry: 'Job queued again',
    pause: 'Job paused',
    resume: 'Job resumed'
  }

  const filters = $derived({
    status: router.query.status ?? '',
    kind: router.query.kind ?? '',
    page: pageParam(router.query.page)
  })

  /** @type {Loader<JobList>} */
  const jobs = new Loader()
  let busy = $state('')
  /** @type {number | null} */
  let openVideoId = $state(null)

  const counts = $derived(jobs.data?.counts ?? queue.counts)
  const finished = $derived(counts.completed + counts.failed + counts.cancelled)

  /** @param {typeof filters} f */
  async function fetchJobs(f) {
    const res = await api.jobs.list({
      status: f.status,
      kind: f.kind,
      limit: PER_PAGE,
      offset: (f.page - 1) * PER_PAGE
    })
    queue.counts = res.counts
    return res
  }

  function refresh() {
    return jobs.run(() => fetchJobs(filters), { quiet: true })
  }

  $effect(() => {
    const f = filters
    untrack(() => jobs.run(() => fetchJobs(f)))
  })

  $effect(() => poll(refresh, 2000, { immediate: false }))

  /**
   * @param {Job} job
   * @param {'cancel' | 'retry' | 'pause' | 'resume'} action
   */
  async function act(job, action) {
    busy = `${job.id}`
    try {
      await api.jobs.act(job.id, action)
      notify.success(ACTION_MESSAGES[action])
      await refresh()
    } catch (e) {
      notify.error(e)
    } finally {
      busy = ''
    }
  }

  /** @param {Job} job */
  async function remove(job) {
    busy = `${job.id}`
    try {
      await api.jobs.remove(job.id)
      await refresh()
    } catch (e) {
      notify.error(e)
    } finally {
      busy = ''
    }
  }

  async function clearFinished() {
    busy = 'bulk'
    try {
      const { cleared } = await api.jobs.clearFinished()
      notify.success(`Cleared ${plural(cleared, 'finished job')}`)
      await refresh()
    } catch (e) {
      notify.error(e)
    } finally {
      busy = ''
    }
  }

  async function retryFailed() {
    busy = 'bulk'
    try {
      const { retried } = await api.jobs.retryFailed()
      notify.success(`Retrying ${plural(retried, 'failed job')}`)
      await refresh()
    } catch (e) {
      notify.error(e)
    } finally {
      busy = ''
    }
  }

  /** @param {Job} job */
  function isWaiting(job) {
    if (job.status !== 'queued' || !job.run_after) return false
    return (parseTime(job.run_after)?.getTime() ?? 0) > clock.now
  }

  /** @param {Event & { currentTarget: HTMLSelectElement }} event */
  function selectValue(event) {
    return event.currentTarget.value
  }
</script>

<svelte:head>
  <title>Queue · YouHoard</title>
</svelte:head>

<div class="page-head">
  <h1 class="page-title">Queue</h1>
  <div class="cluster">
    <button type="button" class="btn btn-secondary btn-sm" disabled={!counts.failed || !!busy} onclick={retryFailed}>
      Retry failed
    </button>
    <button type="button" class="btn btn-secondary btn-sm" disabled={!finished || !!busy} onclick={clearFinished}>
      Clear finished
    </button>
  </div>
</div>

<ul class="counts job-counts" aria-label="Jobs by status">
  {#each STATUSES as status (status)}
    <li class:active={filters.status === status}>
      <strong>{int(counts[status])}</strong>
      {STATUS[status].label.toLowerCase()}
    </li>
  {/each}
</ul>

<div class="toolbar">
  <label class="sr-only" for="queue-status">Status</label>
  <select id="queue-status" value={filters.status} onchange={(e) => updateQuery({ status: selectValue(e) })}>
    <option value="">All statuses</option>
    {#each STATUSES as status (status)}
      <option value={status}>{STATUS[status].label}</option>
    {/each}
  </select>
  <label class="sr-only" for="queue-kind">Kind</label>
  <select id="queue-kind" value={filters.kind} onchange={(e) => updateQuery({ kind: selectValue(e) })}>
    <option value="">All kinds</option>
    {#each KINDS as kind (kind)}
      <option value={kind}>{JOB_KINDS[kind]}</option>
    {/each}
  </select>
  {#if jobs.data}<span class="muted small">{plural(jobs.data.total, 'job')}</span>{/if}
</div>

{#if jobs.error}
  <div class="form-error error-bar" role="alert">
    <span>{jobs.error}</span>
    <button type="button" class="btn btn-secondary btn-sm" onclick={() => jobs.run(() => fetchJobs(filters))}>
      Try again
    </button>
  </div>
{/if}

{#if jobs.data}
  {#if jobs.data.items.length === 0}
    <div class="empty">{filters.status || filters.kind ? 'No jobs match these filters.' : 'The queue is empty.'}</div>
  {:else}
    <ul class="rows" class:stale={jobs.loading}>
      {#each jobs.data.items as job (job.id)}
        {@const progress = job.status === 'running' ? job.progress : null}
        {@const determinate = progress?.phase === 'downloading' && progress.percent != null}
        <li class="row job" class:failed={job.status === 'failed'}>
          <div class="grow job-main">
            <div class="title-line">
              <span class="badge">{JOB_KINDS[job.kind] ?? job.kind}</span>
              {#if job.kind === 'download' && job.video}
                {@const videoId = job.video.id}
                <button type="button" class="link-btn title" onclick={() => (openVideoId = videoId)}>
                  {job.video.title || job.video.youtube_id}
                </button>
              {:else if job.kind === 'check' && job.subscription}
                <a class="title" href="#/subscriptions/{job.subscription.id}">{job.subscription.title}</a>
              {:else if job.kind === 'scan'}
                <span class="title">Library rescan</span>
              {:else}
                <span class="title">Job #{job.id}</span>
              {/if}
            </div>

            {#if progress}
              <div class="progress">
                <div
                  class="bar"
                  class:indeterminate={!determinate}
                  role="progressbar"
                  aria-label="Progress"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={determinate ? Math.round(progress.percent ?? 0) : undefined}
                >
                  <span style:width={determinate ? `${progress.percent}%` : undefined}></span>
                </div>
                <div class="dots small">
                  {#if progress.phase === 'processing'}
                    <span>processing…</span>
                  {:else}
                    {#if progress.percent != null}<span>{percent(progress.percent)}</span>{/if}
                    {#if progress.speed}<span>{speed(progress.speed)}</span>{/if}
                    {#if progress.eta != null}<span>ETA {eta(progress.eta)}</span>{/if}
                    {#if progress.total_bytes}
                      <span>{bytes(progress.downloaded_bytes ?? 0)} / {bytes(progress.total_bytes)}</span>
                    {/if}
                    <span>downloading</span>
                  {/if}
                </div>
              </div>
            {/if}

            <div class="dots muted small">
              <span><StatusBadge status={job.status} /></span>
              {#if isWaiting(job)}
                <span class="warn-text">waiting until {dateTime(job.run_after)} (<Time value={job.run_after} />)</span>
              {/if}
              {#if job.attempts > 1}<span>attempt {job.attempts}</span>{/if}
              <span>added <Time value={job.created_at} /></span>
              {#if job.started_at}<span>started <Time value={job.started_at} /></span>{/if}
              {#if job.finished_at}<span>finished <Time value={job.finished_at} /></span>{/if}
            </div>
            {#if job.error}<p class="error-text small">{job.error}</p>{/if}
            {#if job.status === 'completed' && job.result}
              <p class="muted small">{jobResultSummary(job)}</p>
            {/if}
          </div>

          <div class="actions">
            {#if job.status === 'queued'}
              <button type="button" class="btn btn-secondary btn-sm" disabled={!!busy} onclick={() => act(job, 'pause')}>
                Pause
              </button>
            {/if}
            {#if job.status === 'paused'}
              <button type="button" class="btn btn-secondary btn-sm" disabled={!!busy} onclick={() => act(job, 'resume')}>
                Resume
              </button>
            {/if}
            {#if job.status === 'failed' || job.status === 'cancelled'}
              <button type="button" class="btn btn-secondary btn-sm" disabled={!!busy} onclick={() => act(job, 'retry')}>
                Retry
              </button>
            {/if}
            {#if CANCELLABLE.includes(job.status)}
              <button type="button" class="btn btn-danger btn-sm" disabled={!!busy} onclick={() => act(job, 'cancel')}>
                Cancel
              </button>
            {/if}
            {#if FINISHED.includes(job.status)}
              <button type="button" class="btn btn-ghost btn-sm" disabled={!!busy} onclick={() => remove(job)}>
                Remove
              </button>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  {/if}
  <Pagination
    page={filters.page}
    total={jobs.data.total}
    perPage={PER_PAGE}
    label="Queue pages"
    onpage={(page) => updateQuery({ page: page > 1 ? page : null })}
  />
{:else if jobs.loading}
  <p class="loading-line"><span class="spinner"></span> Loading queue…</p>
{/if}

{#if openVideoId}
  <VideoDialog id={openVideoId} onclose={() => (openVideoId = null)} />
{/if}

<style>
  .job-counts {
    gap: var(--space-2);
    margin-bottom: var(--space-3);
  }

  .job-counts li {
    padding: var(--space-1) var(--space-2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
  }

  .job-counts li.active {
    border-color: var(--terminal-green);
    color: var(--terminal-green);
  }

  .job {
    flex-wrap: wrap;
    align-items: flex-start;
  }

  .job.failed {
    box-shadow: inset 3px 0 0 var(--error);
  }

  .job-main {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    flex-basis: 280px;
  }

  .title-line {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    min-width: 0;
  }

  .title {
    font-weight: 600;
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .progress {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    max-width: 640px;
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    align-self: center;
  }
</style>
