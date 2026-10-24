<script>
  import { STATUS } from '../lib/format.js'

  /** @type {{ status: string }} */
  let { status } = $props()

  const info = $derived(STATUS[status] ?? { label: status, tone: 'muted' })
</script>

<span class="badge badge-{info.tone}">{info.label}</span>
