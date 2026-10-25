import { matchRoute, navigate, router } from './router.svelte.js'

export const ui = $state({
  addOpen: false,
  addUrl: '',
  videosVersion: 0,
  subscriptionsVersion: 0,
  channelsVersion: 0
})

/** @param {string} [url] a URL to resolve right away */
export function openAdd(url = '') {
  ui.addUrl = url
  ui.addOpen = true
}

export function videosChanged() {
  ui.videosVersion++
}

export function subscriptionsChanged() {
  ui.subscriptionsVersion++
}

export function channelsChanged() {
  ui.channelsVersion++
}

/** Moves to the library and puts the cursor in its search field. */
export function focusSearch() {
  if (matchRoute(router.path).name !== 'library') navigate('/library')
  setTimeout(() => {
    const field = document.querySelector('input[type="search"][aria-label="Search the library"]')
    if (field instanceof HTMLInputElement) field.focus()
  }, 50)
}

export const clock = $state({ now: Date.now() })

setInterval(() => {
  clock.now = Date.now()
}, 15_000)
