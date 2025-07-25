import { writable } from 'svelte/store'

// Simple auth state - just what we need
export const authStore = writable({
  isAuthenticated: false,
  username: null,
  loading: true
})

export const authApi = {
  async init() {
    try {
      const response = await fetch('/api/auth/status', { credentials: 'include' })
      const status = await response.json()
      
      authStore.set({
        isAuthenticated: status.authenticated,
        username: status.username,
        loading: false
      })
    } catch (error) {
      authStore.set({ isAuthenticated: false, username: null, loading: false })
    }
  },

  async login(username, password) {
    try {
      const response = await fetch('/api/auth/login-form', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ username, password }),
        credentials: 'include'
      })

      if (response.ok) {
        await this.init() // Refresh auth state
        return { success: true }
      } else {
        const data = await response.json()
        return { success: false, error: data.detail || 'Login failed' }
      }
    } catch (error) {
      return { success: false, error: 'Network error' }
    }
  },

  async logout() {
    try {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
    } catch (error) {
      console.error('Logout failed:', error)
    }
    authStore.set({ isAuthenticated: false, username: null, loading: false })
  }
} 