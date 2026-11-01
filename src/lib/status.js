/** @import { Job, JobState, VideoStatus } from './types' */
import { pausedWhy, waitingWhy } from './jobs.js'

/**
 * @typedef {VideoStatus | 'waiting' | 'paused'} StateKey
 * @typedef {{
 *   key: StateKey,
 *   processing: boolean,
 *   percent: number | null,
 *   waitsUntil: string | null,
 *   premiere: boolean,
 *   why: string
 * }} VideoState
 */

/**
 * What a video is doing right now. The API folds paused and waiting jobs into "queued";
 * the video's download job tells them apart.
 * @param {{ status: VideoStatus, job?: JobState | null }} video
 * @param {Job | undefined} live the running download for this video, with its progress
 * @returns {VideoState}
 */
export function videoState(video, live) {
  const job = video.job
  /** @type {VideoState} */
  const state = {
    key: video.status,
    processing: false,
    percent: null,
    waitsUntil: null,
    premiere: false,
    why: ''
  }
  if (video.status === 'downloading') {
    state.processing = live?.progress?.phase === 'processing'
    state.percent = live?.progress?.percent ?? null
  } else if (video.status === 'queued' && job) {
    if (job.state === 'paused') {
      state.key = 'paused'
      state.why = pausedWhy(job)
    } else if (job.state === 'waiting') {
      state.key = 'waiting'
      state.waitsUntil = job.waits_until
      state.premiere = job.waiting_on === 'premiere'
      // a premiere's time says it all
      state.why = state.premiere ? '' : waitingWhy(job)
    }
  }
  return state
}
