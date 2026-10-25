<script>
  /**
   * @type {{
   *   label: string,
   *   value: string | number,
   *   options: { value: string | number, label: string }[],
   *   onchange: (value: string) => void,
   *   bare?: boolean,
   *   name?: string,
   *   class?: string
   * }}
   */
  let { label, value, options, onchange, bare = false, name, class: className = '' } = $props()
</script>

<label class="sel {className}" class:bare>
  {#if !bare}<span>{label}</span>{/if}
  <select aria-label={name ?? label} {value} onchange={(event) => onchange(event.currentTarget.value)}>
    {#each options as option (option.value)}
      <option value={option.value}>{option.label}</option>
    {/each}
  </select>
</label>
