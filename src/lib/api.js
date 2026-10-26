/** @import * as T from './types' */

export class ApiError extends Error {
  /**
   * @param {string} message
   * @param {number} status
   */
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** @type {() => void} */
let onUnauthorized = () => {}

/** @param {() => void} handler */
export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler
}

/** @param {unknown} error */
export function errorMessage(error) {
  return error instanceof Error ? error.message : String(error)
}

/** @param {any} data */
function detailMessage(data) {
  const detail = data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((d) => (typeof d === 'string' ? d : (d?.msg ?? JSON.stringify(d)))).join('; ')
  }
  return null
}

/**
 * @param {'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'} method
 * @param {string} path path below /api, e.g. "/videos?page=2"
 * @param {unknown} [body]
 * @returns {Promise<any>}
 */
export async function request(method, path, body) {
  /** @type {Record<string, string>} */
  const headers = { Accept: 'application/json' }
  /** @type {RequestInit} */
  const init = { method, headers, credentials: 'same-origin' }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }

  let res
  try {
    res = await fetch('/api' + path, init)
  } catch {
    throw new ApiError('Cannot reach the YouHoard server', 0)
  }

  const text = await res.text()
  let data = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = null
    }
  }

  if (!res.ok) {
    if (res.status === 401) onUnauthorized()
    throw new ApiError(detailMessage(data) ?? `${res.status} ${res.statusText}`.trim(), res.status)
  }
  return data
}

/**
 * A query string. Array values repeat the key (`status=a&status=b`); empty values are left out.
 * @param {Record<string, string | number | boolean | null | undefined | (string | number)[]>} params
 */
export function qs(params) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item !== undefined && item !== null && item !== '') search.append(key, String(item))
    }
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}

export const api = {
  auth: {
    /** @returns {Promise<T.AuthStatus>} */
    status: () => request('GET', '/auth/status'),
    /**
     * @param {string} username
     * @param {string} password
     * @returns {Promise<{ username: string }>}
     */
    setup: (username, password) => request('POST', '/auth/setup', { username, password }),
    /**
     * @param {string} username
     * @param {string} password
     * @returns {Promise<{ username: string, token: string }>}
     */
    login: (username, password) => request('POST', '/auth/login', { username, password }),
    /** @returns {Promise<{ ok: boolean }>} */
    logout: () => request('POST', '/auth/logout')
  },

  videos: {
    /**
     * @param {T.VideoQuery} query
     * @returns {Promise<T.Page<T.Video>>}
     */
    list: (query) => request('GET', '/videos' + qs({ ...query })),
    /**
     * @param {number} id
     * @returns {Promise<T.VideoDetail>}
     */
    get: (id) => request('GET', `/videos/${id}`),
    /**
     * @param {Omit<T.VideoQuery, 'status' | 'sort' | 'order' | 'page' | 'per_page' | 'unavailable'>} query
     * @returns {Promise<T.VideoCounts>}
     */
    counts: (query) => request('GET', '/videos/counts' + qs({ ...query })),
    /**
     * @param {string} url
     * @param {T.VideoOptions} [options]
     * @returns {Promise<T.Video>}
     */
    add: (url, options = {}) => request('POST', '/videos', { url, ...options }),
    /**
     * @param {number} id
     * @param {T.VideoOptions} [options]
     * @returns {Promise<{ job_id: number }>}
     */
    download: (id, options = {}) => request('POST', `/videos/${id}/download`, options),
    /**
     * @param {number} id
     * @param {{ sort?: 'top' | 'new', page?: number, per_page?: number }} query
     * @returns {Promise<T.CommentPage>}
     */
    comments: (id, query) => request('GET', `/videos/${id}/comments` + qs(query)),
    /**
     * The saved live chat replay, or just the stretch from `since` up to `until` seconds.
     * @param {number} id
     * @param {{ since?: number, until?: number }} [window]
     * @returns {Promise<{ items: T.ChatMessage[] }>}
     */
    chat: (id, window = {}) => request('GET', `/videos/${id}/chat` + qs(window)),
    /**
     * A preview of a video link, and whether the library has the video already.
     * @param {string} url
     * @returns {Promise<T.ResolvedVideo>}
     */
    resolve: (url) => request('POST', '/videos/resolve', { url }),
    /**
     * Into the trash, or deleted for good when the trash is off.
     * @param {number} id
     * @returns {Promise<{ ok: boolean, trash: { expires_at: string } | null }>}
     */
    removeFiles: (id) => request('DELETE', `/videos/${id}`),
    /**
     * Move a removed video's files back from the trash.
     * @param {number} id
     * @returns {Promise<{ ok: boolean }>}
     */
    restore: (id) => request('POST', `/videos/${id}/restore`),
    /**
     * @param {number} id
     * @param {boolean} watched
     * @returns {Promise<T.Video>}
     */
    setWatched: (id, watched) => request('POST', `/videos/${id}/watched`, { watched })
  },

  channels: {
    /**
     * @param {{ q?: string, sort?: 'name' | 'size' | 'videos', page?: number, per_page?: number }} query
     * @returns {Promise<T.Page<T.Channel>>}
     */
    list: (query) => request('GET', '/channels' + qs(query)),
    /**
     * @param {number} id
     * @returns {Promise<T.Channel>}
     */
    get: (id) => request('GET', `/channels/${id}`)
  },

  subscriptions: {
    /** @returns {Promise<{ items: T.Subscription[] }>} */
    list: () => request('GET', '/subscriptions'),
    /**
     * @param {string} url
     * @returns {Promise<T.ResolvedSource>}
     */
    resolve: (url) => request('POST', '/subscriptions/resolve', { url }),
    /**
     * @param {string} url
     * @param {T.SubscriptionOptions} options
     * @returns {Promise<T.Subscription>}
     */
    create: (url, options) => request('POST', '/subscriptions', { url, ...options }),
    /**
     * @param {number} id
     * @returns {Promise<T.Subscription>}
     */
    get: (id) => request('GET', `/subscriptions/${id}`),
    /**
     * @param {number} id
     * @param {T.SubscriptionOptions} changes
     * @returns {Promise<T.Subscription>}
     */
    update: (id, changes) => request('PATCH', `/subscriptions/${id}`, changes),
    /**
     * @param {number} id
     * @returns {Promise<{ ok: boolean }>}
     */
    remove: (id) => request('DELETE', `/subscriptions/${id}`),
    /**
     * @param {number} id
     * @param {boolean} full
     * @returns {Promise<{ job_id: number }>}
     */
    check: (id, full) => request('POST', `/subscriptions/${id}/check`, { full }),
    /**
     * @param {number} id
     * @param {T.EntryQuery} query
     * @returns {Promise<T.Page<T.Entry>>}
     */
    entries: (id, query) => request('GET', `/subscriptions/${id}/entries` + qs({ ...query })),
    /**
     * @param {number} id
     * @param {string} youtubeId
     * @returns {Promise<{ job_id: number, video_id: number }>}
     */
    downloadEntry: (id, youtubeId) =>
      request('POST', `/subscriptions/${id}/entries/${encodeURIComponent(youtubeId)}/download`)
  },

  jobs: {
    /**
     * @param {T.JobQuery} query
     * @returns {Promise<T.JobList>}
     */
    list: (query) => request('GET', '/jobs' + qs({ ...query })),
    /**
     * @param {number} id
     * @param {'cancel' | 'retry' | 'pause' | 'resume'} action
     * @returns {Promise<{ ok: boolean }>}
     */
    act: (id, action) => request('POST', `/jobs/${id}/${action}`),
    /**
     * @param {number} id
     * @returns {Promise<{ ok: boolean }>}
     */
    remove: (id) => request('DELETE', `/jobs/${id}`),
    /** @returns {Promise<{ cleared: number }>} */
    clearFinished: () => request('POST', '/jobs/clear'),
    /** @returns {Promise<{ retried: number }>} */
    retryFailed: () => request('POST', '/jobs/retry-failed'),
    /**
     * The ids of every job a query matches, without a page limit.
     * @param {Omit<T.JobQuery, 'limit' | 'offset'>} query
     * @returns {Promise<{ ids: number[] }>}
     */
    ids: (query) => request('GET', '/jobs/ids' + qs({ ...query })),
    /**
     * Pause the queued and waiting jobs among `ids`; others are left alone.
     * @param {number[]} ids
     * @returns {Promise<{ paused: number }>}
     */
    pauseMany: (ids) => request('POST', '/jobs/pause', { ids }),
    /**
     * Resume the paused jobs among `ids`, except downloads of videos already archived.
     * @param {number[]} ids
     * @returns {Promise<{ resumed: number }>}
     */
    resumeMany: (ids) => request('POST', '/jobs/resume', { ids }),
    /**
     * End a bot-check pause early.
     * @returns {Promise<{ ok: boolean }>}
     */
    resumeYoutube: () => request('POST', '/jobs/resume-youtube')
  },

  settings: {
    /** @returns {Promise<T.Settings>} */
    get: () => request('GET', '/settings'),
    /**
     * @param {T.SettingsUpdate} changes
     * @returns {Promise<T.Settings>}
     */
    update: (changes) => request('PUT', '/settings', changes)
  },

  system: {
    /** @returns {Promise<T.SystemInfo>} */
    get: () => request('GET', '/system'),
    /**
     * @param {boolean} [force] mark videos missing even when most of the library seems gone
     * @returns {Promise<{ job_id: number }>}
     */
    rescan: (force = false) => request('POST', '/library/rescan', force ? { force } : undefined)
  }
}
