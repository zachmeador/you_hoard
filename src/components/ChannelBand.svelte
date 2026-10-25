<script>
  /** @import { Channel, Subscription } from '../lib/types' */
  import { bytes, compact, int, policyLabel, POLICIES } from '../lib/format.js'
  import { href } from '../lib/router.svelte.js'
  import { openAdd } from '../lib/ui.svelte.js'
  import Avatar from './Avatar.svelte'
  import HoldBar from './HoldBar.svelte'
  import Icon from './Icon.svelte'
  import Pips from './Pips.svelte'

  /** @type {{ channel: Channel, subscription: Subscription | null, onclear: () => void }} */
  let { channel, subscription, onclear } = $props()

  const counts = $derived(
    subscription
      ? subscription.counts
      : {
          entries: channel.video_count,
          archived: channel.archived_count,
          queued: 0,
          failed: 0,
          not_selected: Math.max(0, channel.video_count - channel.archived_count),
          removed: 0
        }
  )
</script>

<section class="chband" aria-label="Channel">
  <div class="who">
    <Avatar name={channel.name} src={channel.avatar_url} large />
    <div style="min-width: 0">
      <h2>
        {channel.name}
        {#if channel.verified}<span class="verified" title="Verified"><Icon name="verified" /><span class="sr">Verified</span></span>{/if}
      </h2>
      <p class="meta">
        {#if channel.handle}<span>{channel.handle}</span>{/if}
        {#if channel.subscriber_count}<span>{compact(channel.subscriber_count)} subscribers</span>{/if}
        <a class="lnk" href={channel.youtube_url} target="_blank" rel="noopener noreferrer">YouTube ↗</a>
      </p>
    </div>
  </div>
  <div class="hold">
    <div class="row">
      <span><b>{int(channel.archived_count)}</b> of {int(counts.entries)} archived</span>
      <span>{bytes(channel.archived_size)}</span>
    </div>
    <HoldBar {counts} />
  </div>
  <div class="acts">
    {#if subscription}
      <a class="btn sm" href={href(`/subscriptions/${subscription.id}`)}>
        <Pips n={POLICIES[subscription.download_policy].pips} />{policyLabel(subscription)}
      </a>
    {:else}
      <button type="button" class="btn sm" onclick={() => openAdd(channel.youtube_url)}>Subscribe…</button>
    {/if}
    <button type="button" class="btn sm quiet" onclick={onclear}><Icon name="x" />Clear</button>
  </div>
</section>
