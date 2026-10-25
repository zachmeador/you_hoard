<script>
  /** @import { Snippet } from 'svelte' */
  import SelectField from './SelectField.svelte'

  /**
   * @type {{
   *   label: string,
   *   value: string | number,
   *   options: { value: string | number, label: string }[],
   *   onchange: (value: string) => void,
   *   hint?: string,
   *   children?: Snippet
   * }}
   */
  let { label, value, options, onchange, hint, children } = $props()
</script>

<div class="field">
  <span class="label">{label}</span>
  <SelectField {label} bare {value} {options} {onchange} />
  {#if hint}<span class="hint">{hint}</span>{/if}
  {@render children?.()}
</div>
