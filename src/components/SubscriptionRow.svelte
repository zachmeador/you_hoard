<script>
  /** @import { Subscription } from '../lib/types' */
  import { policyLabel, POLICIES, rel, sourceMeta } from '../lib/format.js'
  import { href } from '../lib/router.svelte.js'
  import { clock } from '../lib/ui.svelte.js'
  import Avatar from './Avatar.svelte'
  import HoldCell from './HoldCell.svelte'
  import Icon from './Icon.svelte'
  import LastCheck from './LastCheck.svelte'
  import Menu from './Menu.svelte'
  import Pips from './Pips.svelte'

  /**
   * @type {{
   *   sub: Subscription,
   *   ontoggle: (enabled: boolean) => void,
   *   oncheck: (full: boolean) => void,
   *   onremove: () => void
   * }}
   */
  let { sub, ontoggle, oncheck, onremove } = $props()

  const label = $derived(policyLabel(sub))
  const pips = $derived(POLICIES[sub.download_policy].pips)
  const next = $derived(sub.enabled && sub.next_check_at && !sub.checking ? rel(sub.next_check_at, clock.now) : '')
</script>

<tr class:off={!sub.enabled}>
  <td class="c-src c-main keep">
    <div class="src">
      <Avatar name={sub.title} src={sub.channel?.avatar_url} playlist={sub.kind === 'playlist'} />
      <div style="min-width: 0">
        <a class="ttl" href={href(`/subscriptions/${sub.id}`)}>{sub.title}</a>
        <div class="k">
          <span class="pol-inline"><Pips n={pips} />{label} · </span>{sourceMeta(sub)}
        </div>
      </div>
    </div>
    <div class="m-meta">
      <Pips n={pips} />{label}{sub.enabled ? '' : ' · paused'}
      <HoldCell counts={sub.counts} />
      <div style="margin-top: 8px"><LastCheck {sub} /></div>
      {#if next}<div style="margin-top: 2px">Next check {next}</div>{/if}
    </div>
  </td>
  <td class="c-pol"><Pips n={pips} />{label}</td>
  <td class="c-hold"><HoldCell counts={sub.counts} /></td>
  <td class="c-last">
    <LastCheck {sub} />
    <div class="next-inline">{next ? `Next ${next}` : !sub.enabled ? 'Paused' : ''}</div>
  </td>
  <td class="c-next dim">
    {#if !sub.enabled}<span class="muted">Paused</span>{:else if next}<span>{next}</span>{:else}—{/if}
  </td>
  <td class="c-on c-side keep">
    <input
      type="checkbox"
      class="sw"
      checked={sub.enabled}
      aria-label="{sub.enabled ? 'Enabled' : 'Paused'}: {sub.title}"
      onchange={(event) => ontoggle(event.currentTarget.checked)}
    />
  </td>
  <td class="c-act">
    <button
      type="button"
      class="btn icon sm quiet"
      aria-label="Check {sub.title} now"
      title="Check now"
      disabled={sub.checking}
      onclick={() => oncheck(false)}
    >
      <Icon name="refresh" />
    </button>
    <Menu label="More actions for {sub.title}">
      {#snippet children(close)}
        <button
          type="button"
          role="menuitem"
          onclick={() => {
            close()
            oncheck(true)
          }}
        >
          <Icon name="refresh" />Full rescan
        </button>
        <a role="menuitem" href={href(`/subscriptions/${sub.id}`)} onclick={close}><Icon name="sliders" />Edit policy</a>
        <a role="menuitem" href={sub.url} target="_blank" rel="noopener noreferrer" onclick={close}>
          <Icon name="ext" />Open on YouTube
        </a>
        <hr />
        <button
          type="button"
          role="menuitem"
          class="danger"
          onclick={() => {
            close()
            onremove()
          }}
        >
          <Icon name="trash" />Delete…
        </button>
      {/snippet}
    </Menu>
  </td>
</tr>
