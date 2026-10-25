<script>
  import { errorMessage } from '../lib/api.js'
  import { auth } from '../lib/auth.svelte.js'

  /** @type {{ mode: 'setup' | 'login' }} */
  let { mode } = $props()

  let username = $state('')
  let password = $state('')
  let busy = $state(false)
  let error = $state('')

  const setup = $derived(mode === 'setup')

  /** @param {SubmitEvent} event */
  async function submit(event) {
    event.preventDefault()
    busy = true
    error = ''
    try {
      if (setup) await auth.setup(username.trim(), password)
      else await auth.login(username.trim(), password)
    } catch (e) {
      error = errorMessage(e)
    } finally {
      busy = false
    }
  }
</script>

<svelte:head>
  <title>{setup ? 'Create your account' : 'Log in'} · YouHoard</title>
</svelte:head>

<div class="auth">
  <form class="auth-card" onsubmit={submit}>
    <h1>{setup ? 'Create your account' : 'Log in'}</h1>

    {#if error}<p class="form-error" role="alert">{error}</p>{/if}

    <div class="field">
      <label class="label" for="auth-username">Username</label>
      <input
        id="auth-username"
        class="input"
        bind:value={username}
        required
        autocomplete="username"
        autocapitalize="none"
        spellcheck="false"
      />
    </div>
    <div class="field">
      <label class="label" for="auth-password">Password</label>
      <input
        id="auth-password"
        class="input"
        type="password"
        bind:value={password}
        required
        minlength={setup ? 8 : undefined}
        autocomplete={setup ? 'new-password' : 'current-password'}
        aria-describedby={setup ? 'auth-password-hint' : undefined}
      />
      {#if setup}<span id="auth-password-hint" class="hint">At least 8 characters</span>{/if}
    </div>

    <button type="submit" class="btn primary" disabled={busy}>{setup ? 'Create account' : 'Log in'}</button>
  </form>
</div>
