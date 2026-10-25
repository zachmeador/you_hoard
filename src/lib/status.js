/** @import { Job, VideoStatus } from './types' */
import { isPremiere, isWaiting, waitNote } from './jobs.js'

/**
 * @typedef {VideoStatus | 'waiting' | 'paused'} StateKey
 * @typedef {{
 *   key: StateKey,
 *   processing: boolean,
 *   percent: number | null,
 *   runAfter: string | null,
 *   premiere: boolean,
 *   why: string
 * }} VideoState
 */

/**
 * What a video is doing right now. The API folds paused and waiting jobs into "queued";
 * the download job tells them apart.
 * @param {{ status: VideoStatus }} video
 * @param {Job | undefined} job the running, paused or waiting job for this video
 * @param {number} [now]
 * @returns {VideoState}
 */
export function videoState(video, job, now = Date.now()) {
  /** @type {VideoState} */
  const state = {
    key: video.status,
    processing: false,
    percent: null,
    runAfter: null,
    premiere: false,
    why: ''
  }
  if (video.status === 'downloading') {
    state.processing = job?.progress?.phase === 'processing'
    state.percent = job?.progress?.percent ?? null
  } else if (video.status === 'queued' && job) {
    if (job.status === 'paused') state.key = 'paused'
    else if (isWaiting(job, now)) {
      state.key = 'waiting'
      state.runAfter = job.run_after
      state.premiere = isPremiere(job)
      state.why = waitNote(job)
    }
  }
  return state
}
