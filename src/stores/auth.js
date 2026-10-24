import { writable } from 'svelte/store'

const signedOut = { isAuthenticated: false, username: null, loading: false, setupRequired: false, error: '' }
export const authStore = writable({ ...signedOut, loading: true })

export const authApi = {
  async init() {
    try {
      const response = await fetch('/api/auth/status', { credentials: 'include' })
      if (!response.ok) throw new Error('Could not reach YouHoard')
      const status = await response.json()
      authStore.set({ ...signedOut, isAuthenticated: status.authenticated,
        username: status.username, setupRequired: status.setup_required })
    } catch (error) {
      authStore.set({ ...signedOut, error: 'Cannot reach the server. Check that the backend is running, then retry.' })
    }
  },

  async submit(path, username, password) {
    try {
      const response = await fetch(`/api/auth/${path}`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      })
      const data = await response.json()
      if (!response.ok) {
        const error = Array.isArray(data.detail) ? data.detail.map(item => item.msg).join('; ') : data.detail
        return { success: false, error: error || 'Sign-in failed' }
      }
      await this.init()
      return { success: true }
    } catch (error) {
      return { success: false, error: 'Cannot reach the server. Please try again.' }
    }
  },

  login(username, password) { return this.submit('login', username, password) },
  setup(username, password) { return this.submit('setup', username, password) },
  expire() { authStore.set(signedOut) },

  async logout() {
    try {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
    } finally {
      this.expire()
    }
  }
}
