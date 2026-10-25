/** @param {string} key @param {string} fallback */
function read(key, fallback) {
  try {
    return localStorage.getItem(`yh-${key}`) ?? fallback
  } catch {
    return fallback
  }
}

/** @param {string} key @param {string} value */
function write(key, value) {
  try {
    localStorage.setItem(`yh-${key}`, value)
  } catch {
    // storage can be unavailable (private windows); the preference then lasts for the session
  }
}

const THEME_COLORS = { dark: '#110e0b', light: '#f8f4ef' }

class Prefs {
  /** @type {'dark' | 'light'} */
  theme = $state(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark')
  /** @type {'grid' | 'list'} */
  view = $state(read('view', 'grid') === 'list' ? 'list' : 'grid')
  /** @type {'name' | 'size'} */
  channelSort = $state(read('channel-sort', 'name') === 'size' ? 'size' : 'name')
  /** The subtitle language switched on last, or empty for off. */
  captions = $state(read('captions', ''))

  /** @param {'dark' | 'light'} theme */
  setTheme(theme) {
    this.theme = theme
    document.documentElement.dataset.theme = theme
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLORS[theme])
    write('theme', theme)
  }

  toggleTheme() {
    this.setTheme(this.theme === 'light' ? 'dark' : 'light')
  }

  /** @param {'grid' | 'list'} view */
  setView(view) {
    this.view = view
    write('view', view)
  }

  /** @param {'name' | 'size'} sort */
  setChannelSort(sort) {
    this.channelSort = sort
    write('channel-sort', sort)
  }

  /** @param {string} lang */
  setCaptions(lang) {
    this.captions = lang
    write('captions', lang)
  }
}

export const prefs = new Prefs()
