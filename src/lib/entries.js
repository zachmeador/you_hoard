/** @import { Entry, Page } from './types' */
import { api } from './api.js'

export const ENTRIES_PER_PAGE = 50
const TAIL_PAGE = 200

/**
 * An entry the source dropped before anything was saved: nothing to open, nothing to retry.
 * @param {Entry} entry
 */
export const lostEntry = (entry) =>
  !!entry.removed_at && entry.status !== 'archived' && entry.status !== 'deleted'

/**
 * One page of a subscription's inventory. Two tabs need more than a single request: "queued"
 * also covers downloads in progress, and "removed" has no filter in the API, but removed entries
 * sort last, so the walk starts at the end of the list.
 * @param {number} id
 * @param {{ status: string, type: string, q: string, page: number }} f
 * @returns {Promise<Page<Entry>>}
 */
export async function loadEntries(id, f) {
  const base = { video_type: f.type, q: f.q }
  const per_page = ENTRIES_PER_PAGE

  if (f.status === 'queued') {
    const [queued, running] = await Promise.all([
      api.subscriptions.entries(id, { ...base, status: 'queued', page: f.page, per_page }),
      api.subscriptions.entries(id, { ...base, status: 'downloading', per_page })
    ])
    return {
      ...queued,
      items: [...(f.page === 1 ? running.items : []), ...queued.items],
      total: queued.total + running.total
    }
  }

  if (f.status === 'removed') {
    const head = await api.subscriptions.entries(id, { ...base, per_page: 1 })
    /** @type {Entry[]} */
    const removed = []
    for (let page = Math.ceil(head.total / TAIL_PAGE); page >= 1; page--) {
      const res = await api.subscriptions.entries(id, { ...base, page, per_page: TAIL_PAGE })
      const tail = res.items.filter((e) => e.removed_at)
      removed.unshift(...tail)
      if (tail.length < res.items.length) break
    }
    const start = (f.page - 1) * per_page
    return { items: removed.slice(start, start + per_page), total: removed.length, page: f.page, per_page }
  }

  return api.subscriptions.entries(id, { ...base, status: f.status, page: f.page, per_page })
}
