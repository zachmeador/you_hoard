import { untrack } from 'svelte'

/**
 * Runs `task` every `ms` while the page is visible, never overlapping runs, and right away when
 * the tab becomes visible again. Returns a stop function (handy as an `$effect` teardown).
 * @param {() => unknown} task
 * @param {number} ms
 * @param {{ immediate?: boolean }} [options]
 */
export function poll(task, ms, { immediate = true } = {}) {
  let stopped = false
  let running = false
  /** @type {ReturnType<typeof setTimeout> | undefined} */
  let timer

  async function tick() {
    clearTimeout(timer)
    if (stopped || running) return
    if (!document.hidden) {
      running = true
      try {
        await untrack(task)
      } catch {
        // polling is best effort; the next tick tries again
      } finally {
        running = false
      }
    }
    if (!stopped) timer = setTimeout(tick, ms)
  }

  function onVisibilityChange() {
    if (!document.hidden) tick()
  }

  document.addEventListener('visibilitychange', onVisibilityChange)
  if (immediate) tick()
  else timer = setTimeout(tick, ms)

  return () => {
    stopped = true
    clearTimeout(timer)
    document.removeEventListener('visibilitychange', onVisibilityChange)
  }
}
