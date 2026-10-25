<script>
  /** @import { Subtitle, VideoDetail } from '../lib/types' */
  import { untrack } from 'svelte'
  import { dur, languageName, qualityWithRate, shortLang, SUBTITLE_SOURCES } from '../lib/format.js'
  import { prefs } from '../lib/prefs.svelte.js'
  import Icon from './Icon.svelte'

  /** @type {{ video: VideoDetail, time?: number }} */
  let { video, time = $bindable(0) } = $props()

  const chapters = $derived(video.chapters ?? [])
  const heatmap = $derived(video.heatmap ?? [])
  const sponsors = $derived(video.sponsor_segments ?? [])
  const subtitles = $derived(video.subtitles ?? [])
  const vertical = $derived((video.height ?? 0) > (video.width ?? 0))
  const aspect = $derived(video.width && video.height ? `${video.width} / ${video.height}` : '16 / 9')

  /** @type {HTMLVideoElement | undefined} */
  let el = $state()
  /** @type {HTMLDivElement | undefined} */
  let wrap = $state()
  let paused = $state(true)
  let fine = $state(0)
  let length = $state(untrack(() => video.duration ?? 0))
  let volume = $state(1)
  let muted = $state(false)
  let fullscreen = $state(false)
  let idle = $state(false)
  let failed = $state(false)
  let wanted = $state(untrack(() => prefs.captions))
  /** @type {'' | 'captions' | 'audio'} */
  let menu = $state('')
  /** @type {{ label: string, enabled: boolean }[]} */
  let audio = $state([])
  /** @type {{ x: number, t: number } | null} */
  let hover = $state(null)
  /** @type {ReturnType<typeof setTimeout> | undefined} */
  let idleTimer

  const caption = $derived(subtitles.some((t) => t.lang === wanted) ? wanted : '')
  const hidden = $derived(idle && !paused && menu === '')
  const chapter = $derived(chapters.findLast((c) => c.start <= fine))
  const ticks = $derived(chapters.filter((c) => c.start > 0 && c.start < length))
  const heat = $derived.by(() => {
    if (!heatmap.length || !length) return ''
    const points = heatmap.map(
      (p) => `${(((p.start + p.end) / 2 / length) * 100).toFixed(2)},${(100 - p.value * 100).toFixed(1)}`
    )
    return `M0,100 L${points.join(' L')} L100,100 Z`
  })
  const hoverChapter = $derived(hover ? chapters.findLast((c) => c.start <= (hover?.t ?? 0)) : undefined)

  /** @param {Subtitle} track */
  function captionLabel(track) {
    const source = SUBTITLE_SOURCES[track.source]
    return `${track.name || languageName(track.lang)}${source ? ` (${source})` : ''}`
  }

  $effect(() => {
    const index = subtitles.findIndex((t) => t.lang === caption)
    const list = el?.textTracks
    if (!list) return
    for (let i = 0; i < list.length; i++) list[i].mode = i === index ? 'showing' : 'disabled'
  })

  $effect(() => {
    if (paused || !el) return
    const media = el
    let frame = requestAnimationFrame(function tick() {
      fine = media.currentTime
      frame = requestAnimationFrame(tick)
    })
    return () => cancelAnimationFrame(frame)
  })

  /** @param {number} value */
  const clamp = (value) => Math.min(Math.max(0, value), length || Infinity)
  const pct = (/** @type {number} */ t) => (length ? Math.min(100, (t / length) * 100) : 0)

  /**
   * @param {number} t seconds
   * @param {{ play?: boolean }} [options]
   */
  export function seek(t, { play = false } = {}) {
    if (!el) return
    el.currentTime = clamp(t)
    fine = time = el.currentTime
    if (play) {
      el.play().catch(() => {})
      wrap?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  }

  function toggle() {
    if (!el) return
    if (el.paused) el.play().catch(() => {})
    else el.pause()
  }

  function toggleMute() {
    if (el) el.muted = !el.muted
  }

  function toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
    else if (wrap?.requestFullscreen) wrap.requestFullscreen().catch(() => {})
    else /** @type {any} */ (el)?.webkitEnterFullscreen?.()
  }

  function readAudio() {
    const list = /** @type {any} */ (el)?.audioTracks
    if (!list || list.length < 2) {
      audio = []
      return
    }
    const fallback = video.audio_languages ?? []
    audio = Array.from({ length: list.length }, (_, i) => ({
      label: languageName(list[i].language || fallback[i] || '') || list[i].label || `Track ${i + 1}`,
      enabled: !!list[i].enabled
    }))
  }

  /** @param {number} index */
  function chooseAudio(index) {
    const list = /** @type {any} */ (el)?.audioTracks
    if (!list) return
    for (let i = 0; i < list.length; i++) list[i].enabled = i === index
    readAudio()
    menu = ''
  }

  /** @param {string} lang */
  function chooseCaption(lang) {
    wanted = lang
    prefs.setCaptions(lang)
    menu = ''
  }

  function wake() {
    idle = false
    clearTimeout(idleTimer)
    idleTimer = setTimeout(() => (idle = true), 2800)
  }

  /** @param {PointerEvent} event */
  function onwindowpointer(event) {
    const target = event.target
    if (!(target instanceof Element)) return
    if (wrap?.contains(target)) wake()
    if (menu && event.type === 'pointerdown' && !target.closest('.pm')) menu = ''
  }

  /** @param {KeyboardEvent} event */
  function onwindowkeydown(event) {
    if (event.metaKey || event.ctrlKey || event.altKey) return
    if (event.target instanceof Node && wrap?.contains(event.target)) wake()
    if (event.key === 'Escape' && menu) {
      menu = ''
      return
    }
    const target = event.target
    if (document.querySelector('dialog[open]')) return
    if (target instanceof HTMLElement) {
      if (target.isContentEditable) return
      // Controls keep their own keys: space presses a focused button, arrows move a slider.
      if (/^(INPUT|SELECT|TEXTAREA|BUTTON|A|SUMMARY)$/.test(target.tagName)) return
    }
    const key = event.key.toLowerCase()
    if (key === ' ' || key === 'k') toggle()
    else if (key === 'arrowleft') seek(fine - 5)
    else if (key === 'arrowright') seek(fine + 5)
    else if (key === 'j') seek(fine - 10)
    else if (key === 'l') seek(fine + 10)
    else if (key === 'f') toggleFullscreen()
    else if (key === 'm') toggleMute()
    else return
    event.preventDefault()
    wake()
  }

  /** @param {KeyboardEvent} event */
  function onseekkeydown(event) {
    /** @type {Record<string, number>} */
    const steps = { ArrowLeft: -5, ArrowRight: 5, ArrowDown: -5, ArrowUp: 5, PageDown: -30, PageUp: 30 }
    if (event.key in steps) seek(fine + steps[event.key])
    else if (event.key === 'Home') seek(0)
    else if (event.key === 'End') seek(length)
    else return
    event.preventDefault()
  }

  /** @param {PointerEvent & { currentTarget: HTMLElement }} event */
  function onscrubmove(event) {
    const box = event.currentTarget.getBoundingClientRect()
    const ratio = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width))
    hover = { x: Math.min(94, Math.max(6, ratio * 100)), t: ratio * length }
  }
</script>

<svelte:window onpointermove={onwindowpointer} onpointerdown={onwindowpointer} onkeydown={onwindowkeydown} />
<svelte:document onfullscreenchange={() => (fullscreen = document.fullscreenElement === wrap)} />

<div
  class="player"
  class:vert={vertical}
  class:playing={!paused}
  class:hide={hidden}
  bind:this={wrap}
  style:aspect-ratio={aspect}
>
  <!-- Subtitles are real tracks with their own labels; there is no separate captions track. -->
  <!-- svelte-ignore a11y_media_has_caption -->
  <video
    bind:this={el}
    src={video.media_url}
    poster={video.thumbnail_url ?? undefined}
    preload="metadata"
    playsinline
    onplay={() => {
      paused = false
      wake()
    }}
    onpause={() => {
      paused = true
      idle = false
    }}
    onended={() => (paused = true)}
    ontimeupdate={() => (fine = time = el?.currentTime ?? 0)}
    onloadedmetadata={() => {
      if (el && Number.isFinite(el.duration)) length = el.duration
      readAudio()
    }}
    ondurationchange={() => {
      if (el && Number.isFinite(el.duration)) length = el.duration
    }}
    onvolumechange={() => {
      volume = el?.volume ?? 1
      muted = el?.muted ?? false
    }}
    onerror={() => (failed = true)}
  >
    {#each subtitles as track (track.lang)}
      <track kind="subtitles" src={track.url} srclang={track.lang} label={captionLabel(track)} />
    {/each}
  </video>
  <div class="scrim"></div>
  <button
    type="button"
    class="surface"
    tabindex="-1"
    aria-hidden="true"
    onmousedown={(event) => event.preventDefault()}
    onclick={toggle}
    ondblclick={toggleFullscreen}
  ></button>

  {#if failed}
    <div class="pov">
      <span class="what">This file can't be played in this browser</span>
      <a class="info" href={video.media_url} download>Download the file</a>
    </div>
  {:else}
    {#if paused}
      <button type="button" class="big-play" aria-label="Play" onclick={toggle}><Icon name="play" /></button>
    {/if}
    <div class="pctl" class:heat={heat !== ''}>
      <button type="button" aria-label={paused ? 'Play' : 'Pause'} onclick={toggle}>
        <Icon name={paused ? 'play' : 'pause'} />
      </button>
      <span class="time">
        <span>{dur(fine)}</span> / {dur(length)}
        {#if chapter}<span class="chap">· {chapter.title}</span>{/if}
      </span>
      <div
        class="scrub"
        class:heat={heat !== ''}
        role="presentation"
        onpointermove={onscrubmove}
        onpointerleave={() => (hover = null)}
      >
        {#if heat}
          <svg class="heat" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><path d={heat} /></svg>
        {/if}
        {#each sponsors as segment (segment.start)}
          <span
            class="skip"
            title="{segment.category} {dur(segment.start)}–{dur(segment.end)}"
            style:left="{pct(segment.start)}%"
            style:width="{pct(segment.end) - pct(segment.start)}%"
          ></span>
        {/each}
        <i style:width="{pct(fine)}%"></i>
        {#each ticks as tick (tick.start)}
          <b style:left="{pct(tick.start)}%"></b>
        {/each}
        <input
          class="seek"
          type="range"
          aria-label="Seek"
          aria-valuetext="{dur(fine)} of {dur(length)}"
          min="0"
          max={length || 0}
          step="any"
          value={fine}
          oninput={(event) => seek(Number(event.currentTarget.value))}
          onkeydown={onseekkeydown}
        />
        {#if hover}
          <span class="tip" style:left="{hover.x}%">{dur(hover.t)}{hoverChapter ? ` · ${hoverChapter.title}` : ''}</span>
        {/if}
      </div>
      {#if subtitles.length}
        <span class="pm">
          <button
            type="button"
            class="cc"
            aria-haspopup="menu"
            aria-expanded={menu === 'captions'}
            onclick={() => (menu = menu === 'captions' ? '' : 'captions')}
          >
            CC{shortLang(caption) ? ` ${shortLang(caption)}` : ''}<span class="sr"> subtitles</span>
          </button>
          {#if menu === 'captions'}
            <div class="pmenu" role="menu" aria-label="Subtitles">
              <button type="button" role="menuitemradio" aria-checked={caption === ''} onclick={() => chooseCaption('')}>
                Off{#if caption === ''}<Icon name="check" />{/if}
              </button>
              {#each subtitles as track (track.lang)}
                <button
                  type="button"
                  role="menuitemradio"
                  aria-checked={caption === track.lang}
                  onclick={() => chooseCaption(track.lang)}
                >
                  {captionLabel(track)}{#if caption === track.lang}<Icon name="check" />{/if}
                </button>
              {/each}
            </div>
          {/if}
        </span>
      {/if}
      {#if audio.length > 1}
        <span class="pm">
          <button
            type="button"
            aria-haspopup="menu"
            aria-expanded={menu === 'audio'}
            aria-label="Audio language"
            onclick={() => (menu = menu === 'audio' ? '' : 'audio')}
          >
            <Icon name="vol" />
          </button>
          {#if menu === 'audio'}
            <div class="pmenu" role="menu" aria-label="Audio language">
              {#each audio as track, i (i)}
                <button type="button" role="menuitemradio" aria-checked={track.enabled} onclick={() => chooseAudio(i)}>
                  {track.label}{#if track.enabled}<Icon name="check" />{/if}
                </button>
              {/each}
            </div>
          {/if}
        </span>
      {/if}
      {#if video.quality}<span class="pq">{qualityWithRate(video)}</span>{/if}
      <span class="pvol">
        <button type="button" aria-label={muted || volume === 0 ? 'Unmute' : 'Mute'} onclick={toggleMute}>
          <Icon name={muted || volume === 0 ? 'mute' : 'vol'} />
        </button>
        <input
          class="vol"
          type="range"
          aria-label="Volume"
          min="0"
          max="1"
          step="0.05"
          value={muted ? 0 : volume}
          style:--v="{Math.round((muted ? 0 : volume) * 100)}%"
          oninput={(event) => {
            if (!el) return
            el.volume = Number(event.currentTarget.value)
            el.muted = el.volume === 0
          }}
        />
      </span>
      <button type="button" aria-label={fullscreen ? 'Exit full screen' : 'Full screen'} onclick={toggleFullscreen}>
        <Icon name="full" />
      </button>
    </div>
  {/if}
</div>
