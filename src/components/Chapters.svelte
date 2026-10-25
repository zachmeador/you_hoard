<script>
  /** @import { Chapter } from '../lib/types' */
  import { dur } from '../lib/format.js'

  /** @type {{ chapters: Chapter[], time: number, onseek: (t: number) => void }} */
  let { chapters, time, onseek } = $props()

  /** @type {HTMLOListElement | undefined} */
  let list = $state()
  const current = $derived(chapters.findLastIndex((c) => c.start <= time))

  $effect(() => {
    const row = list?.children[current]
    if (!list || !(row instanceof HTMLElement)) return
    const top = row.offsetTop
    if (top < list.scrollTop || top + row.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTop = top - list.clientHeight / 2 + row.offsetHeight / 2
    }
  })
</script>

<section aria-labelledby="chapters-h">
  <h2 class="label" id="chapters-h">Chapters</h2>
  <ol class="chapters" bind:this={list}>
    {#each chapters as chapter, i (chapter.start)}
      <li>
        <button type="button" aria-current={i === current ? 'true' : undefined} onclick={() => onseek(chapter.start)}>
          <span class="t">{dur(chapter.start)}</span><span class="n">{chapter.title}</span>
        </button>
      </li>
    {/each}
  </ol>
</section>
