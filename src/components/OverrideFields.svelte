<script>
  /** @import { Overrides, Tri, ListMode } from '../lib/overrides.js' */
  import { defaultLabels } from '../lib/overrides.js'
  import { qualityLabel } from '../lib/format.js'
  import { librarySettings } from '../lib/settings.svelte.js'
  import FieldSelect from './FieldSelect.svelte'
  import LanguagePicker from './LanguagePicker.svelte'

  /** @type {{ value: Overrides, onchange?: () => void, quality?: boolean }} */
  let { value = $bindable(), onchange, quality = true } = $props()

  const labels = $derived(defaultLabels(librarySettings.current))
  const languages = $derived(librarySettings.options.languages)
  const qualityOptions = $derived([
    { value: '', label: labels.quality },
    ...librarySettings.options.qualities.map((q) => ({ value: q, label: qualityLabel(q) }))
  ])

  /** @param {string} defaultLabel @param {string} none */
  const listOptions = (defaultLabel, none) => [
    { value: 'default', label: defaultLabel },
    { value: 'none', label: none },
    { value: 'custom', label: 'Custom languages' }
  ]

  /**
   * @template {keyof Overrides} K
   * @param {K} key
   * @param {Overrides[K]} next
   */
  function set(key, next) {
    value[key] = next
    onchange?.()
  }
</script>

{#if quality}
  <FieldSelect
    label="Quality"
    value={value.quality}
    options={qualityOptions}
    onchange={(v) => set('quality', v)}
  />
{/if}
<FieldSelect
  label="Subtitles"
  value={value.subtitles}
  options={listOptions(labels.subtitles, 'None')}
  onchange={(v) => set('subtitles', /** @type {ListMode} */ (v))}
>
  {#if value.subtitles === 'custom'}
    <LanguagePicker
      label="Subtitle languages"
      value={value.subtitleLanguages}
      options={languages}
      onchange={(list) => set('subtitleLanguages', list)}
    />
  {/if}
</FieldSelect>
<FieldSelect
  label="Auto captions"
  value={value.autoCaptions}
  options={[
    { value: '', label: labels.autoCaptions },
    { value: 'true', label: 'Fill in with auto captions' },
    { value: 'false', label: 'Uploaded subtitles only' }
  ]}
  onchange={(v) => set('autoCaptions', /** @type {Tri} */ (v))}
/>
<FieldSelect
  label="Audio languages"
  value={value.audio}
  options={listOptions(labels.audio, 'Original only')}
  onchange={(v) => set('audio', /** @type {ListMode} */ (v))}
>
  {#if value.audio === 'custom'}
    <LanguagePicker
      label="Extra audio languages"
      value={value.audioLanguages}
      options={languages}
      onchange={(list) => set('audioLanguages', list)}
    />
  {/if}
</FieldSelect>
<FieldSelect
  label="Comments"
  value={value.comments}
  options={[
    { value: '', label: labels.comments },
    { value: 'true', label: 'Download comments' },
    { value: 'false', label: 'Skip comments' }
  ]}
  onchange={(v) => set('comments', /** @type {Tri} */ (v))}
/>
<FieldSelect
  label="Live chat"
  value={value.liveChat}
  options={[
    { value: '', label: labels.liveChat },
    { value: 'true', label: 'Save chat replay' },
    { value: 'false', label: 'Skip chat replay' }
  ]}
  onchange={(v) => set('liveChat', /** @type {Tri} */ (v))}
/>
<FieldSelect
  label="SponsorBlock"
  value={value.sponsorblock}
  options={[
    { value: '', label: labels.sponsorblock },
    { value: 'true', label: 'Save segment markers' },
    { value: 'false', label: 'Skip segment markers' }
  ]}
  onchange={(v) => set('sponsorblock', /** @type {Tri} */ (v))}
/>
