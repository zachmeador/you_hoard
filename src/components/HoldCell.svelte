<script>
  /** @import { SubscriptionCounts } from '../lib/types' */
  import { int } from '../lib/format.js'
  import HoldBar from './HoldBar.svelte'

  /** @type {{ counts: SubscriptionCounts }} */
  let { counts } = $props()
</script>

<div class="hold-cell">
  <HoldBar {counts} />
  <div class="nums">
    <span><b>{int(counts.archived)}</b> / {int(counts.entries)}</span>
    {#if counts.queued}<span class="q"><b>{int(counts.queued)}</b> queued</span>{/if}
    {#if counts.failed}<span class="f"><b>{int(counts.failed)}</b> failed</span>{/if}
    {#if counts.not_selected}<span><b>{int(counts.not_selected)}</b> not selected</span>{/if}
    {#if counts.removed}<span class="g"><b>{int(counts.removed)}</b> removed</span>{/if}
  </div>
</div>
