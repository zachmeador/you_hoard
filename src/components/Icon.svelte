<script>
  /** @import { IconName } from '../lib/icons.js' */
  import { ICONS } from '../lib/icons.js'

  /** @type {{ name: IconName, class?: string }} */
  let { name, class: className = '' } = $props()
</script>

<svg class="ic {className}" viewBox="0 0 16 16" aria-hidden="true" focusable="false">{@html ICONS[name]}</svg>
