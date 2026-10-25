import { qs } from './api.js'

/** @typedef {Record<string, string | number | null | undefined>} QueryParams */
/**
 * @typedef {{ name: 'library' | 'subscriptions' | 'queue' | 'system' | 'not-found' }
 *   | { name: 'video' | 'subscription', id: number }} Route
 */

/** @param {string} hash */
function parse(hash) {
  const raw = hash.replace(/^#/, '')
  const i = raw.indexOf('?')
  let path = (i === -1 ? raw : raw.slice(0, i)) || '/'
  if (!path.startsWith('/')) path = `/${path}`
  if (path.length > 1) path = path.replace(/\/+$/, '')
  /** @type {Record<string, string>} */
  const query = Object.fromEntries(new URLSearchParams(i === -1 ? '' : raw.slice(i + 1)))
  return { path, query }
}

class Router {
  path = $state('/')
  /** @type {Record<string, string>} */
  query = $state({})

  constructor() {
    this.sync()
    window.addEventListener('hashchange', () => this.sync())
  }

  sync() {
    const next = parse(location.hash)
    if (next.path !== this.path) window.scrollTo(0, 0)
    this.path = next.path
    this.query = next.query
  }
}

export const router = new Router()

/**
 * @param {string} path
 * @param {QueryParams} [query]
 */
export function href(path, query = {}) {
  return `#${path}${qs(query)}`
}

/**
 * @param {string} path
 * @param {QueryParams} [query]
 * @param {{ replace?: boolean }} [options]
 */
export function navigate(path, query = {}, { replace = false } = {}) {
  const target = href(path, query)
  if (replace) {
    history.replaceState(history.state, '', target)
    router.sync()
  } else {
    location.hash = target
  }
}

/**
 * Merges `patch` into the current hash query (empty values are dropped) without adding a
 * history entry. Changing anything other than `page` goes back to the first page.
 * @param {QueryParams} patch
 */
export function updateQuery(patch) {
  /** @type {QueryParams} */
  const next = { ...router.query, ...patch }
  if (!('page' in patch)) delete next.page
  navigate(router.path, next, { replace: true })
}

/** @param {string | undefined} value */
export function pageParam(value) {
  const n = Number(value)
  return Number.isInteger(n) && n > 1 ? n : 1
}

/**
 * @param {string} path
 * @returns {Route}
 */
export function matchRoute(path) {
  const video = /^\/video\/(\d+)$/.exec(path)
  if (video) return { name: 'video', id: Number(video[1]) }
  const sub = /^\/subscriptions\/(\d+)$/.exec(path)
  if (sub) return { name: 'subscription', id: Number(sub[1]) }
  switch (path) {
    case '/':
    case '/library':
      return { name: 'library' }
    case '/subscriptions':
      return { name: 'subscriptions' }
    case '/queue':
      return { name: 'queue' }
    case '/system':
      return { name: 'system' }
    default:
      return { name: 'not-found' }
  }
}

/** The nav section a route belongs to. @param {Route} route */
export function sectionOf(route) {
  if (route.name === 'video') return 'library'
  if (route.name === 'subscription') return 'subscriptions'
  return route.name
}
