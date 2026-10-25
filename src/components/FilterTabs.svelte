<script>
  import { int } from '../lib/format.js'

  /**
   * @type {{
   *   label: string,
   *   value: string,
   *   tabs: { value: string, label: string, count?: number | null, gone?: boolean, gap?: boolean }[],
   *   onchange: (value: string) => void,
   *   class?: string
   * }}
   */
  let { label, value, tabs, onchange, class: className = '' } = $props()
</script>

<div class="tabs {className}" role="group" aria-label={label}>
  {#each tabs as tab (tab.value)}
    {#if tab.gap}<span class="spacer"></span>{/if}
    <button
      type="button"
      class:gone={tab.gone}
      aria-pressed={value === tab.value}
      onclick={() => onchange(tab.value)}
    >
      {#if tab.gone}<i class="lz"></i>{/if}{tab.label}{#if tab.count != null}<b>{int(tab.count)}</b>{/if}
    </button>
  {/each}
</div>
