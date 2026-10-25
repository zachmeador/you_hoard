<script>
  /** @import { Subscription, VideoDetail } from '../lib/types' */
  import { copyText } from '../lib/clipboard.js'
  import {
    AVAILABILITY,
    audioCodec,
    bytes,
    hasTime,
    isoDate,
    isoTime,
    languageName,
    policyLabel,
    qualityWithRate,
    resolution,
    videoCodec
  } from '../lib/format.js'
  import { href } from '../lib/router.svelte.js'
  import { librarySettings } from '../lib/settings.svelte.js'
  import { notify } from '../lib/toasts.svelte.js'
  import Icon from './Icon.svelte'
  import StatusWord from './StatusWord.svelte'

  const TAGS_SHOWN = 12

  /** @type {{ video: VideoDetail, subscription: Subscription | null }} */
  let { video, subscription } = $props()

  let allTags = $state(false)

  const archived = $derived(video.status === 'archived')
  const wide = $derived(video.width && video.height ? video.width / video.height > 2 : false)
  const codecs = $derived([videoCodec(video.vcodec), audioCodec(video.acodec)].filter(Boolean).join(' + '))
  const audio = $derived(
    (video.audio_languages ?? []).map((code, i, all) => {
      const name = languageName(code, librarySettings.options.languages)
      return i === 0 && all.length > 1 ? `${name} (default)` : name
    })
  )
  const tags = $derived(video.tags ?? [])
  const category = $derived((video.categories ?? []).join(', '))
  const access = $derived(video.availability ? (AVAILABILITY[video.availability] ?? '') : '')
  const typeWord = $derived({ video: 'Video', short: 'Short', live: 'Stream replay' }[video.video_type])

  async function copyId() {
    if (await copyText(video.youtube_id)) notify.success(`Copied ${video.youtube_id}`)
  }
</script>

<section aria-labelledby="details-h">
  <h2 class="label" id="details-h">Details</h2>
  <dl class="kv">
    <dt>Status</dt>
    <dd>
      <StatusWord status={video.status} videoId={video.id} />
      {#if archived && video.archived_at}<span class="muted">{isoTime(video.archived_at)}</span>{/if}
    </dd>
    <dt>YouTube</dt>
    <dd>
      {#if video.unavailable}
        <span class="st gone">Gone since {isoDate(video.unavailable_at)}</span>
      {:else}
        Available
      {/if}
    </dd>
    {#if access}<dt>Access</dt><dd>{access}</dd>{/if}
    {#if video.age_limit}<dt>Age limit</dt><dd>{video.age_limit}+</dd>{/if}
    <dt>Type</dt>
    <dd>{typeWord}</dd>
    <dt>Published</dt>
    <dd>{hasTime(video.published_at) ? isoTime(video.published_at) : isoDate(video.published_at)}</dd>
    {#if archived}
      <dt>Quality</dt>
      <dd>
        {qualityWithRate(video)}
        <span class="muted">
          · {resolution(video.width, video.height)}{wide ? ' · 2.35:1' : ''}{video.dynamic_range && video.dynamic_range !== 'SDR' ? ` · ${video.dynamic_range}` : ''}
        </span>
      </dd>
      {#if codecs}<dt>Codecs</dt><dd>{codecs}</dd>{/if}
      {#if audio.length}<dt>Audio</dt><dd>{audio.join(', ')}</dd>{/if}
      <dt>Size</dt>
      <dd>{bytes(video.media_size)}</dd>
    {/if}
    <dt>Added</dt>
    <dd>{isoTime(video.created_at)}</dd>
    {#if video.deleted_at}<dt>Removed</dt><dd>{isoTime(video.deleted_at)}</dd>{/if}
    <dt>Watched</dt>
    <dd>{#if video.watched_at}{isoTime(video.watched_at)}{:else}<span class="muted">Not yet</span>{/if}</dd>
    <dt>YouTube ID</dt>
    <dd>
      <span class="mono">{video.youtube_id}</span>
      <button type="button" class="copy" aria-label="Copy ID" onclick={copyId}><Icon name="copy" /></button>
    </dd>
    {#if subscription}
      <dt>Source</dt>
      <dd>
        <a class="lnk" href={href(`/subscriptions/${subscription.id}`)}>{subscription.title}</a>
        <span class="muted">· {policyLabel(subscription)}</span>
      </dd>
    {/if}
    {#if category}<dt>Category</dt><dd>{category}</dd>{/if}
    {#if tags.length}
      <dt>Tags</dt>
      <dd>
        <ul class="chips plain">
          {#each allTags ? tags : tags.slice(0, TAGS_SHOWN) as tag (tag)}<li><span>{tag}</span></li>{/each}
        </ul>
        {#if tags.length > TAGS_SHOWN}
          <button type="button" class="more-btn" aria-expanded={allTags} onclick={() => (allTags = !allTags)}>
            {allTags ? 'Show fewer tags' : `Show all ${tags.length} tags`}
          </button>
        {/if}
      </dd>
    {/if}
  </dl>
</section>
