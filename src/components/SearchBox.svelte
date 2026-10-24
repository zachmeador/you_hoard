<script>
  import { untrack } from 'svelte'

  /** @type {{ value: string, label: string, placeholder?: string, onsearch: (query: string) => void }} */
  let { value, label, placeholder = '', onsearch } = $props()

  const id = $props.id()
  let text = $state(untrack(() => value))
  /** @type {ReturnType<typeof setTimeout> | undefined} */
  let timer

  $effect(() => {
    const external = value
    untrack(() => {
      if (external !== text.trim()) text = external
    })
  })

  $effect(() => () => clearTimeout(timer))

  function oninput() {
    clearTimeout(timer)
    timer = setTimeout(() => onsearch(text.trim()), 300)
  }

  /** @param {KeyboardEvent} event */
  function onkeydown(event) {
    if (event.key !== 'Enter') return
    event.preventDefault()
    clearTimeout(timer)
    onsearch(text.trim())
  }
</script>

<label class="sr-only" for={id}>{label}</label>
<input {id} class="search" type="search" autocomplete="off" {placeholder} bind:value={text} {oninput} {onkeydown} />
