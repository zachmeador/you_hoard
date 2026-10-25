/** @import { DownloadPolicy, Job, JobKind, Language, Subscription, VideoType } from './types' */

const DASH = '—'
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const MONTH = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December'
]
const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

/** @param {number} n */
const pad = (n) => String(n).padStart(2, '0')

/**
 * Parses API dates: `YYYY-MM-DD` as a local calendar date, timestamps as UTC.
 * @param {string | number | Date | null | undefined} value
 */
export function parseTime(value) {
  if (value == null || value === '') return null
  if (value instanceof Date) return value
  if (typeof value === 'number') return new Date(value)
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (day) return new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3]))
  const stamp = /(Z|[+-]\d\d:?\d\d)$/i.test(value) ? value : value.replace(' ', 'T') + 'Z'
  const date = new Date(stamp)
  return Number.isNaN(date.getTime()) ? null : date
}

/** True when the value carries a time of day, not just a date. @param {string | null | undefined} value */
export const hasTime = (value) => !!value && value.length > 10

/** @param {string | null | undefined} value */
export function dmy(value) {
  const d = parseTime(value)
  return d ? `${d.getDate()} ${MON[d.getMonth()]} ${d.getFullYear()}` : DASH
}

/**
 * @param {string | null | undefined} value
 * @param {number} [now]
 */
export function dshort(value, now = Date.now()) {
  const d = parseTime(value)
  if (!d) return DASH
  return d.getFullYear() === new Date(now).getFullYear() ? `${d.getDate()} ${MON[d.getMonth()]}` : dmy(value)
}

/** @param {string | null | undefined} value */
export function isoDate(value) {
  const d = parseTime(value)
  return d ? `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` : DASH
}

/** @param {string | null | undefined} value */
export function hm(value) {
  const d = parseTime(value)
  return d ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : DASH
}

/** @param {string | null | undefined} value */
export function isoTime(value) {
  const d = parseTime(value)
  return d ? `${isoDate(value)} ${hm(value)}` : DASH
}

/**
 * A short time for something happening soon: "18:40", "Tue 18:40" or "31 Oct, 17:00".
 * @param {string | null | undefined} value
 * @param {number} [now]
 */
export function whenShort(value, now = Date.now()) {
  const d = parseTime(value)
  if (!d) return DASH
  const n = new Date(now)
  if (d.toDateString() === n.toDateString()) return hm(value)
  if (Math.abs(d.getTime() - now) / 86400000 < 6) return `${DOW[d.getDay()]} ${hm(value)}`
  return `${d.getDate()} ${MON[d.getMonth()]}, ${hm(value)}`
}

/**
 * @param {string | null | undefined} value
 * @param {number} [now]
 */
export function rel(value, now = Date.now()) {
  const d = parseTime(value)
  if (!d) return DASH
  let s = Math.round((d.getTime() - now) / 1000)
  const future = s > 0
  s = Math.abs(s)
  let out
  if (s < 45) return future ? 'in a moment' : 'just now'
  if (s < 3600) out = `${Math.max(1, Math.round(s / 60))}m`
  else if (s < 86400) {
    const h = Math.floor(s / 3600)
    const m = Math.round((s % 3600) / 60)
    out = h < 10 && m && m < 60 ? `${h}h ${m}m` : `${h}h`
  } else if (s < 86400 * 45) out = `${Math.floor(s / 86400)}d`
  else return dmy(value)
  return future ? `in ${out}` : `${out} ago`
}

/**
 * "3 weeks ago": as precise as a timestamp that YouTube itself only gave as "3 weeks ago".
 * @param {number | null | undefined} unix seconds
 * @param {number} [now]
 */
export function coarseAgo(unix, now = Date.now()) {
  if (unix == null) return ''
  const days = Math.floor((now - unix * 1000) / 86400000)
  /** @param {number} n @param {string} unit */
  const plural = (n, unit) => `${n} ${unit}${n === 1 ? '' : 's'} ago`
  if (days < 1) return 'today'
  if (days < 7) return plural(days, 'day')
  if (days < 30) return plural(Math.floor(days / 7), 'week')
  if (days < 365) return plural(Math.floor(days / 30), 'month')
  return plural(Math.floor(days / 365), 'year')
}

/** @param {number | null | undefined} n */
export function bytes(n) {
  if (n == null) return DASH
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  let i = 0
  let b = n
  while (b >= 1000 && i < units.length - 1) {
    b /= 1000
    i++
  }
  return `${i ? +b.toPrecision(3) : Math.round(b)} ${units[i]}`
}

/** @param {number | null | undefined} seconds */
export function dur(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return ''
  const s = Math.max(0, Math.round(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const x = pad(s % 60)
  return h ? `${h}:${pad(m)}:${x}` : `${m}:${x}`
}

const integerFormat = new Intl.NumberFormat('en-US')
const compactFormat = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })

/** @param {number | null | undefined} n */
export const int = (n) => (n == null ? DASH : integerFormat.format(n))

/** @param {number | null | undefined} n */
export const compact = (n) => (n == null ? DASH : compactFormat.format(n))

/** @param {number | null | undefined} value 0-100 */
export const percent = (value) => (value == null ? '' : `${value.toFixed(value < 10 ? 1 : 0)}%`)

/** @param {number | null | undefined} bytesPerSecond */
export const speed = (bytesPerSecond) => (bytesPerSecond == null ? DASH : `${bytes(bytesPerSecond)}/s`)

/** @param {number | null | undefined} seconds */
export const eta = (seconds) => (seconds == null ? DASH : dur(seconds))

/** @type {Record<number, string>} */
const INTERVALS = {
  1: 'Every hour',
  3: 'Every 3 hours',
  6: 'Every 6 hours',
  12: 'Every 12 hours',
  24: 'Daily',
  72: 'Every 3 days',
  168: 'Weekly'
}

/** @param {number} hours */
export function interval(hours) {
  if (INTERVALS[hours]) return INTERVALS[hours]
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
export const resolution = (width, height) => (width && height ? `${width}×${height}` : DASH)

/** @param {string} name */
export function initials(name) {
  return (
    name
      .replace(/[^\p{L}\p{N} ]/gu, '')
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0])
      .join('')
      .toUpperCase() || '?'
  )
}

/** @type {Intl.DisplayNames | null} */
let languageNames = null
try {
  languageNames = new Intl.DisplayNames(['en'], { type: 'language' })
} catch {
  languageNames = null
}

/** The subtitle pattern that fetches every uploaded track. */
export const ALL_UPLOADED = { code: 'all', name: 'All uploaded' }

/**
 * @param {string} code
 * @param {Language[]} [known] curated names from the server take precedence
 */
export function languageName(code, known = []) {
  const curated = known.find((l) => l.code === code)
  if (curated) return curated.name
  if (code === ALL_UPLOADED.code) return ALL_UPLOADED.name
  try {
    return languageNames?.of(code) ?? code
  } catch {
    return code
  }
}

/**
 * A language code short enough for a button, or nothing when the code is not a plain one
 * (uploader-named caption tracks have opaque codes like "en-eEY6OEpapPo").
 * @param {string} code
 */
export const shortLang = (code) => (/^[a-z]{2,3}(-[A-Za-z0-9]{2,4})?$/.test(code) ? code : '')

/** @type {Record<string, string>} */
const VCODECS = { avc1: 'H.264', vp9: 'VP9', av01: 'AV1', hevc: 'HEVC' }
/** @type {Record<string, string>} */
const ACODECS = { mp4a: 'AAC', opus: 'Opus' }

/** @param {string | null | undefined} codec */
export const videoCodec = (codec) => (codec ? (VCODECS[codec] ?? codec) : '')
/** @param {string | null | undefined} codec */
export const audioCodec = (codec) => (codec ? (ACODECS[codec] ?? codec) : '')

/** "1080p60": the quality, with the frame rate when it is above 30. @param {{ quality: string | null, fps: number | null }} v */
export function qualityWithRate(v) {
  if (!v.quality) return DASH
  return v.fps && v.fps > 30 ? `${v.quality}${Math.round(v.fps)}` : v.quality
}

/** @type {Record<DownloadPolicy, { label: string, pips: number, help: string }>} */
export const POLICIES = {
  none: { label: 'Track only', pips: 0, help: 'Keep the inventory current; download nothing automatically.' },
  new: { label: 'New uploads', pips: 1, help: 'Archive entries that appear after the first check.' },
  recent: { label: 'Latest N', pips: 2, help: 'New uploads, plus the latest N per tab from the first check.' },
  all: { label: 'Everything', pips: 3, help: 'Archive everything the source lists: a full backfill.' }
}

/** @param {{ download_policy: DownloadPolicy, recent_count: number }} s */
export function policyLabel(s) {
  return s.download_policy === 'recent' ? `Latest ${s.recent_count}` : POLICIES[s.download_policy].label
}

/** @type {Record<VideoType, string>} */
export const CONTENT_TYPES = { video: 'Videos', short: 'Shorts', live: 'Live' }

/** @type {Record<VideoType, string>} */
export const KIND_WORDS = { video: 'Video', short: 'Short', live: 'Stream' }

/** @type {Record<JobKind, string>} */
export const JOB_KINDS = { download: 'Download', check: 'Check', scan: 'Scan' }

/** @type {Record<string, string>} */
export const SUBTITLE_SOURCES = {
  uploaded: 'uploaded',
  auto: 'auto-generated',
  translated: 'auto-translated',
  unknown: ''
}

/** @type {Record<string, string>} */
export const AVAILABILITY = {
  unlisted: 'Unlisted',
  private: 'Private',
  needs_auth: 'Needs sign-in',
  subscriber_only: 'Members only',
  premium_only: 'Premium only'
}

/**
 * How a subscription describes its source on one line.
 * @param {Subscription} s
 */
export function sourceMeta(s) {
  const bits = [s.kind === 'playlist' ? `Playlist · by ${s.owner_name ?? 'unknown'}` : 'Channel']
  if (s.kind === 'channel') bits.push(s.content_types.map((t) => CONTENT_TYPES[t]).join(', '))
  if (s.quality) bits.push(s.quality)
  bits.push(interval(s.check_interval_hours))
  return bits.join(' · ')
}

/**
 * The library grid's date group for a published date, relative to `now`.
 * @param {string | null | undefined} published
 * @param {number} [now]
 */
export function groupLabel(published, now = Date.now()) {
  const d = parseTime(published)
  if (!d) return 'Undated'
  const n = new Date(now)
  const y = d.getFullYear()
  const ny = n.getFullYear()
  const today = new Date(ny, n.getMonth(), n.getDate())
  const days = Math.round((today.getTime() - new Date(y, d.getMonth(), d.getDate()).getTime()) / 86400000)
  if (days < 7) return 'This week'
  if (y === ny && d.getMonth() === n.getMonth()) return `Earlier in ${MONTH[d.getMonth()]}`
  if (y === ny && d.getMonth() === n.getMonth() - 1) return `${MONTH[d.getMonth()]} ${y}`
  if (y === ny) return `Earlier in ${y}`
  if (y === ny - 1) return String(y)
  if (y >= 2020) return `2020–${ny - 2}`
  return y >= 2010 ? 'The 2010s' : 'The 2000s'
}

/**
 * @param {string} text
 * @returns {number | null} seconds, for "1:02:03" or "12:30"
 */
export function parseClock(text) {
  const parts = text.split(':').map(Number)
  if (parts.some((n) => !Number.isFinite(n))) return null
  return parts.reduce((a, n) => a * 60 + n, 0)
}

/** @typedef {{ kind: 'text' | 'url' | 'time', text: string, seconds?: number }} TextPart */

const TEXT_TOKENS = /(https?:\/\/[^\s<>"']*[^\s<>"'.,;:!?)\]])|((?<![\d:.])(?:\d{1,2}:)?\d{1,2}:\d{2}(?![\d:]))/g

/**
 * Splits plain text into links and clock times that can seek the player.
 * @param {string} text
 * @param {number | null} [limit] times beyond this many seconds stay plain text
 * @returns {TextPart[]}
 */
export function textParts(text, limit = null) {
  /** @type {TextPart[]} */
  const parts = []
  let last = 0
  for (const match of text.matchAll(TEXT_TOKENS)) {
    const at = match.index ?? 0
    const seconds = match[2] ? parseClock(match[2]) : null
    if (match[2] && (seconds == null || (limit != null && seconds > limit))) continue
    if (at > last) parts.push({ kind: 'text', text: text.slice(last, at) })
    parts.push(match[1] ? { kind: 'url', text: match[1] } : { kind: 'time', text: match[2], seconds: seconds ?? 0 })
    last = at + match[0].length
  }
  if (last < text.length) parts.push({ kind: 'text', text: text.slice(last) })
  return parts
}

/** @param {Job} job */
export function jobItemTitle(job) {
  if (job.video) return job.video.title
  if (job.subscription) return job.subscription.title
  return `Job #${job.id}`
}
