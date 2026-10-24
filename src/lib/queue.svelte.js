/** @import { JobCounts } from './types' */
import { api } from './api.js'

class QueueCounts {
  /** @type {JobCounts} */
  counts = $state({ queued: 0, paused: 0, running: 0, failed: 0, completed: 0, cancelled: 0 })
  active = $derived(this.counts.queued + this.counts.running)

  async refresh() {
    const res = await api.jobs.list({ limit: 1 })
    this.counts = res.counts
  }
}

export const queue = new QueueCounts()
