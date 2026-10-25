<script>
  /** @import { ChatMessage } from '../lib/types' */
  import { tick, untrack } from 'svelte'
  import { ApiError, api, errorMessage } from '../lib/api.js'
  import { dur } from '../lib/format.js'

  /** Seconds of chat fetched at a time; a busy premiere can send thousands of messages a minute. */
  const SPAN = 30
  const BEHIND = 3
  const AHEAD = 1
  const SHOWN = 150

  /** @type {{ videoId: number, time: number, onseek: (t: number) => void }} */
  let { videoId, time, onseek } = $props()

  /** Messages by window number (`floor(seconds / SPAN)`), loaded as playback gets there. */
  let loaded = $state(/** @type {Record<number, ChatMessage[]>} */ ({}))
  let error = $state('')
  /** @type {HTMLDivElement | undefined} */
  let box = $state()
  let following = true
  /** @type {Set<number>} */
  const requested = new Set()

  const current = $derived(Math.floor(Math.max(0, time) / SPAN))
  /** The messages sent by now, newest last, trimmed to what fits on screen. */
  const shown = $derived.by(() => {
    /** @type {ChatMessage[]} */
    const all = []
    for (let w = Math.max(0, current - BEHIND); w <= current; w++) all.push(...(loaded[w] ?? []))
    const sent = all.filter((m) => m.t <= time)
    return sent.slice(-SHOWN)
  })

  /** @param {number} windowNumber */
  async function load(windowNumber) {
    requested.add(windowNumber)
    try {
      const res = await api.videos.chat(videoId, { since: windowNumber * SPAN, until: (windowNumber + 1) * SPAN })
      loaded[windowNumber] = res.items
    } catch (e) {
      requested.delete(windowNumber)
      error = e instanceof ApiError && e.status === 404 ? 'No chat replay was saved' : errorMessage(e)
    }
  }

  $effect(() => {
    const here = current
    untrack(() => {
      if (error) return
      for (let w = Math.max(0, here - BEHIND); w <= here + AHEAD; w++) if (!requested.has(w)) load(w)
      for (const key of Object.keys(loaded)) {
        const w = Number(key)
        if (w < here - BEHIND - 4 || w > here + AHEAD + 4) {
          delete loaded[w]
          requested.delete(w)
        }
      }
    })
  })

  $effect(() => {
    void shown
    tick().then(() => {
      if (following && box) box.scrollTop = box.scrollHeight
    })
  })

  function onscroll() {
    if (box) following = box.scrollHeight - box.scrollTop - box.clientHeight < 24
  }
</script>

<section aria-labelledby="chat-h">
  <h2 class="label" id="chat-h">Live chat</h2>
  {#if error}
    <p class="note">{error}</p>
  {:else}
    <!-- The log scrolls on its own, so it has to be reachable from the keyboard. -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div class="chat" role="log" aria-label="Live chat replay" tabindex="0" bind:this={box} {onscroll}>
      {#if shown.length}
        <ul>
          {#each shown as message (message)}
            <li>
              <button type="button" class="t" aria-label="Jump to {dur(message.t)}" onclick={() => onseek(message.t)}>
                {dur(message.t)}
              </button>
              <span class="who">{message.author}</span>
              <span class="txt">{message.text}</span>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="none">No messages yet</p>
      {/if}
    </div>
  {/if}
</section>
