/** @import { Job, JobCounts, PauseCause } from './types' */
import { api } from './api.js'

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
  /** When YouTube work resumes, while it's paused. @type {string | null} */
  youtubePausedUntil = $state(null)
  /** What started the pause. @type {PauseCause | null} */
  youtubePauseCause = $state(null)
  /** The words behind the pause: what YouTube said, or why downloads stopped. @type {string | null} */
  youtubePauseReason = $state(null)
  /** When the next download may start, while downloads rest between one another. @type {string | null} */
  downloadRestUntil = $state(null)

  /** Running downloads by video id, for their progress. */
  byVideo = $derived.by(() => {
    /** @type {Map<number, Job>} */
    const map = new Map()
    for (const job of this.running) if (job.video) map.set(job.video.id, job)
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
    this.counts = { ...emptyCounts(), ...res.counts }
    this.youtubePausedUntil = res.youtube_paused_until ?? null
    this.youtubePauseCause = res.youtube_pause_cause ?? null
    this.youtubePauseReason = res.youtube_pause_reason ?? null
    this.downloadRestUntil = res.download_rest_until ?? null
    this.running = res.items
  }
}

export const queue = new QueueState()
