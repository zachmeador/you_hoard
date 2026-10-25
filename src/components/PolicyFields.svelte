<script>
  /** @import { DownloadPolicy, SubscriptionKind, VideoType } from '../lib/types' */
  import { CONTENT_TYPES, POLICIES } from '../lib/format.js'
  import Pips from './Pips.svelte'

  /** @type {DownloadPolicy[]} */
  const POLICY_KEYS = ['none', 'new', 'recent', 'all']
  /** @type {VideoType[]} */
  const TYPES = ['video', 'short', 'live']

  /**
   * @type {{
   *   kind: SubscriptionKind,
   *   policy: DownloadPolicy,
   *   recentCount: number,
   *   types: VideoType[],
   *   onchange?: () => void
   * }}
   */
  let {
    kind,
    policy = $bindable(),
    recentCount = $bindable(),
    types = $bindable(),
    onchange
  } = $props()

  /** @param {DownloadPolicy} next */
  function choose(next) {
    policy = next
    onchange?.()
  }

  /** @param {VideoType} type @param {boolean} on */
  function toggle(type, on) {
    types = TYPES.filter((t) => (t === type ? on : types.includes(t)))
    onchange?.()
  }
</script>

<div class="pseg" role="group" aria-label="Download policy">
  {#each POLICY_KEYS as key (key)}
    <button type="button" aria-pressed={policy === key} title={POLICIES[key].help} onclick={() => choose(key)}>
      <Pips n={POLICIES[key].pips} />{POLICIES[key].label}
    </button>
  {/each}
</div>
<div class="pol-detail">
  {#if policy === 'recent'}
    <label class="n-input">
      Latest
      <input
        class="input"
        type="number"
        min="1"
        max="1000"
        aria-label="Number of latest entries per tab"
        bind:value={recentCount}
        oninput={() => onchange?.()}
      />
      {kind === 'channel' ? 'per tab, plus new uploads' : 'entries, plus new uploads'}
    </label>
  {:else}
    <span>{POLICIES[policy].help}</span>
  {/if}
  {#if kind === 'channel'}
    <span class="tab-group" role="group" aria-label="Tabs">
      <span class="muted" aria-hidden="true">Tabs</span>
      {#each TYPES as type (type)}
        <label class="chk">
          <input
            type="checkbox"
            checked={types.includes(type)}
            onchange={(event) => toggle(type, event.currentTarget.checked)}
          />{CONTENT_TYPES[type]}
        </label>
      {/each}
    </span>
  {/if}
</div>
