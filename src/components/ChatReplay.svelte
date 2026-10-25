<script>
  /** @import { ChatMessage } from '../lib/types' */
  import { onMount, tick } from 'svelte'
  import { api } from '../lib/api.js'
  import { dur } from '../lib/format.js'
  import { Loader } from '../lib/loader.svelte.js'

  const WINDOW = 150

  /** @type {{ videoId: number, time: number, onseek: (t: number) => void }} */
  let { videoId, time, onseek } = $props()

  /** @type {Loader<{ items: ChatMessage[] }>} */
  const chat = new Loader()
  /** @type {HTMLDivElement | undefined} */
  let box = $state()
  let following = true

  const messages = $derived(chat.data?.items ?? [])
  /** The messages sent by now, newest last, trimmed to what fits on screen. */
  const shown = $derived.by(() => {
    let lo = 0
    let hi = messages.length
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (messages[mid].t <= time) lo = mid + 1
      else hi = mid
    }
    const start = Math.max(0, lo - WINDOW)
    return { start, items: messages.slice(start, lo) }
  })

  onMount(() => {
    chat.run(() => api.videos.chat(videoId))
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
  {#if chat.error}
    <p class="note">{chat.error}</p>
  {:else}
    <!-- The log scrolls on its own, so it has to be reachable from the keyboard. -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div class="chat" role="log" aria-label="Live chat replay" tabindex="0" bind:this={box} {onscroll}>
      {#if shown.items.length}
        <ul>
          {#each shown.items as message, i (shown.start + i)}
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
        <p class="none">{chat.loading ? 'Loading…' : 'No messages yet'}</p>
      {/if}
    </div>
  {/if}
</section>
