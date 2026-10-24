import { ApiError, api, errorMessage, setUnauthorizedHandler } from './api.js'

class Auth {
  /** @type {'loading' | 'offline' | 'setup' | 'login' | 'ready'} */
  phase = $state('loading')
  /** @type {string | null} */
  username = $state(null)
  error = $state('')

  async check() {
    this.phase = 'loading'
    try {
      const status = await api.auth.status()
      this.username = status.username
      this.phase = status.authenticated ? 'ready' : status.setup_required ? 'setup' : 'login'
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        this.phase = 'login'
      } else {
        this.error = errorMessage(e)
        this.phase = 'offline'
      }
    }
  }

  /**
   * @param {string} username
   * @param {string} password
   */
  async login(username, password) {
    const res = await api.auth.login(username, password)
    this.username = res.username
    this.phase = 'ready'
  }

  /**
   * @param {string} username
   * @param {string} password
   */
  async setup(username, password) {
    const res = await api.auth.setup(username, password)
    this.username = res.username
    this.phase = 'ready'
  }

  async logout() {
    try {
      await api.auth.logout()
    } catch {
      // the local session is dropped either way
    }
    this.signedOut()
  }

  signedOut() {
    this.username = null
    if (this.phase === 'ready') this.phase = 'login'
  }
}

export const auth = new Auth()

setUnauthorizedHandler(() => auth.signedOut())
