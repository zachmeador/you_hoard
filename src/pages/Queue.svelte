<script>
  /** @import { Job, JobCounts, JobFilter, JobList, JobStatus } from '../lib/types' */
  import { untrack } from 'svelte'
  import { SvelteMap } from 'svelte/reactivity'
  import { api } from '../lib/api.js'
  import { bytes, dur, hm, int, JOB_KINDS, rel, whenShort } from '../lib/format.js'
  import { isPremiere, isRetry, jobResult, jobTook, looksGone, shortReason } from '../lib/jobs.js'
  import { jobItemTitle } from '../lib/format.js'
  import { Loader } from '../lib/loader.svelte.js'
  import { poll } from '../lib/poll.js'
  import { queue } from '../lib/queue.svelte.js'
  import { href, pageParam, router, updateQuery } from '../lib/router.svelte.js'
  import { librarySettings } from '../lib/settings.svelte.js'
  import { notify } from '../lib/toasts.svelte.js'
  import { clock } from '../lib/ui.svelte.js'
  import FilterTabs from '../components/FilterTabs.svelte'
  import Icon from '../components/Icon.svelte'
  import Pager from '../components/Pager.svelte'
  import RunningJob from '../components/RunningJob.svelte'
  import SelectField from '../components/SelectField.svelte'

  /** @typedef {'running' | 'waiting' | 'queued' | 'paused' | 'failed' | 'history'} Section */
  /** @typedef {JobList & { offset: number }} Slice a loaded list, with where in the full list it starts */

  const STEP = 100
  const PREVIEW = 25
  const RUNNING = 50
  /** @type {Section[]} */
  const SECTIONS = ['running', 'waiting', 'queued', 'paused', 'failed', 'history']
  /** @type {Record<Section, JobFilter | JobFilter[]>} */
  const STATUS = {
    running: 'running',
    waiting: 'waiting',
    queued: 'queued',
    paused: 'paused',
    failed: 'failed',
    history: ['completed', 'cancelled']
  }
  /** What "Select all" counts, by tab. */
  const NOUN = { waiting: 'waiting', queued: 'up next', paused: 'paused' }

  const view = $derived(SECTIONS.find((s) => s === router.query.tab) ?? '')
  const kind = $derived(router.query.kind ?? '')
  const page = $derived(pageParam(router.query.page))
  const offset = $derived(view ? (page - 1) * STEP : 0)

  /** @type {Record<Section, Loader<Slice>>} */
  const lists = {
    running: new Loader(),
    waiting: new Loader(),
    queued: new Loader(),
    paused: new Loader(),
    failed: new Loader(),
    history: new Loader()
  }
  /** Picked job ids, each with the status the job had when picked. @type {SvelteMap<number, JobStatus>} */
  const picked = new SvelteMap()
  let busy = $state(false)

  /** @param {Section} section */
  const items = (section) => lists[section].data?.items ?? []
  /** @param {Section} section */
  const totalOf = (section) => lists[section].data?.total ?? 0
  /**
   * Rows keep the offset they were loaded at, so their numbers stay right while the next page loads.
   * @param {Section} section
   */
  const startOf = (section) => lists[section].data?.offset ?? 0
  /** On screen: the section's own tab, or the All view when it has jobs. @param {Section} section */
  const shown = (section) => (view ? view === section : items(section).length > 0)
  /** @param {JobStatus} status */
  const pickedIds = (status) => [...picked].filter(([, s]) => s === status).map(([id]) => id)
  /** @param {string} word @param {number} n */
  const withCount = (word, n) => (n > 0 ? `${word} ${int(n)}` : word)

  /** Counts of the list(s) this view loads, so they follow the Jobs filter. @type {JobCounts} */
  const counts = $derived(
    (view ? [view] : SECTIONS).map((s) => lists[s].data?.counts).find((c) => c) ?? queue.counts
  )
  const running = $derived(items('running'))
  /** Rows on screen with a checkbox. */
  const selectable = $derived([
    ...(shown('waiting') ? items('waiting') : []),
    ...(shown('queued') ? items('queued') : []),
    ...(shown('paused') ? items('paused') : [])
  ])
  const everyPicked = $derived(picked.size > 0 && selectable.every((job) => picked.has(job.id)))
  const somePicked = $derived(picked.size > 0 && !everyPicked)
  const pausable = $derived(pickedIds('queued').length)
  const resumable = $derived(pickedIds('paused').length)
  /** The tab whose every job "Select all" can pick. */
  const pickTab = $derived(view === 'waiting' || view === 'queued' || view === 'paused' ? view : null)
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
    await Promise.all(
      (view ? [view] : SECTIONS).map((section, i) =>
        lists[section].run(
          async () => {
            const from = section === 'running' ? 0 : offset
            const res = await api.jobs.list({
              status: STATUS[section],
              kind: filter,
              limit: section === 'running' ? RUNNING : view ? STEP : PREVIEW,
              offset: from
            })
            // a kind filter narrows the counts, which would skew the sidebar badge
            if (i === 0 && !filter) queue.counts = { ...queue.counts, ...res.counts }
            return { ...res, offset: from }
          },
          { quiet }
        )
      )
    )
  }

  $effect(() => {
    void view
    void kind
    void page
    untrack(() => refresh(false))
    return poll(() => refresh(true), 3000, { immediate: false })
  })

  $effect(() => {
    void view
    void kind
    untrack(() => picked.clear())
  })

  $effect(() => {
    const data = view && view !== 'running' ? lists[view].data : undefined
    if (!data || data.items.length > 0 || page <= 1) return
    const last = Math.max(1, Math.ceil(data.total / STEP))
    if (last < page) untrack(() => updateQuery({ page: last > 1 ? last : null }))
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
  const jobAction = (job, action) =>
    act(async () => {
      await api.jobs.act(job.id, action)
      picked.delete(job.id)
    })

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

  async function resumeYoutube() {
    try {
      await api.jobs.resumeYoutube()
      notify.success('Downloads and checks resumed')
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

  /** @param {Job} job */
  function toggle(job) {
    if (picked.has(job.id)) picked.delete(job.id)
    else picked.set(job.id, job.status)
  }

  function toggleAll() {
    if (everyPicked) picked.clear()
    else for (const job of selectable) picked.set(job.id, job.status)
  }

  /** Picks every job of the tab, not just the page on screen. */
  async function pickEvery() {
    const section = pickTab
    if (!section || busy) return
    const filter = kind
    busy = true
    try {
      const { ids } = await api.jobs.ids({ status: section, kind: filter })
      if (view !== section || kind !== filter) return
      const status = section === 'paused' ? 'paused' : 'queued'
      for (const id of ids) picked.set(id, status)
    } catch (e) {
      notify.error(e)
    } finally {
      busy = false
    }
  }

  /** @param {'pause' | 'resume'} action */
  async function bulk(action) {
    const ids = pickedIds(action === 'pause' ? 'queued' : 'paused')
    if (!ids.length || busy) return
    busy = true
    await act(async () => {
      const changed =
        action === 'pause' ? (await api.jobs.pauseMany(ids)).paused : (await api.jobs.resumeMany(ids)).resumed
      const skipped = ids.length - changed
      const jobs = changed === 1 ? '1 job' : `${int(changed)} jobs`
      notify.success(
        `${action === 'pause' ? 'Paused' : 'Resumed'} ${jobs}${skipped > 0 ? ` · ${int(skipped)} skipped` : ''}`
      )
      picked.clear()
    })
    busy = false
  }

  /** @param {number} to */
  function goTo(to) {
    updateQuery({ page: to > 1 ? to : null })
    window.scrollTo({ top: 0 })
  }

  /** @param {Section} section */
  const rangeOf = (section) =>
    `${int(startOf(section) + 1)}–${int(startOf(section) + items(section).length)} of ${int(totalOf(section))}`
  /** @param {Section} section */
  const moreOf = (section) => totalOf(section) - items(section).length
  /** @param {Section} section */
  const pagesOf = (section) => Math.max(1, Math.ceil(totalOf(section) / STEP))

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

{#snippet heading(/** @type {Section} */ section, /** @type {string} */ title)}
  <div class="sec-h">
    <h2 class="label">{title}</h2>
    {#if view && items(section).length && pagesOf(section) > 1}<span class="n">{rangeOf(section)}</span>{/if}
  </div>
{/snippet}

{#snippet foot(/** @type {Section} */ section)}
  {#if view}
    <Pager label="Pages" {page} pages={pagesOf(section)} onpage={goTo} />
  {:else if moreOf(section) > 0}
    <p class="tfoot">
      and {int(moreOf(section))} more
      <button type="button" class="more-btn" onclick={() => updateQuery({ tab: section })}>View all</button>
    </p>
  {/if}
{/snippet}

{#snippet pick(/** @type {Job} */ job, /** @type {string} */ title)}
  <label class="chk">
    <input type="checkbox" checked={picked.has(job.id)} aria-label="Select {title}" onchange={() => toggle(job)} />
  </label>
{/snippet}

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
    <div class="k">combined speed</div>
  </div>
  <div class="bulk">
    <button type="button" class="btn" disabled={queue.counts.failed === 0} onclick={retryFailed}>
      <Icon name="retry" />Retry failed
    </button>
    <button
      type="button"
      class="btn"
      disabled={queue.counts.completed + queue.counts.cancelled === 0}
      onclick={clearFinished}
    >
      Clear finished
    </button>
  </div>
</div>

{#if queue.youtubePausedUntil}
  <div class="callout qpause">
    <Icon name="clock" class="mk" />
    <div>
      <span class="ttl2">YouTube asked for a bot check</span>
      Downloads and checks wait until {whenShort(queue.youtubePausedUntil, clock.now)} ({rel(queue.youtubePausedUntil, clock.now)}),
      instead of each one running into it. The wait grows if YouTube keeps asking.
      <div class="acts">
        <button type="button" class="btn" onclick={resumeYoutube}>Resume now</button>
      </div>
    </div>
  </div>
{/if}

<FilterTabs
  class="qtabs"
  label="Sections"
  value={view}
  {tabs}
  onchange={(value) => updateQuery({ tab: value })}
/>

{#if selectable.length > 0 || picked.size > 0}
  <div class="qsel" role="toolbar" aria-label="Selected jobs">
    <label class="chk">
      <input type="checkbox" checked={everyPicked} indeterminate={somePicked} onchange={toggleAll} />
      {picked.size ? `${int(picked.size)} selected` : 'Select all'}
    </label>
    {#if pickTab && everyPicked && selectable.length > 0 && totalOf(pickTab) > picked.size}
      <button type="button" class="more-btn" disabled={busy} onclick={pickEvery}>
        Select all {int(totalOf(pickTab))} {NOUN[pickTab]}
      </button>
    {/if}
    <div class="acts">
      {#if view === '' || view === 'waiting' || view === 'queued'}
        <button type="button" class="btn sm" disabled={busy || pausable === 0} onclick={() => bulk('pause')}>
          <Icon name="pause" />{withCount('Pause', pausable)}
        </button>
      {/if}
      {#if view === '' || view === 'paused'}
        <button type="button" class="btn sm" disabled={busy || resumable === 0} onclick={() => bulk('resume')}>
          <Icon name="play" />{withCount('Resume', resumable)}
        </button>
      {/if}
    </div>
  </div>
{/if}

{#if view === '' || view === 'running'}
  <div class="sec-h"><h2 class="label">Running</h2></div>
  {#each running as job (job.id)}
    <RunningJob {job} oncancel={() => jobAction(job, 'cancel')} />
  {:else}
    <p class="muted nothing">Nothing running.</p>
  {/each}
{/if}

{#if shown('waiting')}
  {@render heading('waiting', 'Waiting')}
  {#if items('waiting').length}
    <table class="tbl q pick stack">
      <thead>
        <tr>
          <th class="c-pick"><span class="sr">Select</span></th>
          <th class="c-when">Until</th>
          <th>Item</th>
          <th class="c-act"><span class="sr">Actions</span></th>
        </tr>
      </thead>
      <tbody>
        {#each items('waiting') as job (job.id)}
          {@const title = jobItemTitle(job)}
          {@const link = itemLink(job)}
          <tr class:picked={picked.has(job.id)}>
            <td class="c-pick keep">{@render pick(job, title)}</td>
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
    {@render foot('waiting')}
  {:else if lists.waiting.data}
    <p class="muted nothing">Nothing here.</p>
  {/if}
{/if}

{#if shown('queued')}
  {@render heading('queued', 'Up next')}
  {#if items('queued').length}
    <table class="tbl q pick stack">
      <thead>
        <tr>
          <th class="c-pick"><span class="sr">Select</span></th>
          <th class="c-pos num">#</th>
          <th>Item</th>
          <th class="num c-added">Added</th>
          <th class="c-act"><span class="sr">Actions</span></th>
        </tr>
      </thead>
      <tbody>
        {#each items('queued') as job, i (job.id)}
          {@const title = jobItemTitle(job)}
          {@const link = itemLink(job)}
          <tr class:picked={picked.has(job.id)}>
            <td class="c-pick keep">{@render pick(job, title)}</td>
            <td class="c-pos num">{startOf('queued') + i + 1}</td>
            <td class="c-main keep">
              {#if link}<a class="ttl" href={link}>{title}</a>{:else}<span class="ttl">{title}</span>{/if}
              <div class="m-meta">{JOB_KINDS[job.kind]} · added {rel(job.created_at, clock.now)}</div>
            </td>
            <td class="num c-added">{rel(job.created_at, clock.now)}</td>
            <td class="c-act c-side keep">
              <button type="button" class="btn sm quiet" aria-label="Pause {title}" onclick={() => jobAction(job, 'pause')}>
                <Icon name="pause" />
              </button>
              <button type="button" class="btn sm quiet" aria-label="Cancel {title}" onclick={() => jobAction(job, 'cancel')}>
                <Icon name="x" />
              </button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    {@render foot('queued')}
  {:else if lists.queued.data}
    <p class="muted nothing">Nothing here.</p>
  {/if}
{/if}

{#if shown('paused')}
  {@render heading('paused', 'Paused')}
  {#if items('paused').length}
    <table class="tbl q pick stack">
      <thead>
        <tr>
          <th class="c-pick"><span class="sr">Select</span></th>
          <th>Item</th>
          <th class="num c-added">Added</th>
          <th class="c-act"><span class="sr">Actions</span></th>
        </tr>
      </thead>
      <tbody>
        {#each items('paused') as job (job.id)}
          {@const title = jobItemTitle(job)}
          {@const link = itemLink(job)}
          <tr class:picked={picked.has(job.id)}>
            <td class="c-pick keep">{@render pick(job, title)}</td>
            <td class="c-main keep">
              {#if link}<a class="ttl" href={link}>{title}</a>{:else}<span class="ttl">{title}</span>{/if}
              <div class="m-meta">{JOB_KINDS[job.kind]} · added {rel(job.created_at, clock.now)}</div>
            </td>
            <td class="num c-added">{rel(job.created_at, clock.now)}</td>
            <td class="c-act c-side keep">
              <button type="button" class="btn sm" aria-label="Resume {title}" onclick={() => jobAction(job, 'resume')}>
                <Icon name="play" />Resume
              </button>
              <button type="button" class="btn sm quiet" aria-label="Cancel {title}" onclick={() => jobAction(job, 'cancel')}>
                <Icon name="x" />
              </button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    {@render foot('paused')}
  {:else if lists.paused.data}
    <p class="muted nothing">Nothing here.</p>
  {/if}
{/if}

{#if shown('failed')}
  {@render heading('failed', 'Failed')}
  {#if items('failed').length}
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
        {#each items('failed') as job (job.id)}
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
    {@render foot('failed')}
  {:else if lists.failed.data}
    <p class="muted nothing">Nothing here.</p>
  {/if}
{/if}

{#if shown('history')}
  {@render heading('history', 'History')}
  {#if items('history').length}
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
        {#each items('history') as job (job.id)}
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
    {@render foot('history')}
  {:else if lists.history.data}
    <p class="muted nothing">Nothing here.</p>
  {/if}
{/if}
