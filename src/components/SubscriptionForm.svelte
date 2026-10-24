<script module>
  /** @import { DownloadPolicy, Settings, Subscription, SubscriptionKind, SubscriptionOptions, VideoType } from '../lib/types' */
  import { parseLanguages } from '../lib/format.js'

  /**
   * @typedef {{
   *   enabled: boolean,
   *   content_types: VideoType[],
   *   download_policy: DownloadPolicy,
   *   recent_count: number,
   *   quality: string | null,
   *   subtitles: 'default' | 'none' | 'custom',
   *   subtitle_text: string,
   *   download_comments: boolean | null,
   *   check_interval_hours: number
   * }} SubscriptionFormValue
   */

  /**
   * @param {Settings | null} settings
   * @returns {SubscriptionFormValue}
   */
  export function newSubscriptionForm(settings) {
    return {
      enabled: true,
      content_types: ['video', 'short', 'live'],
      download_policy: 'new',
      recent_count: 10,
      quality: null,
      subtitles: 'default',
      subtitle_text: '',
      download_comments: null,
      check_interval_hours: settings?.check_interval_hours ?? 24
    }
  }

  /**
   * @param {Subscription} sub
   * @returns {SubscriptionFormValue}
   */
  export function subscriptionForm(sub) {
    const langs = sub.subtitle_languages
    return {
      enabled: sub.enabled,
      content_types: [...sub.content_types],
      download_policy: sub.download_policy,
      recent_count: sub.recent_count,
      quality: sub.quality,
      subtitles: langs == null ? 'default' : langs.length ? 'custom' : 'none',
      subtitle_text: (langs ?? []).join(', '),
      download_comments: sub.download_comments,
      check_interval_hours: sub.check_interval_hours
    }
  }

  /**
   * @param {SubscriptionFormValue} form
   * @param {SubscriptionKind} kind
   * @returns {SubscriptionOptions}
   */
  export function subscriptionPayload(form, kind) {
    /** @type {SubscriptionOptions} */
    const payload = {
      enabled: form.enabled,
      download_policy: form.download_policy,
      recent_count: Math.max(1, Math.round(Number(form.recent_count) || 1)),
      quality: form.quality,
      subtitle_languages:
        form.subtitles === 'default' ? null : form.subtitles === 'none' ? [] : parseLanguages(form.subtitle_text),
      download_comments: form.download_comments,
      check_interval_hours: form.check_interval_hours
    }
    if (kind === 'channel') payload.content_types = [...form.content_types]
    return payload
  }

  /**
   * @param {SubscriptionFormValue} form
   * @param {SubscriptionKind} kind
   */
  export function subscriptionFormProblem(form, kind) {
    if (kind === 'channel' && form.content_types.length === 0) return 'Pick at least one content type.'
    if (form.download_policy === 'recent' && !(Number(form.recent_count) >= 1)) return 'Recent count must be at least 1.'
    if (form.subtitles === 'custom' && parseLanguages(form.subtitle_text).length === 0) {
      return 'Enter at least one subtitle language, or pick None.'
    }
    return ''
  }
</script>

<script>
  import { CONTENT_TYPES, POLICIES, interval, languages, qualityLabel } from '../lib/format.js'
  import { librarySettings } from '../lib/settings.svelte.js'

  /** @type {{ kind: SubscriptionKind, value: SubscriptionFormValue }} */
  let { kind, value = $bindable() } = $props()

  const uid = $props.id()
  const settings = $derived(librarySettings.current)
  const options = $derived(librarySettings.options)
  const intervals = $derived(
    options.check_intervals.includes(value.check_interval_hours)
      ? options.check_intervals
      : [...options.check_intervals, value.check_interval_hours].sort((a, b) => a - b)
  )

  /** @param {string | null | undefined} text */
  function libraryDefault(text) {
    return settings && text ? `Library default (${text})` : 'Library default'
  }
</script>

<div class="sub-form">
  {#if kind === 'channel'}
    <fieldset>
      <legend>Content types</legend>
      <div class="cluster">
        {#each options.content_types as type (type)}
          <label class="check">
            <input type="checkbox" value={type} bind:group={value.content_types} />
            {CONTENT_TYPES[type] ?? type}
          </label>
        {/each}
      </div>
    </fieldset>
  {/if}

  <fieldset>
    <legend>Download policy</legend>
    <div class="policies">
      {#each options.policies as policy (policy)}
        <div class="policy" class:selected={value.download_policy === policy}>
          <label class="check">
            <input
              type="radio"
              name="{uid}-policy"
              value={policy}
              bind:group={value.download_policy}
              aria-describedby="{uid}-{policy}-help"
            />
            {POLICIES[policy]?.label ?? policy}
          </label>
          <span id="{uid}-{policy}-help" class="hint">{POLICIES[policy]?.help ?? ''}</span>
        </div>
      {/each}
    </div>
  </fieldset>

  {#if value.download_policy === 'recent'}
    <div class="field narrow">
      <label class="field-label" for="{uid}-recent">Recent count (N)</label>
      <input id="{uid}-recent" type="number" min="1" max="5000" step="1" required bind:value={value.recent_count} />
    </div>
  {/if}

  <div class="selects">
    <div class="field">
      <label class="field-label" for="{uid}-quality">Quality</label>
      <select id="{uid}-quality" bind:value={value.quality}>
        <option value={null}>{libraryDefault(qualityLabel(settings?.default_quality))}</option>
        {#each options.qualities as q (q)}
          <option value={q}>{qualityLabel(q)}</option>
        {/each}
      </select>
    </div>
    <div class="field">
      <label class="field-label" for="{uid}-subtitles">Subtitles</label>
      <select id="{uid}-subtitles" bind:value={value.subtitles}>
        <option value="default">{libraryDefault(languages(settings?.subtitle_languages))}</option>
        <option value="none">None</option>
        <option value="custom">Custom languages</option>
      </select>
    </div>
    {#if value.subtitles === 'custom'}
      <div class="field">
        <label class="field-label" for="{uid}-languages">Subtitle languages</label>
        <input
          id="{uid}-languages"
          bind:value={value.subtitle_text}
          placeholder="en, de"
          autocomplete="off"
          spellcheck="false"
        />
      </div>
    {/if}
    <div class="field">
      <label class="field-label" for="{uid}-comments">Comments</label>
      <select id="{uid}-comments" bind:value={value.download_comments}>
        <option value={null}>{libraryDefault(settings ? (settings.download_comments ? 'download' : 'skip') : '')}</option>
        <option value={true}>Download comments</option>
        <option value={false}>Skip comments</option>
      </select>
    </div>
    <div class="field">
      <label class="field-label" for="{uid}-interval">Check interval</label>
      <select id="{uid}-interval" bind:value={value.check_interval_hours}>
        {#each intervals as hours (hours)}
          <option value={hours}>{interval(hours)}</option>
        {/each}
      </select>
    </div>
  </div>

  <div>
    <label class="check">
      <input type="checkbox" bind:checked={value.enabled} />
      Enabled
    </label>
    <p class="hint">Enabled subscriptions are checked on schedule and download according to the policy.</p>
  </div>
</div>

<style>
  .sub-form {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }

  .policies {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: var(--space-2);
  }

  .policy {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--background);
    transition: border-color 0.2s, box-shadow 0.2s;
  }

  .policy.selected {
    border-color: var(--terminal-green);
    box-shadow: var(--glow-primary);
  }

  .policy .hint {
    padding-left: 1.5rem;
  }

  .narrow {
    max-width: 12rem;
  }

  .selects {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: var(--space-3);
  }
</style>
