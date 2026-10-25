/** @import { Settings, SettingsOptions } from './types' */
import { api } from './api.js'

/** @type {SettingsOptions} */
export const DEFAULT_OPTIONS = {
  qualities: ['best', '2160p', '1440p', '1080p', '720p', '480p', '360p'],
  check_intervals: [1, 3, 6, 12, 24, 72, 168],
  trash_days: [0, 7, 30, 90],
  policies: ['none', 'new', 'recent', 'all'],
  content_types: ['video', 'short', 'live'],
  languages: []
}

class LibrarySettings {
  /** @type {Settings | null} */
  current = $state(null)
  options = $derived({ ...DEFAULT_OPTIONS, ...this.current?.options })
  /** @type {Promise<Settings> | null} */
  #pending = null

  /** Loads the settings once per session; later calls share the same request. */
  load() {
    this.#pending ??= api.settings.get().then(
      (settings) => (this.current = settings),
      (error) => {
        this.#pending = null
        throw error
      }
    )
    return this.#pending
  }

  /** @param {Settings} settings */
  set(settings) {
    this.current = settings
    this.#pending = Promise.resolve(settings)
  }
}

export const librarySettings = new LibrarySettings()
