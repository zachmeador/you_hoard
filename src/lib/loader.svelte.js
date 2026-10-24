import { errorMessage } from './api.js'

/** @template T */
export class Loader {
  /** @type {T | undefined} */
  data = $state()
  error = $state('')
  loading = $state(false)
  #seq = 0

  /**
   * Runs `fetcher` and keeps only the newest result. Quiet runs (polling) don't touch the
   * loading flag or surface errors.
   * @param {() => Promise<T>} fetcher
   * @param {{ quiet?: boolean }} [options]
   */
  async run(fetcher, { quiet = false } = {}) {
    const seq = ++this.#seq
    if (!quiet) this.loading = true
    try {
      const data = await fetcher()
      if (seq === this.#seq) {
        this.data = data
        this.error = ''
      }
    } catch (e) {
      if (seq === this.#seq && !quiet) this.error = errorMessage(e)
    } finally {
      if (seq === this.#seq) this.loading = false
    }
  }
}
