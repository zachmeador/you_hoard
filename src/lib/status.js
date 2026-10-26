/** @import { Job, JobState, VideoStatus } from './types' */
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
 * the video's download job tells them apart.
 * @param {{ status: VideoStatus, job?: JobState | null }} video
 * @param {Job | undefined} live the running download for this video, with its progress
 * @param {number} [now]
 * @returns {VideoState}
 */
export function videoState(video, live, now = Date.now()) {
  const job = video.job
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
    state.processing = live?.progress?.phase === 'processing'
    state.percent = live?.progress?.percent ?? null
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
