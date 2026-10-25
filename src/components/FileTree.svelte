<script>
  /** @import { VideoFile } from '../lib/types' */
  import { bytes } from '../lib/format.js'
  import { copyText } from '../lib/clipboard.js'
  import { notify } from '../lib/toasts.svelte.js'
  import Icon from './Icon.svelte'

  /** @type {{ files: VideoFile[], root: string | null }} */
  let { files, root } = $props()

  const media = $derived(files.find((f) => f.kind === 'media'))
  const stem = $derived(media ? base(media.path).replace(/\.[^.]+$/, '') : '')
  const folders = $derived.by(() => {
    /** @type {Map<string, VideoFile[]>} */
    const map = new Map()
    for (const file of files) {
      const dir = file.path.includes('/') ? file.path.slice(0, file.path.lastIndexOf('/') + 1) : ''
      map.set(dir, [...(map.get(dir) ?? []), file])
    }
    return [...map]
  })

  /** @param {string} path */
  function base(path) {
    return path.slice(path.lastIndexOf('/') + 1)
  }

  /** @param {VideoFile} file */
  function label(file) {
    const name = base(file.path)
    return stem && file.kind !== 'media' && name.startsWith(`${stem}.`) ? `…${name.slice(stem.length)}` : name
  }

  async function copy() {
    if (!media) return
    const ok = await copyText(root ? `${root}/${media.path}` : media.path)
    if (ok) notify.success('Path copied')
    else notify.info('Copy is not available here')
  }
</script>

<section aria-labelledby="files-h">
  <h2 class="label" id="files-h">Files</h2>
  {#each folders as [dir, list], index (dir)}
    <ul class="tree">
      {#if index === 0}<li class="root">{root ?? 'media'}/</li>{/if}
      {#if dir}<li><span class="f dir">{dir}</span></li>{/if}
    </ul>
    <ul class="tree" style:margin-left={dir ? '14px' : undefined}>
      {#each list as file (file.path)}
        <li class:media={file.kind === 'media'}>
          <span class="f">{label(file)}</span>
          <span class="sz">{bytes(file.size)}</span>
        </li>
      {/each}
    </ul>
  {/each}
  <div class="file-acts">
    <button type="button" class="btn sm" onclick={copy}><Icon name="copy" />Copy path</button>
  </div>
</section>
