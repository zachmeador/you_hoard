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
    <p class="brand">YouHoard</p>
    <h1>{setup ? 'Create your account' : 'Log in'}</h1>
    {#if setup}
      <p class="muted small">First run: choose the username and password that protect this archive.</p>
    {/if}

    {#if error}<p class="form-error" role="alert">{error}</p>{/if}

    <div class="field">
      <label class="field-label" for="auth-username">Username</label>
      <input
        id="auth-username"
        bind:value={username}
        required
        autocomplete="username"
        autocapitalize="none"
        spellcheck="false"
      />
    </div>
    <div class="field">
      <label class="field-label" for="auth-password">Password</label>
      <input
        id="auth-password"
        type="password"
        bind:value={password}
        required
        minlength={setup ? 8 : undefined}
        autocomplete={setup ? 'new-password' : 'current-password'}
        aria-describedby={setup ? 'auth-password-hint' : undefined}
      />
      {#if setup}<span id="auth-password-hint" class="hint">At least 8 characters.</span>{/if}
    </div>

    <button type="submit" class="btn btn-primary submit" disabled={busy}>
      {#if busy}<span class="spinner"></span>{/if}
      {setup ? 'Create account' : 'Log in'}
    </button>
  </form>
</div>

<style>
  .auth {
    display: grid;
    place-items: center;
    min-height: 100vh;
    padding: var(--space-4);
  }

  .auth-card {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    width: 100%;
    max-width: 380px;
    padding: var(--space-8) var(--space-6);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-lg), var(--glow-primary);
  }

  .brand {
    font-size: 2rem;
    font-weight: 700;
    text-align: center;
    color: var(--terminal-green);
    text-shadow: 0 0 10px var(--primary-glow);
  }

  h1 {
    font-size: 1.1rem;
    text-align: center;
    color: var(--text-secondary);
  }

  .submit {
    margin-top: var(--space-2);
    padding: var(--space-3);
    font-size: 0.9rem;
  }
</style>
