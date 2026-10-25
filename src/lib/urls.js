const VIDEO_ID = /^[\w-]{11}$/

/**
 * Tells a video link from a channel or playlist link, the way the server does.
 * @param {string} input
 * @returns {{ kind: 'video', url: string, id: string | null } | { kind: 'source', url: string } | null}
 *   null when it is not a YouTube link; `id` is null while the video ID is incomplete
 */
export function classifyInput(input) {
  const text = input.trim()
  if (!text) return null
  if (VIDEO_ID.test(text)) return { kind: 'video', url: text, id: text }
  if (text.startsWith('@') && text.length > 1) {
    return { kind: 'source', url: `https://www.youtube.com/${text}` }
  }
  /** @type {URL} */
  let url
  try {
    url = new URL(text.includes('://') ? text : `https://${text}`)
  } catch {
    return null
  }
  const host = url.hostname.replace(/^(www|m|music)\./, '')
  /** @param {string | undefined} id */
  const video = (id) => ({ kind: /** @type {const} */ ('video'), url: text, id: id && VIDEO_ID.test(id) ? id : null })
  if (host === 'youtu.be') return url.pathname.length > 1 ? video(url.pathname.split('/')[1]) : null
  if (host !== 'youtube.com') return null
  if (url.pathname === '/watch' && url.searchParams.get('v')) return video(url.searchParams.get('v') ?? undefined)
  const embedded = /^\/(?:shorts|live|embed|v)\/([^/?#]+)/.exec(url.pathname)
  if (embedded) return video(embedded[1])
  return { kind: 'source', url: text }
}
