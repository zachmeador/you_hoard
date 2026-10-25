<script>
  /** @import { IconName } from '../lib/icons.js' */
  /** @import { VideoOptions } from '../lib/types' */
  import { emptyOverrides, qualityChoices, videoOptions } from '../lib/overrides.js'
  import { librarySettings } from '../lib/settings.svelte.js'
  import Icon from './Icon.svelte'
  import OverrideFields from './OverrideFields.svelte'
  import SelectField from './SelectField.svelte'

  /** @type {{ label: string, icon?: IconName, busy?: boolean, onrun: (options: VideoOptions) => void }} */
  let { label, icon = 'dl', busy = false, onrun } = $props()

  let overrides = $state(emptyOverrides())
  let open = $state(false)

  const qualities = $derived(qualityChoices(librarySettings.current, librarySettings.options.qualities))
</script>

<SelectField
  label="Quality"
  bare
  value={overrides.quality}
  options={qualities}
  onchange={(value) => {
    overrides.quality = value
  }}
/>
<button
  type="button"
  class="disclose"
  aria-expanded={open}
  aria-controls="download-options"
  onclick={() => (open = !open)}
>
  <Icon name="chev" />Options
</button>
<button type="button" class="btn primary" disabled={busy} onclick={() => onrun(videoOptions(overrides))}>
  <Icon name={icon} />{label}
</button>
{#if open}
  <div id="download-options" class="ovr full"><OverrideFields bind:value={overrides} quality={false} /></div>
{/if}
