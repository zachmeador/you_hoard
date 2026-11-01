/** @import { Actor } from './types' */

/** What each event in the record says happened. @type {Record<string, string>} */
const WORDS = {
  'job.queued': 'Queued',
  'job.started': 'Started',
  'job.completed': 'Completed',
  'job.failed': 'Failed',
  'job.retrying': 'Failed, will try again',
  'job.refused': 'Refused by YouTube',
  'job.deferred': 'Waiting for it to go live',
  'job.returned': 'Returned to the queue',
  'job.paused': 'Paused',
  'job.resumed': 'Resumed',
  'job.cancelled': 'Cancelled',
  'job.retried': 'Retried',
  'job.run_now': 'Told to run now',
  'job.removed': 'Removed from the queue',
  'jobs.cleared': 'Cleared the finished jobs',
  'youtube.refused': 'YouTube refused a request',
  'youtube.extras_refused': 'YouTube refused a subtitle or live chat',
  'youtube.failures': 'Downloads kept failing',
  'youtube.paused': 'YouTube work paused',
  'youtube.resumed': 'YouTube work resumed',
  'subscription.off': 'Subscription turned off',
  'subscription.on': 'Subscription turned on',
  'trash.purged': 'Trash cleaned up',
  'scan.completed': 'Library rescan completed',
  'app.started': 'YouHoard started',
  'app.stopped': 'YouHoard stopped'
}

/** Events whose reason changes what they say. @type {Record<string, Record<string, string>>} */
const BECAUSE = {
  'job.paused': { subscription_off: 'Paused because its subscription is off' }
}

/** Who caused an event. @type {Record<Actor, string>} */
export const ACTORS = { owner: 'You', app: 'YouHoard', cli: 'Command line' }

/**
 * An event in plain words; an event this doesn't know is shown by its name.
 * @param {string} event
 * @param {string | null} [reason]
 */
export function eventWords(event, reason = null) {
  return (reason && BECAUSE[event]?.[reason]) || WORDS[event] || event
}
