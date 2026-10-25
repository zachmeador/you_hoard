<script>
  /** @import { Entry } from '../lib/types' */
  import { lostEntry } from '../lib/entries.js'
  import StatusWord from './StatusWord.svelte'

  /** @type {{ entry: Entry }} */
  let { entry } = $props()
</script>

{#if entry.live_status === 'is_upcoming'}
  <span class="st upcoming">Upcoming</span>
{:else if lostEntry(entry)}
  <span class="st lost">Never downloaded</span>
{:else if entry.status === 'not_selected'}
  <span class="st notsel">Not selected</span>
{:else}
  <StatusWord status={entry.status} videoId={entry.video_id} bar />
{/if}
