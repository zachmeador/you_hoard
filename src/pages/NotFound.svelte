<script>
  import { href } from '../lib/router.svelte.js'
</script>

<svelte:head>
  <title>Not found · YouHoard</title>
</svelte:head>

<div class="empty">
  <b>Page not found</b>
  <a class="lnk" href={href('/library')}>Back to the library</a>
</div>
