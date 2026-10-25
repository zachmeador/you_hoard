<script>
  /** @import { Subscription } from '../lib/types' */
  import { int, rel } from '../lib/format.js'
  import { clock } from '../lib/ui.svelte.js'
  import Icon from './Icon.svelte'

  /** @type {{ sub: Subscription }} */
  let { sub } = $props()

  const last = $derived(sub.last_check)
  const result = $derived(last?.result)
</script>

{#if sub.checking}
  <div class="lc run">
    <span class="when"><Icon name="refresh" />Checking now…</span>
    <div class="prog ind"><i></i></div>
  </div>
{:else if !last}
  <div class="lc"><span class="when">Never checked</span></div>
{:else if last.status === 'failed'}
  <div class="lc fail">
    <span class="when"><Icon name="x" />Failed {rel(last.finished_at, clock.now)}</span>
    {#if last.error}<span class="sum" title={last.error}>{last.error}</span>{/if}
  </div>
{:else}
  <div class="lc">
    <span class="when"><Icon name="check" />{rel(last.finished_at, clock.now)}</span>
    {#if result}
      <span class="sum">
        {int(result.listed)} listed · {int(result.new_entries)} new · {int(result.queued)} queued{result.removed
          ? ` · ${int(result.removed)} removed`
          : ''}{result.full ? ' (full)' : ''}
      </span>
    {/if}
  </div>
{/if}
