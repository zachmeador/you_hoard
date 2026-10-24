<script>
  import { api, errorMessage } from '../lib/api.js'
  import { qualityLabel } from '../lib/format.js'
  import { queue } from '../lib/queue.svelte.js'
  import { librarySettings } from '../lib/settings.svelte.js'
  import { notify } from '../lib/toasts.svelte.js'
  import { videosChanged } from '../lib/ui.svelte.js'
  import Modal from './Modal.svelte'

  /** @type {{ onclose: () => void }} */
  let { onclose } = $props()

  const uid = $props.id()
  /** @type {{ close: () => void } | undefined} */
  let modal = $state()
  let url = $state('')
  let quality = $state('')
  let busy = $state(false)
  let error = $state('')

  const defaultQuality = $derived(librarySettings.current?.default_quality)

  /** @param {SubmitEvent} event */
  async function submit(event) {
    event.preventDefault()
    busy = true
    error = ''
    try {
      const video = await api.videos.add(url.trim(), quality || undefined)
      notify.success(`Added “${video.title}”. Download queued.`)
      videosChanged()
      queue.refresh().catch(() => {})
      modal?.close()
    } catch (e) {
      error = errorMessage(e)
    } finally {
      busy = false
    }
  }
</script>

<Modal title="Add video" size="sm" bind:this={modal} {onclose}>
  <form class="stack" onsubmit={submit}>
    <div class="field">
      <label class="field-label" for="{uid}-url">Video URL</label>
      <input
        id="{uid}-url"
        bind:value={url}
        required
        inputmode="url"
        autocomplete="off"
        spellcheck="false"
        placeholder="https://www.youtube.com/watch?v=…"
        data-autofocus
      />
    </div>
    <div class="field">
      <label class="field-label" for="{uid}-quality">Quality</label>
      <select id="{uid}-quality" bind:value={quality}>
        <option value="">Library default{defaultQuality ? ` (${qualityLabel(defaultQuality)})` : ''}</option>
        {#each librarySettings.options.qualities as q (q)}
          <option value={q}>{qualityLabel(q)}</option>
        {/each}
      </select>
    </div>
    {#if error}<p class="form-error" role="alert">{error}</p>{/if}
    <div class="form-actions">
      <button type="button" class="btn btn-secondary" onclick={() => modal?.close()}>Cancel</button>
      <button type="submit" class="btn btn-primary" disabled={busy || !url.trim()}>
        {busy ? 'Adding…' : 'Add to library'}
      </button>
    </div>
  </form>
</Modal>
