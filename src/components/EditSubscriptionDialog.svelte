<script>
  /** @import { Subscription } from '../lib/types' */
  import { untrack } from 'svelte'
  import { api, errorMessage } from '../lib/api.js'
  import { notify } from '../lib/toasts.svelte.js'
  import Modal from './Modal.svelte'
  import SubscriptionForm, {
    subscriptionForm,
    subscriptionFormProblem,
    subscriptionPayload
  } from './SubscriptionForm.svelte'

  /** @type {{ sub: Subscription, onclose: () => void, onsaved: (sub: Subscription) => void }} */
  let { sub, onclose, onsaved } = $props()

  /** @type {{ close: () => void } | undefined} */
  let modal = $state()
  let form = $state(untrack(() => subscriptionForm(sub)))
  let busy = $state(false)
  let error = $state('')

  const problem = $derived(subscriptionFormProblem(form, sub.kind))

  /** @param {SubmitEvent} event */
  async function save(event) {
    event.preventDefault()
    if (problem) return
    busy = true
    error = ''
    try {
      const updated = await api.subscriptions.update(sub.id, subscriptionPayload(form, sub.kind))
      onsaved(updated)
      notify.success('Subscription saved')
      modal?.close()
    } catch (e) {
      error = errorMessage(e)
    } finally {
      busy = false
    }
  }
</script>

<Modal title="Edit subscription" bind:this={modal} {onclose}>
  <form class="stack" onsubmit={save}>
    <p class="muted">{sub.title} <span class="badge">{sub.kind}</span></p>
    <SubscriptionForm kind={sub.kind} bind:value={form} />
    {#if problem}<p class="hint warn-text">{problem}</p>{/if}
    {#if error}<p class="form-error" role="alert">{error}</p>{/if}
    <div class="form-actions">
      <button type="button" class="btn btn-secondary" onclick={() => modal?.close()}>Cancel</button>
      <button type="submit" class="btn btn-primary" disabled={busy || !!problem}>
        {busy ? 'Saving…' : 'Save changes'}
      </button>
    </div>
  </form>
</Modal>
