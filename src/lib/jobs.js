/** @import { Job, JobState } from './types' */
import { bytes, int, parseTime } from './format.js'

/** One try plus the three retries the job runner makes. */
export const MAX_ATTEMPTS = 4

/**
 * A queued job that is held back until its `run_after` time (a retry backoff or a premiere).
 * @param {JobState} job
 * @param {number} [now]
 */
export function isWaiting(job, now = Date.now()) {
  if (job.status !== 'queued' || !job.run_after) return false
  return (parseTime(job.run_after)?.getTime() ?? 0) > now
}

/** @param {JobState} job */
export const isRetry = (job) => job.attempts > 0 && !!job.error

/** @param {JobState} job */
export const isPremiere = (job) => !isRetry(job) && /premiere|upcoming/i.test(job.error ?? '')

const GONE = /private video|has been removed|been terminated|no longer available|removed for violating|copyright|does not exist|video unavailable/i

/** Errors the job runner treats as final: the video is gone from YouTube, so retrying is pointless. @param {string | null} error */
export const looksGone = (error) => GONE.test(error ?? '')

/** @param {string} text */
export function shortReason(text) {
  if (/bot/i.test(text)) return 'a bot check'
  if (/429/.test(text)) return 'HTTP 429 (rate limited)'
  return text
}

/**
 * Why a waiting job has not run yet; empty for premieres, whose time says it all.
 * @param {JobState} job
 */
export function waitNote(job) {
  if (isRetry(job)) return `Attempt ${job.attempts + 1} of ${MAX_ATTEMPTS}, after ${shortReason(job.error ?? '')}`
  return isPremiere(job) ? '' : (job.error ?? '')
}

/**
 * What a finished job produced, in a few words.
 * @param {Job} job
 */
export function jobResult(job) {
  if (job.status === 'cancelled') return 'Cancelled'
  const result = job.result ?? {}
  /** @param {string} key */
  const num = (key) => (typeof result[key] === 'number' ? result[key] : null)
  if (job.kind === 'check') {
    return `${int(num('listed'))} listed · ${int(num('new_entries'))} new · ${int(num('queued'))} queued`
  }
  if (job.kind === 'scan') {
    return `${int(num('files'))} files · ${int(num('added'))} added · ${int(num('missing'))} missing · ${int(num('relinked'))} moved`
  }
  if (typeof result.skipped === 'string') return result.skipped
  const height = num('height')
  const size = num('media_size')
  return [height ? `${height}p` : '', size != null ? bytes(size) : ''].filter(Boolean).join(' · ')
}

/** Seconds a finished job ran for. @param {Job} job */
export function jobTook(job) {
  const start = parseTime(job.started_at)
  const end = parseTime(job.finished_at)
  return start && end ? Math.max(0, Math.round((end.getTime() - start.getTime()) / 1000)) : null
}
