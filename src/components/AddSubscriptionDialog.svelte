<script>
  /** @import { ResolvedSource, Subscription } from '../lib/types' */
  import { api, errorMessage } from '../lib/api.js'
  import { queue } from '../lib/queue.svelte.js'
  import { librarySettings } from '../lib/settings.svelte.js'
  import { notify } from '../lib/toasts.svelte.js'
  import Modal from './Modal.svelte'
  import SubscriptionForm, {
    newSubscriptionForm,
    subscriptionFormProblem,
    subscriptionPayload
  } from './SubscriptionForm.svelte'

  /** @type {{ onclose: () => void, oncreated: (sub: Subscription) => void }} */
  let { onclose, oncreated } = $props()

  const uid = $props.id()
  /** @type {{ close: () => void } | undefined} */
  let modal = $state()
  let url = $state('')
  let resolved = $state(/** @type {ResolvedSource | null} */ (null))
  let form = $state(newSubscriptionForm(null))
  let resolving = $state(false)
  let creating = $state(false)
  let error = $state('')

  const problem = $derived(resolved ? subscriptionFormProblem(form, resolved.kind) : '')
  const owner = $derived(resolved ? (resolved.owner_name ?? resolved.channel_name) : null)

  /** @param {SubmitEvent} event */
  async function resolve(event) {
    event.preventDefault()
    resolving = true
    error = ''
    resolved = null
    try {
      resolved = await api.subscriptions.resolve(url.trim())
      form = newSubscriptionForm(librarySettings.current)
    } catch (e) {
      error = errorMessage(e)
    } finally {
      resolving = false
    }
  }

  /** @param {SubmitEvent} event */
  async function create(event) {
    event.preventDefault()
    if (!resolved || problem) return
    creating = true
    error = ''
    try {
      const sub = await api.subscriptions.create(resolved.url, subscriptionPayload(form, resolved.kind))
      notify.success(sub.enabled ? `Subscribed to “${sub.title}”. First check queued.` : `Subscribed to “${sub.title}”.`)
      queue.refresh().catch(() => {})
      oncreated(sub)
      modal?.close()
    } catch (e) {
      error = errorMessage(e)
    } finally {
      creating = false
    }
  }
</script>

<Modal title="Add subscription" bind:this={modal} {onclose}>
  <div class="stack">
    <form class="resolve" onsubmit={resolve}>
      <div class="field grow">
        <label class="field-label" for="{uid}-url">Channel or playlist URL</label>
        <input
          id="{uid}-url"
          bind:value={url}
          oninput={() => {
            resolved = null
            error = ''
          }}
          required
          inputmode="url"
          autocomplete="off"
          spellcheck="false"
          placeholder="https://www.youtube.com/@channel"
          data-autofocus
        />
      </div>
      <button type="submit" class="btn btn-secondary" disabled={resolving || !url.trim()}>
        {resolving ? 'Resolving…' : 'Resolve'}
      </button>
    </form>

    {#if error}<p class="form-error" role="alert">{error}</p>{/if}

    {#if resolved}
      <div class="resolved">
        <div class="cluster">
          <span class="badge badge-info">{resolved.kind}</span>
          <a class="resolved-title" href={resolved.url} target="_blank" rel="noopener noreferrer">{resolved.title}</a>
        </div>
        {#if owner && owner !== resolved.title}<p class="muted small">by {owner}</p>{/if}
      </div>

      {#if resolved.existing_subscription_id}
        <p>
          You're already subscribed to this {resolved.kind}.
          <a href="#/subscriptions/{resolved.existing_subscription_id}" onclick={() => modal?.close()}>
            Open the existing subscription
          </a>
        </p>
      {:else}
        <form class="stack" onsubmit={create}>
          <SubscriptionForm kind={resolved.kind} bind:value={form} />
          {#if problem}<p class="hint warn-text">{problem}</p>{/if}
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" onclick={() => modal?.close()}>Cancel</button>
            <button type="submit" class="btn btn-primary" disabled={creating || !!problem}>
              {creating ? 'Creating…' : 'Create subscription'}
            </button>
          </div>
        </form>
      {/if}
    {/if}
  </div>
</Modal>

<style>
  .resolve {
    display: flex;
    align-items: flex-end;
    gap: var(--space-2);
  }

  .resolved {
    padding: var(--space-3);
    background: var(--background);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }

  .resolved-title {
    font-weight: 600;
    overflow-wrap: anywhere;
  }
</style>
