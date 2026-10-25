/** @import { Settings, Subscription, SubscriptionOptions, VideoOptions } from './types' */
import { qualityLabel } from './format.js'

/**
 * @typedef {'' | 'true' | 'false'} Tri an optional yes/no: empty means the library default
 * @typedef {'default' | 'none' | 'custom'} ListMode
 * @typedef {{
 *   quality: string,
 *   subtitles: ListMode,
 *   subtitleLanguages: string[],
 *   autoCaptions: Tri,
 *   comments: Tri,
 *   audio: ListMode,
 *   audioLanguages: string[],
 *   liveChat: Tri,
 *   sponsorblock: Tri
 * }} Overrides download options that replace the library defaults
 */

/** @returns {Overrides} */
export function emptyOverrides() {
  return {
    quality: '',
    subtitles: 'default',
    subtitleLanguages: [],
    autoCaptions: '',
    comments: '',
    audio: 'default',
    audioLanguages: [],
    liveChat: '',
    sponsorblock: ''
  }
}

/** @param {boolean | null | undefined} value @returns {Tri} */
const triOf = (value) => (value == null ? '' : value ? 'true' : 'false')

/** @param {Tri} value */
const boolOf = (value) => (value === '' ? null : value === 'true')

/** @param {string[] | null | undefined} list @returns {ListMode} */
const modeOf = (list) => (list == null ? 'default' : list.length ? 'custom' : 'none')

/** @param {ListMode} mode @param {string[]} list */
const listOf = (mode, list) => (mode === 'default' ? null : mode === 'none' ? [] : list)

/** @param {Subscription} sub @returns {Overrides} */
export function overridesOf(sub) {
  return {
    quality: sub.quality ?? '',
    subtitles: modeOf(sub.subtitle_languages),
    subtitleLanguages: [...(sub.subtitle_languages ?? [])],
    autoCaptions: triOf(sub.auto_captions),
    comments: triOf(sub.download_comments),
    audio: modeOf(sub.audio_languages),
    audioLanguages: [...(sub.audio_languages ?? [])],
    liveChat: triOf(sub.live_chat),
    sponsorblock: triOf(sub.sponsorblock)
  }
}

/**
 * Every override as the API takes it on a subscription; null puts the library default back.
 * @param {Overrides} o
 * @returns {Required<Pick<SubscriptionOptions, 'quality' | 'subtitle_languages' | 'download_comments' | 'audio_languages' | 'auto_captions' | 'live_chat' | 'sponsorblock'>>}
 */
export function subscriptionOverrides(o) {
  return {
    quality: o.quality || null,
    subtitle_languages: listOf(o.subtitles, o.subtitleLanguages),
    download_comments: boolOf(o.comments),
    audio_languages: listOf(o.audio, o.audioLanguages),
    auto_captions: boolOf(o.autoCaptions),
    live_chat: boolOf(o.liveChat),
    sponsorblock: boolOf(o.sponsorblock)
  }
}

/**
 * Only the options that differ from the defaults, for adding a single video.
 * @param {Overrides} o
 * @returns {VideoOptions}
 */
export function videoOptions(o) {
  const all = subscriptionOverrides(o)
  /** @type {VideoOptions} */
  const options = {}
  if (all.quality) options.quality = all.quality
  if (all.subtitle_languages) options.subtitle_languages = all.subtitle_languages
  if (all.auto_captions != null) options.auto_captions = all.auto_captions
  if (all.download_comments != null) options.download_comments = all.download_comments
  if (all.audio_languages) options.audio_languages = all.audio_languages
  if (all.live_chat != null) options.live_chat = all.live_chat
  if (all.sponsorblock != null) options.sponsorblock = all.sponsorblock
  return options
}

/**
 * The words for "use the library default", naming what that default is.
 * @param {Settings | null} settings
 */
export function defaultLabels(settings) {
  if (!settings) {
    const same = 'Library default'
    return { quality: same, subtitles: same, autoCaptions: same, comments: same, audio: same, liveChat: same, sponsorblock: same }
  }
  /** @param {boolean} on @param {string} yes @param {string} no */
  const pick = (on, yes, no) => `Library default (${on ? yes : no})`
  return {
    quality: `Library default (${settings.default_quality === 'best' ? 'best available' : settings.default_quality})`,
    subtitles: `Library default (${settings.subtitle_languages.join(', ') || 'none'})`,
    autoCaptions: pick(settings.auto_captions, 'on', 'off'),
    comments: pick(settings.download_comments, 'download', 'skip'),
    audio: `Library default (${settings.audio_languages.join(', ') || 'original only'})`,
    liveChat: pick(settings.live_chat, 'save', 'skip'),
    sponsorblock: pick(settings.sponsorblock, 'save', 'skip')
  }
}

/**
 * The qualities to pick from, led by "use the library default".
 * @param {Settings | null} settings
 * @param {string[]} qualities
 */
export const qualityChoices = (settings, qualities) => [
  { value: '', label: defaultLabels(settings).quality },
  ...qualities.map((q) => ({ value: q, label: qualityLabel(q) }))
]
