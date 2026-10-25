<script>
  import Icon from './Icon.svelte'

  /** @type {{ label: string, placeholder: string, value: string, kbd?: string, class?: string }} */
  let { label, placeholder, value = $bindable(), kbd, class: className = '' } = $props()
</script>

<label class="search {className}">
  <Icon name="search" />
  <input type="search" {placeholder} aria-label={label} autocomplete="off" bind:value />
  {#if kbd}<kbd aria-hidden="true">{kbd}</kbd>{/if}
</label>
