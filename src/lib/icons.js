const SOLID = 'style="fill:currentColor;stroke:none"'
const KNOB = 'style="fill:var(--knob,var(--bg-1))"'

/** Stroke icons on a 16px grid. Markup is static, never user input. */
export const ICONS = {
  shelf: '<path d="M2.5 2.5v11M5.5 2.5v11M8.5 4.5v9M10.6 4.6l2.9 8.6M1.5 13.5h13"/>',
  feed: `<circle cx="3.5" cy="12.5" r="1" ${SOLID}/><path d="M2.5 7.5a6 6 0 0 1 6 6M2.5 2.5a11 11 0 0 1 11 11"/>`,
  queue: '<path d="M8 2.5v8M4.5 7 8 10.5 11.5 7M2.5 13.5h11"/>',
  sliders: `<path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11"/><circle cx="10.5" cy="4.5" r="1.6" ${KNOB}/><circle cx="5.5" cy="8" r="1.6" ${KNOB}/><circle cx="9" cy="11.5" r="1.6" ${KNOB}/>`,
  search: '<circle cx="7" cy="7" r="4.5"/><path d="m10.5 10.5 3 3"/>',
  plus: '<path d="M8 3v10M3 8h10"/>',
  grid: '<path d="M2.5 2.5h4.5v4.5H2.5zM9 2.5h4.5v4.5H9zM2.5 9h4.5v4.5H2.5zM9 9h4.5v4.5H9z"/>',
  list: '<path d="M2.5 4h2M6.5 4h7M2.5 8h2M6.5 8h7M2.5 12h2M6.5 12h7"/>',
  ext: '<path d="M9.5 2.5h4v4M13.5 2.5l-6 6M11.5 9.5v4h-9v-9h4"/>',
  check: '<path d="m3 8.5 3 3 7-7"/>',
  x: '<path d="m4 4 8 8M12 4l-8 8"/>',
  clock: '<circle cx="8" cy="8" r="5.5"/><path d="M8 5v3.2l2 1.3"/>',
  retry: '<path d="M13 8a5 5 0 1 1-1.5-3.6M13 2.5v3h-3"/>',
  pause: '<path d="M5.5 3.5v9M10.5 3.5v9"/>',
  play: `<path d="M5 3.2v9.6L12.8 8z" ${SOLID}/>`,
  trash: '<path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.7 9h5.6l.7-9"/>',
  more: `<circle cx="3.5" cy="8" r="1.1" ${SOLID}/><circle cx="8" cy="8" r="1.1" ${SOLID}/><circle cx="12.5" cy="8" r="1.1" ${SOLID}/>`,
  down: '<path d="M8 3v10M4.5 9.5 8 13l3.5-3.5"/>',
  up: '<path d="M8 13V3M4.5 6.5 8 3l3.5 3.5"/>',
  chev: '<path d="m4 6 4 4 4-4"/>',
  left: '<path d="m10 3.5-4.5 4.5 4.5 4.5"/>',
  right: '<path d="m6 3.5 4.5 4.5L6 12.5"/>',
  sun: '<circle cx="8" cy="8" r="3"/><path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1"/>',
  moon: '<path d="M13 9.5A5.5 5.5 0 1 1 6.5 3a4.5 4.5 0 0 0 6.5 6.5z"/>',
  copy: '<path d="M5.5 5.5h7v8h-7zM3.5 10.5v-8h7"/>',
  full: '<path d="M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10"/>',
  dl: '<path d="M8 2.5v7M5 6.5l3 3 3-3M3 12.5h10"/>',
  eye: '<path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2"/>',
  refresh: '<path d="M13.5 3v3h-3M2.5 13v-3h3"/><path d="M12.8 6A5 5 0 0 0 3.6 5M3.2 10a5 5 0 0 0 9.2 1"/>',
  folder: '<path d="M2 4.5h4l1.5 1.5H14v7H2z"/>',
  playlist: '<path d="M2.5 4h8M2.5 7.5h8M2.5 11h4.5M10 10v4l3.5-2z"/>',
  vol: '<path d="M2.5 6h2.5l3.5-3v10L5 10H2.5zM11 5.5a3.5 3.5 0 0 1 0 5"/>',
  mute: '<path d="M2.5 6h2.5l3.5-3v10L5 10H2.5zM11 6l3 4M14 6l-3 4"/>',
  chat: '<path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2z"/>',
  heart: '<path d="M8 13.5S2.5 10 2.5 6.2A2.9 2.9 0 0 1 8 5a2.9 2.9 0 0 1 5.5 1.2C13.5 10 8 13.5 8 13.5z"/>',
  pin: '<path d="M6 2.5h4l-.5 4 2 2.5H4.5l2-2.5zM8 9v4.5"/>',
  verified: '<circle cx="8" cy="8" r="5.5"/><path d="m5.7 8.2 1.7 1.7 3-3.4"/>'
}

/** @typedef {keyof typeof ICONS} IconName */
