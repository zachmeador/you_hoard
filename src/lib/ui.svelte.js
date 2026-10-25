import { matchRoute, navigate, router } from './router.svelte.js'

export const ui = $state({
  addOpen: false,
  addSeq: 0,
  addUrl: '',
  videosVersion: 0,
  subscriptionsVersion: 0,
  channelsVersion: 0
})

/** @param {string} [url] a URL to resolve right away */
export function openAdd(url = '') {
  ui.addSeq++
  ui.addUrl = url
  ui.addOpen = true
}

/**
 * Closes the add dialog opened as `seq`. A dialog that is still closing when the next one opens
 * must not close it: its close event arrives late.
 * @param {number} seq
 */
export function closeAdd(seq) {
  if (seq === ui.addSeq) ui.addOpen = false
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
