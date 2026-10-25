/** @import { Job, JobCounts } from './types' */
import { api } from './api.js'
import { isWaiting } from './jobs.js'

const PAGE = 200
const MAX_PAGES = 5

/** @returns {JobCounts} */
const emptyCounts = () => ({
  queued: 0,
  waiting: 0,
  paused: 0,
  running: 0,
  failed: 0,
  completed: 0,
  cancelled: 0
})

class QueueState {
  counts = $state(emptyCounts())
  /** @type {Job[]} */
  running = $state([])
  /** Paused and waiting downloads: states a video does not carry itself. @type {Job[]} */
  held = $state([])

  /** Download jobs by video id: running, paused and waiting. */
  byVideo = $derived.by(() => {
    /** @type {Map<number, Job>} */
    const map = new Map()
    for (const job of [...this.running, ...this.held]) if (job.video) map.set(job.video.id, job)
    return map
  })

  /** Changes when a job starts, finishes or changes state, so pages know to reload. */
  signature = $derived(
    `${this.running.map((j) => j.id).join(',')}|${this.counts.queued}|${this.counts.waiting}|${this.counts.paused}|${this.counts.failed}`
  )

  /** @param {number} videoId */
  jobFor(videoId) {
    return this.byVideo.get(videoId)
  }

  async refresh() {
    const res = await api.jobs.list({ status: 'running', limit: 50 })
    const held = []
    if (res.counts.paused > 0) held.push(...(await api.jobs.list({ status: 'paused', limit: PAGE })).items)
    if (res.counts.waiting > 0) held.push(...(await this.#waiting(res.counts.waiting)))
    this.counts = { ...emptyCounts(), ...res.counts }
    this.running = res.items
    this.held = held.filter((j) => j.kind === 'download')
  }

  /** @param {number} wanted */
  async #waiting(wanted) {
    /** @type {Job[]} */
    const found = []
    for (let page = 0; page < MAX_PAGES && found.length < wanted; page++) {
      const res = await api.jobs.list({ status: 'queued', limit: PAGE, offset: page * PAGE })
      found.push(...res.items.filter((j) => isWaiting(j)))
      if ((page + 1) * PAGE >= res.total) break
    }
    return found
  }
}

export const queue = new QueueState()
