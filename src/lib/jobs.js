/** @import { Entry, Job, JobState, PauseCause, Reason, SkipReason } from './types' */
import { bytes, int, parseTime, POLICIES } from './format.js'

/** What each way of pausing YouTube work is called. @type {Record<PauseCause, string>} */
export const PAUSE_TITLES = {
  asked: 'YouTube work is paused',
  refused: 'YouTube refused a request',
  extras: 'YouTube refused a subtitle or live chat',
  failures: 'Downloads keep failing'
}

/** What a paused job's reason says. @type {Partial<Record<Reason, string>>} */
const PAUSED = {
  asked: 'You paused it',
  subscription_off: 'Its subscription is off'
}

/**
 * What a failed job's reason adds to its error; `declined` and `error` add nothing.
 * @type {Partial<Record<Reason, string>>}
 */
const FAILED = {
  gone: 'Gone from YouTube · not retried',
  needs_account: 'Needs a signed-in account'
}

/** What can fix a job, by the reason it is stuck on. @type {Partial<Record<Reason, string>>} */
const HINTS = {
  refused: 'If bot checks keep coming back, load browser cookies with YTDLP_COOKIE_FILE.',
  needs_account: 'Needs cookies from an account that can see it.'
}

/** Why the download policy leaves an inventory entry alone. @type {Partial<Record<SkipReason, string>>} */
const SKIPPED = {
  policy_none: `Download policy is ${POLICIES.none.label}`,
  subscription_off: 'Subscription is off',
  removed: 'Removed from the source',
  tab_off: "Its tab isn't selected",
  before_subscribing: 'From before you subscribed'
}

/** Why an entry isn't ready yet; an upcoming one has its own status word. @type {Record<string, string>} */
const NOT_READY = {
  is_live: 'Live now; it can be archived once it ends',
  post_live: 'Just ended; YouTube is still processing it'
}

/** @param {number} n */
const times = (n) => (n === 1 ? 'once' : n === 2 ? 'twice' : `${n} times`)

/**
 * How many times YouTube has refused a job.
 * @param {number} refusals
 */
export const refusalCount = (refusals) => `YouTube has refused it ${times(refusals)}`

/**
 * Why a waiting job hasn't started. Never empty.
 * @param {Pick<JobState, 'waiting_on' | 'attempts' | 'max_attempts' | 'error'> & { refusals?: number }} job
 */
export function waitingWhy(job) {
  switch (job.waiting_on) {
    case 'youtube':
      return job.refusals
        ? `Held by the pause on YouTube work · ${refusalCount(job.refusals)}`
        : 'Held by the pause on YouTube work'
    case 'retry':
      return `Attempt ${job.attempts + 1} of ${job.max_attempts}${job.error ? ` after ${refusalWords(job.error)}` : ''}`
    case 'premiere':
      return 'Premiere'
    default:
      return 'Waiting'
  }
}

/**
 * Why a paused job is paused. Never empty.
 * @param {Pick<JobState, 'reason'>} job
 */
export function pausedWhy(job) {
  return (job.reason && PAUSED[job.reason]) || 'Paused before YouHoard recorded why'
}

/**
 * What a failed job's reason says beyond its error; empty when the error says it all.
 * @param {Pick<Job, 'reason'>} job
 */
export const failedNote = (job) => (job.reason && FAILED[job.reason]) || ''

/**
 * Whether trying a failed job again can help: a video that is gone from YouTube stays gone.
 * @param {Pick<Job, 'reason'>} job
 */
export const canRetry = (job) => job.reason !== 'gone'

/**
 * What might fix a job stuck on `reason`, or nothing.
 * @param {Reason | null | undefined} reason
 */
export const hintFor = (reason) => (reason && HINTS[reason]) || ''

/**
 * Why the subscription's policy leaves a not-selected entry out, or when it queues if it doesn't.
 * Empty when the entry's status already says it.
 * @param {Pick<Entry, 'skip_reason' | 'live_status'>} entry
 */
export function skipWhy(entry) {
  if (entry.skip_reason === 'not_ready') return NOT_READY[entry.live_status ?? ''] ?? ''
  return entry.skip_reason ? (SKIPPED[entry.skip_reason] ?? '') : 'Selected; it queues at the next check'
}

/**
 * What YouTube said, without yt-dlp's prefix and advice.
 * @param {string} reason
 */
export const refusalWords = (reason) => reason.replace(/^\[\w+\] [\w-]+: /, '').split(/(?<=\.) /)[0]

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
