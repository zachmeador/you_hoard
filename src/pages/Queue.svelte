<script>
  /** @import { Job, JobCounts, JobList } from '../lib/types' */
  import { untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { bytes, dur, hm, int, JOB_KINDS, rel, whenShort } from '../lib/format.js'
  import { isPremiere, isRetry, isWaiting, jobResult, jobTook, looksGone, shortReason } from '../lib/jobs.js'
  import { jobItemTitle } from '../lib/format.js'
  import { Loader } from '../lib/loader.svelte.js'
  import { poll } from '../lib/poll.js'
  import { queue } from '../lib/queue.svelte.js'
  import { href, router, updateQuery } from '../lib/router.svelte.js'
  import { librarySettings } from '../lib/settings.svelte.js'
  import { notify } from '../lib/toasts.svelte.js'
  import { clock } from '../lib/ui.svelte.js'
  import FilterTabs from '../components/FilterTabs.svelte'
  import Icon from '../components/Icon.svelte'
  import RunningJob from '../components/RunningJob.svelte'
  import SelectField from '../components/SelectField.svelte'

  const STEP = 100

  const view = $derived(router.query.tab ?? '')
  const kind = $derived(router.query.kind ?? '')
  const base = $derived(view ? STEP : 25)

  /** @type {Record<'running' | 'queued' | 'paused' | 'failed' | 'completed' | 'cancelled', Loader<JobList>>} */
  const lists = {
    running: new Loader(),
    queued: new Loader(),
    paused: new Loader(),
    failed: new Loader(),
    completed: new Loader(),
    cancelled: new Loader()
  }
  let extra = $state({ queued: 0, failed: 0, history: 0 })

  /** @type {JobCounts} */
  const counts = $derived(
    Object.values(lists).find((l) => l.data)?.data?.counts ?? queue.counts
  )
  const running = $derived(lists.running.data?.items ?? [])
  const queuedItems = $derived(lists.queued.data?.items ?? [])
  const waiting = $derived(
    queuedItems.filter((j) => isWaiting(j, clock.now)).sort((a, b) => (a.run_after ?? '').localeCompare(b.run_after ?? ''))
  )
  const ready = $derived(queuedItems.filter((j) => !isWaiting(j, clock.now)))
  const paused = $derived(lists.paused.data?.items ?? [])
  const failed = $derived(lists.failed.data?.items ?? [])
  const history = $derived(
    [...(lists.completed.data?.items ?? []), ...(lists.cancelled.data?.items ?? [])].sort(
      (a, b) => (b.finished_at ?? '').localeCompare(a.finished_at ?? '')
    )
  )
  const cap = $derived(base + extra.queued)
  const shownReady = $derived(ready.slice(0, cap))
  const upNext = $derived(view === 'paused' ? paused : view === 'queued' ? shownReady : [...shownReady, ...paused])
  const downloads = $derived(queue.running.filter((j) => j.kind === 'download'))
  const slots = $derived(librarySettings.current?.max_concurrent_downloads ?? 2)
  const combined = $derived(
    downloads.reduce((sum, j) => sum + (j.progress?.phase === 'downloading' ? (j.progress.speed ?? 0) : 0), 0)
  )
  const finished = $derived(counts.completed + counts.cancelled)
  const tabs = $derived([
    { value: '', label: 'All' },
    { value: 'running', label: 'Running', count: counts.running },
    { value: 'waiting', label: 'Waiting', count: counts.waiting },
    { value: 'queued', label: 'Up next', count: counts.queued },
    { value: 'paused', label: 'Paused', count: counts.paused },
    { value: 'failed', label: 'Failed', count: counts.failed },
    { value: 'history', label: 'History', count: finished }
  ])

  /** @param {boolean} quiet */
  async function refresh(quiet) {
    const filter = kind || undefined
    /** @param {'running' | 'queued' | 'paused' | 'failed' | 'completed' | 'cancelled'} status @param {number} limit */
    const load = (status, limit) =>
      lists[status].run(() => api.jobs.list({ status, kind: filter, limit }), { quiet })
    const all = view === ''
    const tasks = []
    if (all || view === 'running') tasks.push(load('running', 50))
    if (all || view === 'waiting' || view === 'queued') tasks.push(load('queued', 200 + extra.queued))
    if (all || view === 'paused') tasks.push(load('paused', 100))
    if (all || view === 'failed') tasks.push(load('failed', base + extra.failed))
    if (all || view === 'history') {
      tasks.push(load('completed', base + extra.history), load('cancelled', Math.ceil((base + extra.history) / 2)))
    }
    await Promise.all(tasks)
    const latest = lists.running.data?.counts
    if (latest) queue.counts = { ...queue.counts, ...latest }
  }

  $effect(() => {
    void view
    void kind
    void extra.queued
    void extra.failed
    void extra.history
    untrack(() => refresh(false))
    return poll(() => refresh(true), 3000, { immediate: false })
  })

  /** @param {() => Promise<unknown>} action */
  async function act(action) {
    try {
      await action()
      await refresh(true)
      queue.refresh().catch(() => {})
    } catch (e) {
      notify.error(e)
    }
  }

  /** @param {Job} job @param {'cancel' | 'retry' | 'pause' | 'resume'} action */
  const jobAction = (job, action) => act(() => api.jobs.act(job.id, action))

  /** A waiting job runs again straight away: cancelling and retrying clears its wait. @param {Job} job */
  const runNow = (job) =>
    act(async () => {
      await api.jobs.act(job.id, 'cancel')
      await api.jobs.act(job.id, 'retry')
    })

  /** @param {Job} job */
  const removeJob = (job) => act(() => api.jobs.remove(job.id))

  async function retryFailed() {
    try {
      const { retried } = await api.jobs.retryFailed()
      notify.success(retried === 1 ? 'Retrying 1 failed job' : `Retrying ${int(retried)} failed jobs`)
      await refresh(true)
      queue.refresh().catch(() => {})
    } catch (e) {
      notify.error(e)
    }
  }

  async function clearFinished() {
    try {
      const { cleared } = await api.jobs.clearFinished()
      notify.success(cleared === 1 ? 'Cleared 1 finished job' : `Cleared ${int(cleared)} finished jobs`)
      await refresh(true)
      queue.refresh().catch(() => {})
    } catch (e) {
      notify.error(e)
    }
  }

  /** @param {'queued' | 'failed' | 'history'} section */
  function showMore(section) {
    extra[section] += STEP
  }

  /** @param {Job} job */
  function itemLink(job) {
    if (job.video) return href(`/video/${job.video.id}`)
    if (job.subscription) return href(`/subscriptions/${job.subscription.id}`)
    return null
  }
</script>

<svelte:head>
  <title>Queue · YouHoard</title>
</svelte:head>

<header class="ph">
  <h1>Queue</h1>
  <div class="ph-r">
    <SelectField
      label="Jobs"
      value={kind}
      options={[
        { value: '', label: 'All' },
        { value: 'download', label: 'Downloads' },
        { value: 'check', label: 'Checks' },
        { value: 'scan', label: 'Scans' }
      ]}
      onchange={(value) => updateQuery({ kind: value })}
    />
  </div>
</header>

<div class="qsum">
  <div>
    <div class="big">{downloads.length}<small>of {slots} slots</small></div>
    <div class="slots" aria-hidden="true">
      {#each Array.from({ length: slots }, (_, i) => i) as i (i)}<i class:on={i < downloads.length}></i>{/each}
    </div>
    <div class="k">downloading now</div>
  </div>
  <div>
    <div class="big">{bytes(combined)}<small>/s</small></div>
    <div class="k">combined speed · {int(counts.queued + counts.waiting)} queued</div>
  </div>
  <div class="bulk">
    <button type="button" class="btn" disabled={counts.failed === 0} onclick={retryFailed}>
      <Icon name="retry" />Retry failed <span class="muted">{int(counts.failed)}</span>
    </button>
    <button type="button" class="btn" disabled={finished === 0} onclick={clearFinished}>Clear finished</button>
  </div>
</div>

<FilterTabs
  class="qtabs"
  label="Sections"
  value={view}
  {tabs}
  onchange={(value) => updateQuery({ tab: value })}
/>

{#if view === '' || view === 'running'}
  <div class="sec-h"><h2 class="label">Running</h2><span class="n">{running.length}</span></div>
  {#each running as job (job.id)}
    <RunningJob {job} oncancel={() => jobAction(job, 'cancel')} />
  {:else}
    <p class="muted nothing">Nothing running.</p>
  {/each}
{/if}

{#if (view === '' || view === 'waiting') && waiting.length}
  <div class="sec-h"><h2 class="label">Waiting</h2><span class="n">{counts.waiting}</span></div>
  <table class="tbl q stack">
    <thead>
      <tr>
        <th class="c-when">Until</th>
        <th>Item</th>
        <th class="c-act"><span class="sr">Actions</span></th>
      </tr>
    </thead>
    <tbody>
      {#each waiting as job (job.id)}
        {@const title = jobItemTitle(job)}
        {@const link = itemLink(job)}
        <tr>
          <td class="c-when wt"><b>{whenShort(job.run_after, clock.now)}</b><span>{rel(job.run_after, clock.now)}</span></td>
          <td class="c-main keep">
            {#if link}<a class="ttl" href={link}>{title}</a>{:else}<span class="ttl">{title}</span>{/if}
            <div class="why">
              {#if isRetry(job)}
                Attempt {job.attempts + 1} of 4 after <span class="e">{shortReason(job.error ?? '')}</span>
              {:else if isPremiere(job)}
                Premiere
              {:else}
                {job.error ?? ''}
              {/if}
            </div>
            <div class="m-meta">Until {whenShort(job.run_after, clock.now)} ({rel(job.run_after, clock.now)})</div>
          </td>
          <td class="c-act c-side keep">
            <button type="button" class="btn sm quiet" aria-label="Run now: {title}" onclick={() => runNow(job)}>Run now</button>
            <button type="button" class="btn sm quiet" aria-label="Cancel {title}" onclick={() => jobAction(job, 'cancel')}>
              <Icon name="x" />
            </button>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}

{#if (view === '' || view === 'queued' || view === 'paused') && (upNext.length || view)}
  <div class="sec-h">
    <h2 class="label">{view === 'paused' ? 'Paused' : 'Up next'}</h2>
    <span class="n">
      {#if view === 'paused'}{int(counts.paused)}
      {:else if view === 'queued'}{int(counts.queued)}
      {:else}{int(counts.queued)} queued · {int(counts.paused)} paused{/if}
    </span>
  </div>
  {#if upNext.length}
    <table class="tbl q stack">
      <thead>
        <tr>
          <th class="c-pos num">#</th>
          <th>Item</th>
          <th class="num c-added">Added</th>
          <th class="c-act"><span class="sr">Actions</span></th>
        </tr>
      </thead>
      <tbody>
        {#each upNext as job, i (job.id)}
          {@const title = jobItemTitle(job)}
          {@const link = itemLink(job)}
          <tr class:s-paused={job.status === 'paused'}>
            <td class="c-pos num">{job.status === 'paused' ? '—' : i + 1}</td>
            <td class="c-main keep">
              {#if link}<a class="ttl" href={link}>{title}</a>{:else}<span class="ttl">{title}</span>{/if}
              {#if job.status === 'paused'}<div class="why"><span class="st paused">Paused</span></div>{/if}
              <div class="m-meta">{JOB_KINDS[job.kind]} · added {rel(job.created_at, clock.now)}</div>
            </td>
            <td class="num c-added">{rel(job.created_at, clock.now)}</td>
            <td class="c-act c-side keep">
              {#if job.status === 'paused'}
                <button type="button" class="btn sm" aria-label="Resume {title}" onclick={() => jobAction(job, 'resume')}>
                  <Icon name="play" />Resume
                </button>
              {:else}
                <button type="button" class="btn sm quiet" aria-label="Pause {title}" onclick={() => jobAction(job, 'pause')}>
                  <Icon name="pause" />
                </button>
              {/if}
              <button type="button" class="btn sm quiet" aria-label="Cancel {title}" onclick={() => jobAction(job, 'cancel')}>
                <Icon name="x" />
              </button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    {#if view !== 'paused' && counts.queued > shownReady.length}
      <p class="tfoot">
        and {int(counts.queued - shownReady.length)} more
        <button type="button" class="more-btn" onclick={() => showMore('queued')}>Show more</button>
      </p>
    {/if}
  {:else}
    <p class="muted nothing">Nothing here.</p>
  {/if}
{/if}

{#if view === '' || view === 'failed'}
  {#if failed.length || view}
    <div class="sec-h">
      <h2 class="label">Failed</h2>
      <span class="n">{int(counts.failed)}</span>
      {#if failed.length}
        <span class="r">
          <button type="button" class="btn sm" onclick={retryFailed}><Icon name="retry" />Retry all</button>
        </span>
      {/if}
    </div>
    {#if failed.length}
      <table class="tbl q stack">
        <thead>
          <tr>
            <th class="c-kind">Job</th>
            <th>Item</th>
            <th class="num c-tries">Tries</th>
            <th class="num c-fin">Failed</th>
            <th class="c-act"><span class="sr">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {#each failed as job (job.id)}
            {@const title = jobItemTitle(job)}
            {@const link = itemLink(job)}
            {@const gone = job.kind === 'download' && looksGone(job.error)}
            <tr>
              <td class="c-kind"><span class="kindtag">{JOB_KINDS[job.kind]}</span></td>
              <td class="c-main keep">
                {#if link}<a class="ttl" href={link}>{title}</a>{:else}<span class="ttl">{title}</span>{/if}
                {#if job.error}<div class="row-err" style="white-space: normal">{job.error}</div>{/if}
                {#if gone}<div class="row-note">Gone from YouTube · not retried</div>{/if}
                <div class="m-meta">
                  {JOB_KINDS[job.kind]} · {job.attempts} {job.attempts === 1 ? 'try' : 'tries'} · {rel(job.finished_at, clock.now)}
                </div>
              </td>
              <td class="num c-tries">{job.attempts}</td>
              <td class="num c-fin">{rel(job.finished_at, clock.now)}</td>
              <td class="c-act c-side keep">
                {#if !gone}
                  <button type="button" class="btn sm" aria-label="Retry {title}" onclick={() => jobAction(job, 'retry')}>
                    <Icon name="retry" />Retry
                  </button>
                {/if}
                <button type="button" class="btn sm quiet" aria-label="Remove {title}" onclick={() => removeJob(job)}>
                  <Icon name="x" />
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
      {#if counts.failed > failed.length}
        <p class="tfoot">
          and {int(counts.failed - failed.length)} more
          <button type="button" class="more-btn" onclick={() => showMore('failed')}>Show more</button>
        </p>
      {/if}
    {:else}
      <p class="muted nothing">Nothing here.</p>
    {/if}
  {/if}
{/if}

{#if view === '' || view === 'history'}
  {#if history.length || view}
    <div class="sec-h">
      <h2 class="label">History</h2>
      <span class="n">{int(counts.completed)} completed · {int(counts.cancelled)} cancelled</span>
    </div>
    {#if history.length}
      <table class="tbl q hist stack">
        <thead>
          <tr>
            <th class="c-when">Finished</th>
            <th class="c-kind">Job</th>
            <th>Item</th>
            <th class="c-res">Result</th>
            <th class="num c-took">Took</th>
          </tr>
        </thead>
        <tbody>
          {#each history.slice(0, base + extra.history) as job (job.id)}
            {@const title = jobItemTitle(job)}
            {@const link = itemLink(job)}
            {@const took = jobTook(job)}
            <tr>
              <td class="c-when"><b>{hm(job.finished_at)}</b><span>{rel(job.finished_at, clock.now)}</span></td>
              <td class="c-kind"><span class="kindtag">{JOB_KINDS[job.kind]}</span></td>
              <td class="c-main keep">
                {#if job.kind === 'scan'}
                  <span class="ttl">Library rescan</span>
                {:else if link}
                  <a class="ttl" href={link}>{title}</a>
                {:else}
                  <span class="ttl">{title}</span>
                {/if}
                <div class="m-meta">{hm(job.finished_at)} · {JOB_KINDS[job.kind]} · {jobResult(job)}</div>
              </td>
              <td class="c-res">
                {#if job.status === 'cancelled'}
                  <span class="st cancelled">{jobResult(job)}</span>
                {:else if job.kind === 'download'}
                  <span class="st completed">{jobResult(job)}</span>
                {:else}
                  <span class="dim">{jobResult(job)}</span>
                {/if}
              </td>
              <td class="num c-took">{took != null ? dur(took) : '—'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      {#if finished > history.length}
        <p class="tfoot">
          and {int(finished - history.length)} more
          <button type="button" class="more-btn" onclick={() => showMore('history')}>Show more</button>
        </p>
      {/if}
    {:else}
      <p class="muted nothing">Nothing here.</p>
    {/if}
  {/if}
{/if}
