<script>
  /** @import { SubscriptionCounts } from '../lib/types' */
  import { int } from '../lib/format.js'

  /** @type {{ counts: SubscriptionCounts, big?: boolean }} */
  let { counts, big = false } = $props()

  const segments = $derived.by(() => {
    const gone = Math.min(counts.removed || 0, counts.archived)
    /** @type {[string, number][]} */
    const all = [
      ['a', counts.archived - gone],
      ['g', gone],
      ['q', counts.queued],
      ['f', counts.failed],
      ['d', counts.deleted || 0],
      ['n', counts.not_selected]
    ]
    return all.filter(([, n]) => n > 0)
  })
  const label = $derived(
    `${int(counts.archived)} archived, ${int(counts.queued)} queued, ${int(counts.failed)} failed, ` +
      `${int(counts.not_selected)} not selected, of ${int(counts.entries)} entries`
  )
</script>

<div class="hbar" class:big role="img" aria-label={label}>
  {#each segments as [kind, n] (kind)}
    <i class={kind} style:flex={n}></i>
  {/each}
</div>
