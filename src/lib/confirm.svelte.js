/** @typedef {{ title: string, message: string, confirmLabel: string, danger?: boolean }} ConfirmRequest */

/** @type {{ current: (ConfirmRequest & { resolve: (ok: boolean) => void }) | null }} */
export const confirmState = $state({ current: null })

/**
 * Opens the shared confirmation dialog and resolves with the user's answer.
 * @param {ConfirmRequest} request
 * @returns {Promise<boolean>}
 */
export function confirmAction(request) {
  confirmState.current?.resolve(false)
  return new Promise((resolve) => {
    confirmState.current = { ...request, resolve }
  })
}
