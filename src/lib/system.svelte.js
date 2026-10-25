/** @import { SystemInfo } from './types' */
import { api } from './api.js'

const LOW_DISK = 0.1

class SystemState {
  /** @type {SystemInfo | null} */
  info = $state(null)

  /** What needs the owner's attention, shown as the dot on System in the nav. */
  problems = $derived.by(() => {
    const info = this.info
    /** @type {string[]} */
    const list = []
    if (!info) return list
    if (info.disk && info.disk.free / info.disk.total < LOW_DISK) list.push('Disk almost full')
    if (!info.ffmpeg) list.push('ffmpeg is missing')
    if (!info.js_runtime) list.push('No JavaScript runtime for yt-dlp')
    return list
  })

  async refresh() {
    this.info = await api.system.get()
  }
}

export const system = new SystemState()
