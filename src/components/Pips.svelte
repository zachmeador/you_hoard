<script>
  /** @type {{ n: number }} */
  let { n } = $props()
</script>

<span class="pips" aria-hidden="true">
  {#each [1, 2, 3] as i (i)}<i class:on={i <= n}></i>{/each}
</span>
