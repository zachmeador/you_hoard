<script>
  /** @import { Entry, SubscriptionKind } from '../lib/types' */
  import { compact, dmy, dur, isoDate, KIND_WORDS } from '../lib/format.js'
  import { lostEntry } from '../lib/entries.js'
  import { href } from '../lib/router.svelte.js'
  import EntryStatus from './EntryStatus.svelte'
  import Icon from './Icon.svelte'

  /**
   * @type {{
   *   entries: Entry[],
   *   kind: SubscriptionKind,
   *   busy: string,
   *   ondownload: (entry: Entry) => void
   * }}
   */
  let { entries, kind, busy, ondownload } = $props()

  /** @param {Entry} e */
  const typeWord = (e) => (e.live_status === 'is_upcoming' ? 'Premiere' : KIND_WORDS[e.video_type])
</script>

<table class="tbl inv stack">
  <thead>
    <tr>
      <th class="c-pos num">#</th>
      <th>Title</th>
      <th class="c-kind">Type</th>
      <th class="num c-len">Length</th>
      <th class="num c-views">Views</th>
      <th class="num c-seen">First seen</th>
      <th class="c-st">Status</th>
      <th class="c-act"><span class="sr">Actions</span></th>
    </tr>
  </thead>
  <tbody>
    {#each entries as entry (entry.youtube_id)}
      {@const lost = lostEntry(entry)}
      {@const held = !!entry.removed_at && !lost}
      {@const title = entry.title ?? entry.youtube_id}
      <tr class="s-{entry.status}" class:lost>
        <td class="c-pos num">{entry.position}</td>
        <td class="c-main keep">
          {#if entry.video_id}
            <a class="ttl" href={href(`/video/${entry.video_id}`)}>
              {#if held}<i class="lz" aria-hidden="true"></i>{/if}{title}
            </a>
          {:else}
            <span class="ttl">{title}</span>
          {/if}
          {#if kind === 'playlist' && entry.channel_name}<div class="row-sub">{entry.channel_name}</div>{/if}
          {#if held}
            <div class="row-note"><i class="lz g" aria-hidden="true"></i> Removed from source {dmy(entry.removed_at)} · archived</div>
          {:else if lost}
            <div class="row-note">Removed from source {dmy(entry.removed_at)}</div>
          {/if}
          <div class="m-meta">
            #{entry.position} · {typeWord(entry)}{entry.duration ? ` · ${dur(entry.duration)}` : ''} · seen {isoDate(entry.first_seen_at)}<br />
            <EntryStatus {entry} />
          </div>
        </td>
        <td class="c-kind">{typeWord(entry)}</td>
        <td class="num c-len">{entry.duration ? dur(entry.duration) : '—'}</td>
        <td class="num c-views">{entry.view_count != null ? compact(entry.view_count) : '—'}</td>
        <td class="num c-seen">{isoDate(entry.first_seen_at)}</td>
        <td class="c-st"><EntryStatus {entry} /></td>
        <td class="c-act c-side keep">
          {#if !lost && entry.live_status !== 'is_upcoming'}
            {#if entry.status === 'not_selected' || entry.status === 'missing'}
              <button type="button" class="btn sm" disabled={busy === entry.youtube_id} onclick={() => ondownload(entry)}>
                <Icon name="dl" />Download
              </button>
            {:else if entry.status === 'failed'}
              <button type="button" class="btn sm" disabled={busy === entry.youtube_id} onclick={() => ondownload(entry)}>
                <Icon name="retry" />Retry
              </button>
            {:else if entry.status === 'deleted'}
              <button type="button" class="btn sm quiet" disabled={busy === entry.youtube_id} onclick={() => ondownload(entry)}>
                <Icon name="dl" />Again
              </button>
            {/if}
          {/if}
          <a
            class="ext"
            href="https://www.youtube.com/watch?v={entry.youtube_id}"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Open {title} on YouTube"
          >
            <Icon name="ext" />
          </a>
        </td>
      </tr>
    {/each}
  </tbody>
</table>
