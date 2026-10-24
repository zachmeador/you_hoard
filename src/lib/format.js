/** @import { DownloadPolicy, Job, JobKind, VideoType } from './types' */

const DASH = '—'

/**
 * Parses API dates: `YYYY-MM-DD` as a local calendar date, timestamps as UTC.
 * @param {string | null | undefined} value
 */
export function parseTime(value) {
  if (!value) return null
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (day) return new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3]))
  const iso = /(Z|[+-]\d\d:?\d\d)$/i.test(value) ? value : value.replace(' ', 'T') + 'Z'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : date
}

/** @param {string | null | undefined} value */
export function date(value) {
  const d = parseTime(value)
  return d ? d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : DASH
}

/** @param {string | null | undefined} value */
export function dateTime(value) {
  const d = parseTime(value)
  return d ? d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : DASH
}

/**
 * @param {string | null | undefined} value
 * @param {number} [now]
 */
export function relative(value, now = Date.now()) {
  const d = parseTime(value)
  if (!d) return DASH
  const diff = Math.round((d.getTime() - now) / 1000)
  const abs = Math.abs(diff)
  if (abs < 45) return diff <= 0 ? 'just now' : 'in a moment'
  let amount
  if (abs < 3600) amount = `${Math.max(1, Math.floor(abs / 60))}m`
  else if (abs < 86400) amount = `${Math.floor(abs / 3600)}h`
  else if (abs < 86400 * 30) amount = `${Math.floor(abs / 86400)}d`
  else return date(value)
  return diff < 0 ? `${amount} ago` : `in ${amount}`
}

/** @param {number | null | undefined} bytes */
export function bytes(bytes) {
  if (bytes == null) return DASH
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB', 'PB']
  let value = bytes / 1024
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i++
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[i]}`
}

/** @param {number | null | undefined} seconds */
export function duration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return ''
  const s = Math.max(0, Math.round(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = String(s % 60).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`
}

const compactFormat = new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 })
const integerFormat = new Intl.NumberFormat()

/** @param {number | null | undefined} n */
export function compact(n) {
  return n == null ? DASH : compactFormat.format(n)
}

/** @param {number | null | undefined} n */
export function int(n) {
  return n == null ? DASH : integerFormat.format(n)
}

/**
 * @param {number} n
 * @param {string} one
 * @param {string} [many]
 */
export function plural(n, one, many = `${one}s`) {
  return `${integerFormat.format(n)} ${n === 1 ? one : many}`
}

/** @param {number | null | undefined} bytesPerSecond */
export function speed(bytesPerSecond) {
  return bytesPerSecond == null ? '' : `${bytes(Math.round(bytesPerSecond))}/s`
}

/** @param {number | null | undefined} seconds */
export function eta(seconds) {
  return seconds == null ? '' : duration(seconds)
}

/** @param {number | null | undefined} percent */
export function percent(percent) {
  return percent == null ? '' : `${percent.toFixed(percent < 10 ? 1 : 0)}%`
}

/** @param {number} hours */
export function interval(hours) {
  if (hours === 1) return 'Every hour'
  if (hours === 24) return 'Daily'
  if (hours === 168) return 'Weekly'
  if (hours % 168 === 0) return `Every ${hours / 168} weeks`
  if (hours % 24 === 0) return `Every ${hours / 24} days`
  return `Every ${hours} hours`
}

/** @param {string | null | undefined} quality */
export function qualityLabel(quality) {
  if (!quality) return DASH
  if (quality === 'best') return 'Best available'
  if (quality === '2160p') return '2160p (4K)'
  return quality
}

/** @param {number | null | undefined} width @param {number | null | undefined} height */
export function resolution(width, height) {
  return width && height ? `${width}×${height}` : DASH
}

let languageNames = /** @type {Intl.DisplayNames | null} */ (null)
try {
  languageNames = new Intl.DisplayNames(undefined, { type: 'language' })
} catch {
  languageNames = null
}

/** @param {string} code */
export function languageName(code) {
  try {
    const name = languageNames?.of(code)
    return name && name !== code ? `${name} (${code})` : code
  } catch {
    return code
  }
}

/** @param {string[] | null | undefined} langs */
export function languages(langs) {
  if (!langs) return DASH
  return langs.length ? langs.join(', ') : 'None'
}

/** @param {string} text */
export function parseLanguages(text) {
  return [...new Set(text.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean))]
}

/** @type {Record<string, { label: string, tone: 'ok' | 'info' | 'warn' | 'danger' | 'muted' }>} */
export const STATUS = {
  archived: { label: 'Archived', tone: 'ok' },
  downloading: { label: 'Downloading', tone: 'info' },
  queued: { label: 'Queued', tone: 'warn' },
  failed: { label: 'Failed', tone: 'danger' },
  deleted: { label: 'Files removed', tone: 'muted' },
  missing: { label: 'Not downloaded', tone: 'muted' },
  not_selected: { label: 'Not selected', tone: 'muted' },
  running: { label: 'Running', tone: 'info' },
  paused: { label: 'Paused', tone: 'muted' },
  completed: { label: 'Completed', tone: 'ok' },
  cancelled: { label: 'Cancelled', tone: 'muted' }
}

/** @type {Record<DownloadPolicy, { label: string, help: string }>} */
export const POLICIES = {
  none: { label: 'None', help: 'Track only; download nothing automatically' },
  new: { label: 'New', help: 'Only uploads that appear from now on' },
  recent: { label: 'Recent', help: 'The latest N from each tab, plus new uploads' },
  all: { label: 'All', help: 'Everything the source lists (full backfill)' }
}

/** @type {Record<VideoType, string>} */
export const VIDEO_TYPES = {
  video: 'Video',
  short: 'Short',
  live: 'Live'
}

/** @type {Record<VideoType, string>} */
export const CONTENT_TYPES = {
  video: 'Videos',
  short: 'Shorts',
  live: 'Live'
}

/** @type {Record<JobKind, string>} */
export const JOB_KINDS = {
  download: 'Download',
  check: 'Check',
  scan: 'Scan'
}

/** @param {DownloadPolicy} policy @param {number} recentCount */
export function policySummary(policy, recentCount) {
  return policy === 'recent' ? `Recent ${recentCount}` : POLICIES[policy]?.label ?? policy
}

/** @param {{ listed: number, new_entries: number, queued: number, removed: number, full?: boolean }} r */
export function checkSummary(r) {
  const parts = [`${int(r.listed)} listed`, `${int(r.new_entries)} new`, `${int(r.queued)} queued`]
  if (r.removed) parts.push(`${int(r.removed)} removed`)
  return parts.join(' · ') + (r.full ? ' (full)' : '')
}

/** @param {Job} job */
export function jobResultSummary(job) {
  const r = job.result
  if (!r) return ''
  if (job.kind === 'check' && typeof r.listed === 'number') {
    return checkSummary(/** @type {any} */ (r))
  }
  return Object.entries(r)
    .filter(([, v]) => ['number', 'string', 'boolean'].includes(typeof v))
    .slice(0, 6)
    .map(([k, v]) => `${k.replaceAll('_', ' ')}: ${typeof v === 'number' ? int(v) : v}`)
    .join(' · ')
}

const URL_PATTERN = /(https?:\/\/[^\s<>"']*[^\s<>"'.,;:!?)\]])/g

/** @param {string} text */
export function linkify(text) {
  return text.split(URL_PATTERN).map((part, i) => ({ text: part, url: i % 2 === 1 }))
}
