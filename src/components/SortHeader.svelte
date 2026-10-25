<script>
  import Icon from './Icon.svelte'

  /** @type {{ key: string, label: string, sort: string, order: string, onsort: (key: string) => void, class?: string }} */
  let { key, label, sort, order, onsort, class: className = '' } = $props()
</script>

<th class={className} aria-sort={sort === key ? (order === 'asc' ? 'ascending' : 'descending') : undefined}>
  <button type="button" onclick={() => onsort(key)}>
    {label}{#if sort === key}<Icon name={order === 'asc' ? 'up' : 'down'} />{/if}
  </button>
</th>
