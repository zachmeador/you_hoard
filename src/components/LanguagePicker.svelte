<script>
  /** @import { Language } from '../lib/types' */
  import { ALL_UPLOADED, languageName } from '../lib/format.js'
  import Icon from './Icon.svelte'

  /** @type {{ label: string, value: string[], options: Language[], all?: boolean, onchange: (value: string[]) => void }} */
  let { label, value, options, all = false, onchange } = $props()

  const available = $derived([...(all ? [ALL_UPLOADED] : []), ...options].filter((o) => !value.includes(o.code)))

  /** @param {string} code @param {string} name */
  const text = (code, name) => (code === ALL_UPLOADED.code ? name : `${name} · ${code}`)

  /** @param {string} code */
  function add(code) {
    if (code && !value.includes(code)) onchange([...value, code])
  }

  /** @param {string} code */
  function remove(code) {
    onchange(value.filter((c) => c !== code))
  }
</script>

<div class="langs" role="group" aria-label={label}>
  {#if value.length}
    <ul class="chips">
      {#each value as code (code)}
        {@const name = languageName(code, options)}
        <li>
          <span>{text(code, name)}</span>
          <button type="button" aria-label="Remove {name}" onclick={() => remove(code)}><Icon name="x" /></button>
        </li>
      {/each}
    </ul>
  {/if}
  {#if available.length}
    <label class="sel">
      <select
        aria-label="Add to {label}"
        value=""
        onchange={(event) => {
          add(event.currentTarget.value)
          event.currentTarget.value = ''
        }}
      >
        <option value="">Add language…</option>
        {#each available as option (option.code)}
          <option value={option.code}>{text(option.code, option.name)}</option>
        {/each}
      </select>
    </label>
  {/if}
</div>
