<script>
  /** @import { IconName } from '../lib/icons.js' */
  import Icon from './Icon.svelte'

  /**
   * @type {{
   *   label: string,
   *   value: string,
   *   options: { value: string, label: string, icon?: IconName }[],
   *   onchange: (value: string) => void,
   *   class?: string
   * }}
   */
  let { label, value, options, onchange, class: className = '' } = $props()
</script>

<div class="seg {className}" role="group" aria-label={label}>
  {#each options as option (option.value)}
    <button
      type="button"
      aria-label={option.label}
      aria-pressed={value === option.value}
      onclick={() => onchange(option.value)}
    >
      {#if option.icon}<Icon name={option.icon} />{/if}
      <span>{option.label}</span>
    </button>
  {/each}
</div>
