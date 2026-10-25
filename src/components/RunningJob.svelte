<script>
  /** @import { Job } from '../lib/types' */
  import { bytes, eta, percent, rel, speed } from '../lib/format.js'
  import { jobItemTitle } from '../lib/format.js'
  import { href } from '../lib/router.svelte.js'
  import { clock } from '../lib/ui.svelte.js'
  import Icon from './Icon.svelte'
  import Thumb from './Thumb.svelte'

  /** @type {{ job: Job, oncancel: () => void }} */
  let { job, oncancel } = $props()

  const progress = $derived(job.progress)
  const title = $derived(jobItemTitle(job))
</script>

{#if job.kind === 'download'}
  <div class="run">
    {#if job.video}
      <a class="mini" href={href(`/video/${job.video.id}`)} tabindex="-1" aria-hidden="true"><Thumb src={null} /></a>
    {:else}
      <span class="mini"><Thumb src={null} /></span>
    {/if}
    <div style="min-width: 0">
      {#if job.video}
        <a class="ttl" href={href(`/video/${job.video.id}`)}>{title}</a>
      {:else}
        <span class="ttl">{title}</span>
      {/if}
      <div class="meta"><span>job #{job.id}</span></div>
      {#if progress?.phase === 'processing'}
        <div class="prog ind"><i></i></div>
        <div class="stats">
          <span class="pct">Processing</span>
          <span>merging with ffmpeg</span>
          {#if progress.total_bytes}<span><b>{bytes(progress.total_bytes)}</b></span>{/if}
          <span>started {rel(job.started_at, clock.now)}</span>
        </div>
      {:else}
        <div class="prog"><i style:width="{progress?.percent ?? 0}%"></i></div>
        <div class="stats">
          <span class="pct">{progress ? percent(progress.percent) : 'Starting'}</span>
          {#if progress?.total_bytes}
            <span><b>{bytes(progress.downloaded_bytes)}</b> of {bytes(progress.total_bytes)}</span>
          {/if}
          {#if progress?.speed}<span><b>{speed(progress.speed)}</b></span>{/if}
          {#if progress?.eta != null}<span>ETA <b>{eta(progress.eta)}</b></span>{/if}
          <span>attempt {Math.max(1, job.attempts)}</span>
          <span>started {rel(job.started_at, clock.now)}</span>
        </div>
      {/if}
    </div>
    <div class="acts">
      <button type="button" class="btn sm" aria-label="Cancel {title}" onclick={oncancel}><Icon name="x" />Cancel</button>
    </div>
  </div>
{:else}
  <div class="run check">
    <div class="glyph"><Icon name="refresh" /></div>
    <div style="min-width: 0">
      {#if job.subscription}
        <a class="ttl" href={href(`/subscriptions/${job.subscription.id}`)}>Checking {job.subscription.title}</a>
      {:else}
        <span class="ttl">Library rescan</span>
      {/if}
      <div class="meta"><span>started {rel(job.started_at, clock.now)}</span></div>
      <div class="prog ind"><i></i></div>
    </div>
    <div class="acts">
      <button type="button" class="btn sm" aria-label="Cancel {job.subscription ? `check of ${job.subscription.title}` : 'rescan'}" onclick={oncancel}>
        <Icon name="x" />Cancel
      </button>
    </div>
  </div>
{/if}
