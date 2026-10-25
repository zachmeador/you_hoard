<script>
  /** @import { Comment } from '../lib/types' */
  import { onMount } from 'svelte'
  import { api, errorMessage } from '../lib/api.js'
  import { commentDate, compact, int, parseClock, textParts } from '../lib/format.js'
  import Icon from './Icon.svelte'
  import SelectField from './SelectField.svelte'

  const PER_PAGE = 20

  /**
   * @type {{
   *   videoId: number,
   *   saved: number,
   *   total: number | null,
   *   duration: number | null,
   *   onseek?: (t: number) => void
   * }}
   */
  let { videoId, saved, total, duration, onseek } = $props()

  /** @type {'top' | 'new'} */
  let sort = $state('top')
  /** @type {Comment[]} */
  let items = $state([])
  let count = $state(0)
  let page = $state(0)
  let loading = $state(false)
  let error = $state('')
  /** @type {Set<string>} */
  let open = $state(new Set())
  let generation = 0

  async function more() {
    const mine = generation
    loading = true
    error = ''
    try {
      const res = await api.videos.comments(videoId, { sort, page: page + 1, per_page: PER_PAGE })
      if (mine !== generation) return
      items = [...items, ...res.items]
      count = res.total
      page += 1
    } catch (e) {
      if (mine === generation) error = errorMessage(e)
    } finally {
      if (mine === generation) loading = false
    }
  }

  function reload() {
    generation++
    items = []
    page = 0
    count = 0
    more()
  }

  onMount(reload)

  /** @param {string} id */
  function toggle(id) {
    const next = new Set(open)
    if (!next.delete(id)) next.add(id)
    open = next
  }
</script>

{#snippet body(/** @type {Comment} */ comment)}
  <div class="cm-h">
    <b class="who">{comment.author}</b>
    {#if comment.author_is_uploader}<span class="kindtag">Uploader</span>{/if}
    {#if comment.author_is_verified}
      <span class="verified"><Icon name="verified" /><span class="sr">Verified</span></span>
    {/if}
    {#if comment.is_pinned}<span class="pin"><Icon name="pin" />Pinned</span>{/if}
    <span class="when">{commentDate(comment.timestamp)}</span>
  </div>
  <p class="cm-t">
    {#each textParts(comment.text, duration) as part, i (i)}
      {#if part.kind === 'url'}
        <a href={part.text} target="_blank" rel="noopener noreferrer">{part.text}</a>
      {:else if part.kind === 'time' && onseek}
        <button type="button" class="ts" onclick={() => onseek(part.seconds ?? parseClock(part.text) ?? 0)}>{part.text}</button>
      {:else}{part.text}{/if}
    {/each}
  </p>
  {#if comment.like_count || comment.is_favorited}
    <div class="cm-f">
      {#if comment.like_count}<span>{compact(comment.like_count)} likes</span>{/if}
      {#if comment.is_favorited}<span title="Liked by the creator"><Icon name="heart" /><span class="sr">Liked by the creator</span></span>{/if}
    </div>
  {/if}
{/snippet}

<section class="comments" aria-label="Comments">
  <div class="cm-bar">
    <SelectField
      label="Sort comments"
      name="Sort comments"
      value={sort}
      options={[
        { value: 'top', label: 'Top' },
        { value: 'new', label: 'Newest' }
      ]}
      onchange={(value) => {
        sort = value === 'new' ? 'new' : 'top'
        reload()
      }}
    />
    <span class="muted">
      {int(saved)} saved{total != null && total > saved ? ` of ${int(total)} at archive time` : ''}
    </span>
  </div>
  {#if error}<p class="form-error">{error}</p>{/if}
  <ul class="cmlist">
    {#each items as comment (comment.id)}
      <li>
        {@render body(comment)}
        {#if comment.replies?.length}
          <button type="button" class="more-btn" aria-expanded={open.has(comment.id)} onclick={() => toggle(comment.id)}>
            {open.has(comment.id) ? 'Hide' : 'Show'}
            {comment.replies.length === 1 ? '1 reply' : `${comment.replies.length} replies`}
          </button>
          {#if open.has(comment.id)}
            <ul class="replies">
              {#each comment.replies as reply (reply.id)}
                <li>{@render body(reply)}</li>
              {/each}
            </ul>
          {/if}
        {/if}
      </li>
    {/each}
  </ul>
  {#if items.length < count}
    <button type="button" class="btn sm" disabled={loading} onclick={more}>Load more comments</button>
  {:else if !loading && !items.length && !error}
    <p class="muted">No comments saved</p>
  {/if}
</section>
