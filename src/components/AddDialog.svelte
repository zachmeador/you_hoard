<script>
  /** @import { DownloadPolicy, ResolvedSource, VideoType } from '../lib/types' */
  import { onMount, untrack } from 'svelte'
  import { api, errorMessage } from '../lib/api.js'
  import { interval } from '../lib/format.js'
  import { emptyOverrides, subscriptionOverrides, videoOptions } from '../lib/overrides.js'
  import { href } from '../lib/router.svelte.js'
  import { librarySettings } from '../lib/settings.svelte.js'
  import { notify } from '../lib/toasts.svelte.js'
  import { channelsChanged, subscriptionsChanged, ui, videosChanged } from '../lib/ui.svelte.js'
  import { classifyInput } from '../lib/urls.js'
  import Avatar from './Avatar.svelte'
  import Dialog from './Dialog.svelte'
  import Icon from './Icon.svelte'
  import OverrideFields from './OverrideFields.svelte'
  import PolicyFields from './PolicyFields.svelte'
  import SelectField from './SelectField.svelte'
  import Thumb from './Thumb.svelte'

  /** @type {{ onclose: () => void }} */
  let { onclose } = $props()

  /** @type {{ close: () => void } | undefined} */
  let dialog = $state()
  let url = $state(untrack(() => ui.addUrl))
  /** @type {ResolvedSource | null} */
  let resolved = $state(null)
  let busy = $state('')
  let error = $state('')
  let showOptions = $state(false)
  let overrides = $state(emptyOverrides())
  /** @type {DownloadPolicy} */
  let policy = $state('new')
  let recentCount = $state(10)
  /** @type {VideoType[]} */
  let types = $state(['video', 'short'])
  let every = $state(untrack(() => librarySettings.current?.check_interval_hours ?? 24))

  const input = $derived(classifyInput(url))
  const mode = $derived(resolved ? 'source' : input?.kind === 'video' ? 'video' : 'idle')
  const videoId = $derived(
    input?.kind === 'video'
      ? (/(?:v=|youtu\.be\/|shorts\/|live\/|embed\/|\/v\/)([\w-]{11})/.exec(input.url)?.[1] ?? input.url)
      : ''
  )
  const intervals = $derived(librarySettings.options.check_intervals.map((h) => ({ value: h, label: interval(h) })))

  onMount(() => {
    if (url.trim()) resolve()
  })

  $effect(() => {
    void input?.kind
    untrack(() => {
      overrides = emptyOverrides()
      showOptions = false
    })
  })

  function edited() {
    resolved = null
    error = ''
    showOptions = false
  }

  /** @param {SubmitEvent} [event] */
  async function resolve(event) {
    event?.preventDefault()
    error = ''
    if (!url.trim()) return
    const parsed = classifyInput(url)
    if (!parsed) {
      error = 'Use a youtube.com or youtu.be link to a video, channel or playlist'
      return
    }
    if (parsed.kind === 'video') {
      document.getElementById('add-confirm')?.focus()
      return
    }
    busy = 'resolve'
    try {
      resolved = await api.subscriptions.resolve(parsed.url)
    } catch (e) {
      error = errorMessage(e)
    } finally {
      busy = ''
    }
  }

  async function addVideo() {
    if (input?.kind !== 'video') return
    busy = 'add'
    error = ''
    try {
      const video = await api.videos.add(input.url, videoOptions(overrides))
      videosChanged()
      channelsChanged()
      notify.success(`Added “${video.title}”. Download queued.`)
      dialog?.close()
    } catch (e) {
      error = errorMessage(e)
    } finally {
      busy = ''
    }
  }

  async function subscribe() {
    if (!resolved) return
    busy = 'subscribe'
    error = ''
    try {
      const channel = resolved.kind === 'channel'
      const sub = await api.subscriptions.create(resolved.url, {
        download_policy: policy,
        recent_count: Math.min(1000, Math.max(1, Math.round(Number(recentCount) || 1))),
        ...(channel ? { content_types: types } : {}),
        check_interval_hours: every,
        ...subscriptionOverrides(overrides)
      })
      subscriptionsChanged()
      channelsChanged()
      notify.success(`Subscribed to ${sub.title}. First check queued.`)
      dialog?.close()
    } catch (e) {
      error = errorMessage(e)
    } finally {
      busy = ''
    }
  }
</script>

{#snippet options()}
  <button
    type="button"
    class="disclose"
    aria-expanded={showOptions}
    aria-controls="add-options"
    onclick={() => (showOptions = !showOptions)}
  >
    <Icon name="chev" />Options
  </button>
  {#if showOptions}
    <div id="add-options" class="ovr"><OverrideFields bind:value={overrides} /></div>
  {/if}
{/snippet}

<Dialog title="Add from YouTube" bind:this={dialog} {onclose}>
  <form onsubmit={resolve}>
    <label class="label" for="add-url">YouTube URL</label>
    <div class="url-row">
      <input
        id="add-url"
        class="input"
        data-autofocus
        placeholder="Video, channel, @handle or playlist"
        autocomplete="off"
        spellcheck="false"
        bind:value={url}
        oninput={edited}
      />
      <button type="submit" class="btn" disabled={busy === 'resolve'}>Resolve</button>
    </div>
  </form>

  {#if error}<p class="form-error add-error" role="alert">{error}</p>{/if}

  {#if mode === 'video'}
    <div class="res">
      <div class="who">
        <div class="mini" style="width: 112px"><Thumb src={null} /></div>
        <div>
          <span class="label">Video</span>
          <div class="k mono">{videoId}</div>
        </div>
      </div>
      {@render options()}
      <div class="foot">
        <button type="button" class="btn quiet" onclick={() => dialog?.close()}>Cancel</button>
        <button id="add-confirm" type="button" class="btn primary" disabled={busy === 'add'} onclick={addVideo}>
          <Icon name="dl" />Add and download
        </button>
      </div>
    </div>
  {:else if mode === 'source' && resolved}
    <div class="res">
      <div class="who">
        <Avatar name={resolved.title} large playlist={resolved.kind === 'playlist'} />
        <div>
          <span class="label">{resolved.kind === 'playlist' ? 'Playlist' : 'Channel'}</span>
          <div class="ttl">{resolved.title}</div>
          <div class="k">
            {#if resolved.kind === 'playlist'}by {resolved.owner_name ?? 'unknown'}{:else}<span class="mono">{resolved.youtube_id}</span>{/if}
          </div>
        </div>
      </div>
      {#if resolved.existing_subscription_id}
        <div class="known">
          Already subscribed.
          <a class="lnk" href={href(`/subscriptions/${resolved.existing_subscription_id}`)} onclick={() => dialog?.close()}>
            Open subscription
          </a>
        </div>
        <div class="foot"><button type="button" class="btn quiet" onclick={() => dialog?.close()}>Close</button></div>
      {:else}
        <div class="policy">
          <PolicyFields kind={resolved.kind} bind:policy bind:recentCount bind:types />
        </div>
        <div class="row">
          <SelectField label="Check" name="Check interval" value={every} options={intervals} onchange={(v) => (every = Number(v))} />
        </div>
        {@render options()}
        <div class="foot">
          <button type="button" class="btn quiet" onclick={() => dialog?.close()}>Cancel</button>
          <button
            type="button"
            class="btn primary"
            disabled={busy === 'subscribe' || (resolved.kind === 'channel' && types.length === 0)}
            onclick={subscribe}
          >
            Subscribe
          </button>
        </div>
      {/if}
    </div>
  {/if}
</Dialog>
