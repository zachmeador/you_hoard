<script>
  /** @import { Subscription } from '../lib/types' */
  import { checkSummary } from '../lib/format.js'
  import StatusBadge from './StatusBadge.svelte'
  import Time from './Time.svelte'

  /** @type {{ sub: Subscription }} */
  let { sub } = $props()

  const last = $derived(sub.last_check)
</script>

<div class="check-status">
  <div class="line">
    <span class="muted">Last check</span>
    {#if sub.checking}
      <span class="cluster"><span class="spinner"></span> Checking now…</span>
    {:else if last}
      <StatusBadge status={last.status} />
      <Time value={last.finished_at ?? sub.last_checked_at} />
      {#if last.result}<span class="muted">{checkSummary(last.result)}</span>{/if}
    {:else}
      <span>Never</span>
    {/if}
  </div>
  {#if !sub.checking && last?.error}<p class="error-text">{last.error}</p>{/if}
  <div class="line">
    <span class="muted">Next check</span>
    {#if !sub.enabled}
      <span>Paused</span>
    {:else}
      <Time value={sub.next_check_at} />
    {/if}
  </div>
</div>

<style>
  .check-status {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    font-size: 0.75rem;
  }

  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-2);
  }

  .line > .muted:first-child {
    min-width: 5.5rem;
  }
</style>
