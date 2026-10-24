<script>
  /** @import { Subscription } from '../lib/types' */
  import { api } from '../lib/api.js'
  import { confirmAction } from '../lib/confirm.svelte.js'
  import { queue } from '../lib/queue.svelte.js'
  import { notify } from '../lib/toasts.svelte.js'
  import EditSubscriptionDialog from './EditSubscriptionDialog.svelte'

  /** @type {{ sub: Subscription, onupdate: (sub: Subscription) => void, ondeleted: () => void }} */
  let { sub, onupdate, ondeleted } = $props()

  let busy = $state('')
  let editing = $state(false)

  /** @param {Event & { currentTarget: HTMLInputElement }} event */
  async function toggle(event) {
    const input = event.currentTarget
    const enabled = input.checked
    busy = 'toggle'
    try {
      const updated = await api.subscriptions.update(sub.id, { enabled })
      onupdate(updated)
      notify.success(enabled ? `Enabled “${updated.title}”` : `Paused “${updated.title}”`)
    } catch (e) {
      input.checked = sub.enabled
      notify.error(e)
    } finally {
      busy = ''
    }
  }

  /** @param {boolean} full */
  async function check(full) {
    busy = full ? 'full' : 'check'
    try {
      await api.subscriptions.check(sub.id, full)
      onupdate({ ...sub, checking: true })
      notify.success(full ? `Full rescan queued for “${sub.title}”` : `Check queued for “${sub.title}”`)
      queue.refresh().catch(() => {})
    } catch (e) {
      notify.error(e)
    } finally {
      busy = ''
    }
  }

  async function remove() {
    const ok = await confirmAction({
      title: 'Delete subscription?',
      message: `Stop tracking “${sub.title}”? Videos already in your library are kept.`,
      confirmLabel: 'Delete subscription',
      danger: true
    })
    if (!ok) return
    busy = 'delete'
    try {
      await api.subscriptions.remove(sub.id)
      notify.success(`Deleted subscription “${sub.title}”`)
      ondeleted()
    } catch (e) {
      notify.error(e)
    } finally {
      busy = ''
    }
  }
</script>

<div class="sub-actions">
  <label class="check toggle">
    <input type="checkbox" checked={sub.enabled} disabled={busy === 'toggle'} onchange={toggle} />
    Enabled
  </label>
  <button
    type="button"
    class="btn btn-secondary btn-sm"
    disabled={sub.checking || !!busy}
    title={sub.checking ? 'A check is already running' : undefined}
    onclick={() => check(false)}
  >
    Check now
  </button>
  <button
    type="button"
    class="btn btn-secondary btn-sm"
    disabled={sub.checking || !!busy}
    title="Re-list everything the source has, not just the newest uploads"
    onclick={() => check(true)}
  >
    Full rescan
  </button>
  <button type="button" class="btn btn-ghost btn-sm" disabled={!!busy} onclick={() => (editing = true)}>Edit</button>
  <button type="button" class="btn btn-danger btn-sm" disabled={!!busy} onclick={remove}>Delete</button>
</div>

{#if editing}
  <EditSubscriptionDialog {sub} onclose={() => (editing = false)} onsaved={onupdate} />
{/if}

<style>
  .sub-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }

  .toggle {
    margin-right: var(--space-2);
    font-size: 0.8125rem;
  }
</style>
