export const ui = $state({
  addVideoOpen: false,
  videosVersion: 0
})

export function videosChanged() {
  ui.videosVersion++
}

export const clock = $state({ now: Date.now() })

setInterval(() => {
  clock.now = Date.now()
}, 15_000)
