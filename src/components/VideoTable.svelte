<script>
  /** @import { Video } from '../lib/types' */
  import Icon from './Icon.svelte'
  import SortHeader from './SortHeader.svelte'
  import VideoRow from './VideoRow.svelte'

  /** @type {{ videos: Video[], sort: string, order: string, onsort: (key: string) => void }} */
  let { videos, sort, order, onsort } = $props()
</script>

<table class="tbl lib stack">
  <thead>
    <tr>
      <th class="c-th"><span class="sr">Thumbnail</span></th>
      <SortHeader key="title" label="Title" class="c-title" {sort} {order} {onsort} />
      <SortHeader key="published" label="Published" class="num c-pub" {sort} {order} {onsort} />
      <SortHeader key="duration" label="Length" class="num c-len" {sort} {order} {onsort} />
      <th class="c-st">Status</th>
      <th class="num c-file">File</th>
      <SortHeader key="archived" label="Archived" class="num c-arch" {sort} {order} {onsort} />
      <th class="c-seen" title="Watched"><span class="sr">Watched</span><Icon name="eye" /></th>
    </tr>
  </thead>
  <tbody>
    {#each videos as video (video.id)}
      <VideoRow {video} />
    {/each}
  </tbody>
</table>
