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

/** @param {Record<string, string | number | boolean | null | undefined>} params */
export function qs(params) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
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
     * @param {string} url
     * @param {string} [quality]
     * @returns {Promise<T.Video>}
     */
    add: (url, quality) => request('POST', '/videos', { url, quality: quality || undefined }),
    /**
     * @param {number} id
     * @param {string} [quality]
     * @returns {Promise<{ job_id: number }>}
     */
    download: (id, quality) => request('POST', `/videos/${id}/download`, quality ? { quality } : {}),
    /**
     * @param {number} id
     * @returns {Promise<{ ok: boolean }>}
     */
    removeFiles: (id) => request('DELETE', `/videos/${id}`),
    /**
     * @param {number} id
     * @param {boolean} watched
     * @returns {Promise<T.Video>}
     */
    setWatched: (id, watched) => request('POST', `/videos/${id}/watched`, { watched })
  },

  channels: {
    /**
     * @param {{ q?: string, page?: number, per_page?: number }} query
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
    retryFailed: () => request('POST', '/jobs/retry-failed')
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
    /** @returns {Promise<{ job_id: number }>} */
    rescan: () => request('POST', '/library/rescan')
  }
}
