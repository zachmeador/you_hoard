/**
 * Tells a video link from a channel or playlist link, the way the server does.
 * @param {string} input
 * @returns {{ kind: 'video' | 'source', url: string } | null} null when it is not a YouTube link
 */
export function classifyInput(input) {
  const text = input.trim()
  if (!text) return null
  if (/^[\w-]{11}$/.test(text)) return { kind: 'video', url: text }
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
  if (host === 'youtu.be') return url.pathname.length > 1 ? { kind: 'video', url: text } : null
  if (host !== 'youtube.com') return null
  if (url.pathname === '/watch' && url.searchParams.get('v')) return { kind: 'video', url: text }
  if (/^\/(shorts|live|embed|v)\/[\w-]{11}/.test(url.pathname)) return { kind: 'video', url: text }
  return { kind: 'source', url: text }
}
