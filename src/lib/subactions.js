/** @import { Subscription } from './types' */
import { api } from './api.js'
import { confirmAction } from './confirm.svelte.js'
import { queue } from './queue.svelte.js'
import { notify } from './toasts.svelte.js'
import { channelsChanged, subscriptionsChanged } from './ui.svelte.js'

/**
 * Pauses or resumes a subscription.
 * @param {Subscription} sub
 * @param {boolean} enabled
 * @returns {Promise<Subscription | null>}
 */
export async function setEnabled(sub, enabled) {
  try {
    const updated = await api.subscriptions.update(sub.id, { enabled })
    notify.success(enabled ? `Enabled “${sub.title}”` : `Paused “${sub.title}”`)
    subscriptionsChanged()
    return updated
  } catch (e) {
    notify.error(e)
    return null
  }
}

/**
 * Queues a check, or a full rescan that lists the whole source again.
 * @param {Subscription} sub
 * @param {boolean} full
 */
export async function checkNow(sub, full) {
  try {
    await api.subscriptions.check(sub.id, full)
    notify.success(full ? `Full rescan queued for ${sub.title}` : `Check queued for ${sub.title}`)
    queue.refresh().catch(() => {})
    subscriptionsChanged()
    return true
  } catch (e) {
    notify.error(e)
    return false
  }
}

/**
 * Asks, then deletes a subscription. Archived videos stay in the library.
 * @param {Subscription} sub
 */
export async function removeSubscription(sub) {
  const ok = await confirmAction({
    title: 'Delete subscription?',
    message: `“${sub.title}” stops being checked. Videos already archived stay in the library.`,
    confirmLabel: 'Delete subscription',
    danger: true
  })
  if (!ok) return false
  try {
    await api.subscriptions.remove(sub.id)
    notify.success(`Deleted “${sub.title}”`)
    subscriptionsChanged()
    channelsChanged()
    return true
  } catch (e) {
    notify.error(e)
    return false
  }
}
