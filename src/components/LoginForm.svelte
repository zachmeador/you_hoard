<script>
  import { authApi } from '../stores/auth.js'
  
  let username = ''
  let password = ''
  let submitting = false
  let error = ''

  async function handleSubmit() {
    if (!username.trim() || !password.trim()) return

    submitting = true
    error = ''
    
    const result = await authApi.login(username.trim(), password)
    
    if (!result.success) {
      error = result.error
    }
    // If successful, auth store will update and App.svelte will show the main app
    
    submitting = false
  }
</script>

<div class="login-container">
  <div class="login-card">
    <div class="login-header">
      <h1>You Hoard</h1>
      <p>Please log in to continue</p>
    </div>
    
    <form on:submit|preventDefault={handleSubmit}>
      {#if error}
        <div class="error-message">
          {error}
        </div>
      {/if}
      
      <div class="form-group">
        <label for="username">Username</label>
        <input 
          type="text" 
          id="username" 
          bind:value={username}
          placeholder="Enter username" 
          required
          disabled={submitting}
          autocomplete="username"
        >
      </div>
      
      <div class="form-group">
        <label for="password">Password</label>
        <input 
          type="password" 
          id="password" 
          bind:value={password}
          placeholder="Enter password" 
          required
          disabled={submitting}
          autocomplete="current-password"
        >
      </div>
      
      <button type="submit" class="btn btn-primary btn-lg" disabled={submitting} style="width: 100%;">
        {#if submitting}
          <span class="spinner"></span>Logging in...
        {:else}
          Login
        {/if}
      </button>
    </form>
  </div>
</div>

<style>
  .login-container {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    background: var(--background);
    padding: var(--space-4);
  }
  
  .login-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-lg), var(--glow-primary);
    padding: var(--space-8);
    width: 100%;
    max-width: 400px;
  }
  
  .login-header {
    text-align: center;
    margin-bottom: var(--space-8);
  }
  
  .login-header h1 {
    font-size: 2rem;
    font-weight: 700;
    color: var(--terminal-green);
    font-family: var(--font-mono);
    text-shadow: 0 0 10px var(--primary-glow);
    margin-bottom: var(--space-2);
  }
  
  .login-header p {
    color: var(--text-secondary);
    font-family: var(--font-mono);
  }
  
  .error-message {
    background: rgba(255, 51, 68, 0.2);
    color: var(--error);
    border: 1px solid rgba(255, 51, 68, 0.3);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius);
    margin-bottom: var(--space-4);
    font-size: 0.875rem;
    text-align: center;
  }
  
  .form-group {
    margin-bottom: var(--space-4);
  }
  
  .form-group:last-of-type {
    margin-bottom: var(--space-6);
  }
</style> 