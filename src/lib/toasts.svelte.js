import { ApiError, errorMessage } from './api.js'

/** @typedef {'success' | 'error' | 'info'} ToastKind */
/** @typedef {{ id: number, kind: ToastKind, message: string }} Toast */

/** @type {Toast[]} */
export const toasts = $state([])

let nextId = 1

/**
 * @param {ToastKind} kind
 * @param {string} message
 */
function push(kind, message) {
  const id = nextId++
  toasts.push({ id, kind, message })
  while (toasts.length > 4) toasts.shift()
  setTimeout(() => dismiss(id), kind === 'error' ? 8000 : 4000)
}

/** @param {number} id */
export function dismiss(id) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i !== -1) toasts.splice(i, 1)
}

export const notify = {
  /** @param {string} message */
  success: (message) => push('success', message),
  /** @param {string} message */
  info: (message) => push('info', message),
  /**
   * Shows an error toast, except for 401s (the app switches to the login screen instead).
   * @param {unknown} error
   */
  error: (error) => {
    if (error instanceof ApiError && error.status === 401) return
    push('error', errorMessage(error))
  }
}
