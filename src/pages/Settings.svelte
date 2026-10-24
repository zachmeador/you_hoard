<script>
  /** @import { Settings, SettingsUpdate, SystemInfo } from '../lib/types' */
  import { onMount } from 'svelte'
  import { api, errorMessage } from '../lib/api.js'
  import { bytes, int, interval, parseLanguages, qualityLabel } from '../lib/format.js'
  import { Loader } from '../lib/loader.svelte.js'
  import { queue } from '../lib/queue.svelte.js'
  import { librarySettings } from '../lib/settings.svelte.js'
  import { notify } from '../lib/toasts.svelte.js'

  const IMPORT_COMMAND =
    'uv run python -m app import-tubearchivist --backup /path/to/ta_backup.zip ' +
    '--ta-media <folder inside the media dir> --ta-cache /path/to/ta/cache'

  /**
   * @typedef {{
   *   default_quality: string,
   *   subtitle_text: string,
   *   download_comments: boolean,
   *   max_concurrent_downloads: number,
   *   check_interval_hours: number
   * }} SettingsForm
   */

  /** @type {Loader<SystemInfo>} */
  const system = new Loader()
  let form = $state(/** @type {SettingsForm | null} */ (null))
  let loadError = $state('')
  let saveError = $state('')
  let saving = $state(false)
  let rescanning = $state(false)
  /** @type {number | null} */
  let rescanJob = $state(null)
  /** @type {HTMLElement | undefined} */
  let commandEl = $state()

  const options = $derived(librarySettings.options)
  const saved = $derived(librarySettings.current)
  const dirty = $derived(
    form && saved ? JSON.stringify(toPayload(form)) !== JSON.stringify(toPayload(toForm(saved))) : false
  )
  const intervals = $derived(
    form && !options.check_intervals.includes(form.check_interval_hours)
      ? [...options.check_intervals, form.check_interval_hours].sort((a, b) => a - b)
      : options.check_intervals
  )
  const diskPercent = $derived(
    system.data?.disk && system.data.disk.total > 0
      ? Math.round((system.data.disk.used / system.data.disk.total) * 100)
      : 0
  )

  /**
   * @param {Settings} s
   * @returns {SettingsForm}
   */
  function toForm(s) {
    return {
      default_quality: s.default_quality,
      subtitle_text: s.subtitle_languages.join(', '),
      download_comments: s.download_comments,
      max_concurrent_downloads: s.max_concurrent_downloads,
      check_interval_hours: s.check_interval_hours
    }
  }

  /**
   * @param {SettingsForm} f
   * @returns {SettingsUpdate}
   */
  function toPayload(f) {
    return {
      default_quality: f.default_quality,
      subtitle_languages: parseLanguages(f.subtitle_text),
      download_comments: f.download_comments,
      max_concurrent_downloads: Math.min(8, Math.max(1, Math.round(Number(f.max_concurrent_downloads) || 1))),
      check_interval_hours: Number(f.check_interval_hours)
    }
  }

  onMount(() => {
    api.settings
      .get()
      .then((s) => {
        librarySettings.set(s)
        form = toForm(s)
      })
      .catch((e) => (loadError = errorMessage(e)))
    system.run(() => api.system.get())
  })

  /** @param {SubmitEvent} event */
  async function save(event) {
    event.preventDefault()
    if (!form) return
    saving = true
    saveError = ''
    try {
      const updated = await api.settings.update(toPayload(form))
      librarySettings.set(updated)
      form = toForm(updated)
      notify.success('Settings saved')
    } catch (e) {
      saveError = errorMessage(e)
    } finally {
      saving = false
    }
  }

  async function rescan() {
    rescanning = true
    try {
      const { job_id } = await api.system.rescan()
      rescanJob = job_id
      notify.success('Library rescan queued')
      queue.refresh().catch(() => {})
    } catch (e) {
      notify.error(e)
    } finally {
      rescanning = false
    }
  }

  async function copyCommand() {
    try {
      await navigator.clipboard.writeText(IMPORT_COMMAND)
      notify.success('Command copied')
    } catch {
      if (commandEl) {
        const range = document.createRange()
        range.selectNodeContents(commandEl)
        const selection = getSelection()
        selection?.removeAllRanges()
        selection?.addRange(range)
      }
      notify.info('Clipboard access is unavailable here. The command is selected; copy it with Ctrl+C or ⌘C.')
    }
  }
</script>

<svelte:head>
  <title>Settings · YouHoard</title>
</svelte:head>

<div class="page-head">
  <h1 class="page-title">Settings</h1>
</div>

<div class="settings">
  <div class="column">
    <form class="panel stack" aria-labelledby="defaults-title" onsubmit={save}>
      <h2 id="defaults-title" class="section-title">Download defaults</h2>
      {#if form}
        <div class="fields">
          <div class="field">
            <label class="field-label" for="settings-quality">Default quality</label>
            <select id="settings-quality" bind:value={form.default_quality}>
              {#each options.qualities as q (q)}
                <option value={q}>{qualityLabel(q)}</option>
              {/each}
            </select>
          </div>
          <div class="field">
            <label class="field-label" for="settings-subtitles">Subtitle languages</label>
            <input
              id="settings-subtitles"
              bind:value={form.subtitle_text}
              placeholder="en, de"
              autocomplete="off"
              spellcheck="false"
              aria-describedby="settings-subtitles-hint"
            />
            <span id="settings-subtitles-hint" class="hint">Comma-separated language codes; empty for none.</span>
          </div>
          <div class="field">
            <label class="field-label" for="settings-concurrency">Concurrent downloads</label>
            <input
              id="settings-concurrency"
              type="number"
              min="1"
              max="8"
              step="1"
              required
              bind:value={form.max_concurrent_downloads}
            />
          </div>
          <div class="field">
            <label class="field-label" for="settings-interval">Default check interval</label>
            <select id="settings-interval" bind:value={form.check_interval_hours} aria-describedby="settings-interval-hint">
              {#each intervals as hours (hours)}
                <option value={hours}>{interval(hours)}</option>
              {/each}
            </select>
            <span id="settings-interval-hint" class="hint">Pre-selected for new subscriptions.</span>
          </div>
        </div>
        <label class="check">
          <input type="checkbox" bind:checked={form.download_comments} />
          Download comments
        </label>
        {#if saveError}<p class="form-error" role="alert">{saveError}</p>{/if}
        <div class="form-actions">
          {#if dirty}<span class="hint">Unsaved changes</span>{/if}
          <button type="submit" class="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save settings'}</button>
        </div>
      {:else if loadError}
        <p class="form-error" role="alert">{loadError}</p>
      {:else}
        <p class="loading-line"><span class="spinner"></span> Loading settings…</p>
      {/if}
    </form>

    <section class="panel stack" aria-labelledby="maintenance-title">
      <h2 id="maintenance-title" class="section-title">Library rescan</h2>
      <p class="small muted">
        Re-scan the media folder to pick up files that were added, moved or deleted outside YouHoard.
      </p>
      <div class="cluster">
        <button type="button" class="btn btn-secondary" disabled={rescanning} onclick={rescan}>
          {rescanning ? 'Starting…' : 'Rescan library'}
        </button>
        {#if rescanJob}
          <span class="small ok-text">Rescan queued (job #{rescanJob}).</span>
          <a class="small" href="#/queue?kind=scan">View it in the queue</a>
        {/if}
      </div>
    </section>

    <section class="panel stack" aria-labelledby="import-title">
      <h2 id="import-title" class="section-title">Import from TubeArchivist</h2>
      <p class="small">
        Imports run from the command line on the machine that hosts YouHoard. Put TubeArchivist's media folder
        inside the YouHoard media folder{system.data ? ` (${system.data.media_dir})` : ''}, then run:
      </p>
      <div class="command">
        <pre><code bind:this={commandEl}>{IMPORT_COMMAND}</code></pre>
        <button type="button" class="btn btn-secondary btn-sm" onclick={copyCommand}>Copy command</button>
      </div>
      <ul class="flags small">
        <li><code>--backup</code> the backup zip exported from TubeArchivist</li>
        <li><code>--ta-media</code> TubeArchivist's media folder, inside the YouHoard media folder</li>
        <li><code>--ta-cache</code> TubeArchivist's cache folder</li>
        <li>On its own the command is a dry run that only reports what it would do.</li>
        <li>Add <code>--apply</code> to import, and <code>--organize</code> to rename files into the YouHoard layout.</li>
      </ul>
    </section>
  </div>

  <section class="panel stack" aria-labelledby="system-title">
    <h2 id="system-title" class="section-title">System</h2>
    {#if system.data}
      {@const sys = system.data}
      <dl class="kv">
        <dt>YouHoard</dt>
        <dd>{sys.version}</dd>
        <dt>yt-dlp</dt>
        <dd>{sys.yt_dlp}</dd>
        <dt>ffmpeg</dt>
        <dd>
          {#if sys.ffmpeg}{sys.ffmpeg}{:else}<span class="warn-text">Not found (needed to merge video and audio)</span>{/if}
        </dd>
        <dt>JS runtime</dt>
        <dd>
          {#if sys.js_runtime}{sys.js_runtime}{:else}<span class="warn-text">Not found: YouTube downloads are degraded</span>{/if}
        </dd>
        <dt>Cookies</dt>
        <dd>{sys.cookies ? 'Loaded' : 'None'}</dd>
        <dt>Media folder</dt>
        <dd class="path">{sys.media_dir}</dd>
      </dl>

      {#if sys.disk}
        <div class="disk">
          <div class="disk-label small">
            <span>Disk</span>
            <span class="muted">{bytes(sys.disk.used)} of {bytes(sys.disk.total)} used · {bytes(sys.disk.free)} free</span>
          </div>
          <div
            class="bar"
            class:full={diskPercent >= 90}
            role="meter"
            aria-label="Disk usage"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={diskPercent}
            aria-valuetext="{diskPercent}% used"
          >
            <span style:width="{diskPercent}%"></span>
          </div>
        </div>
      {/if}

      <dl class="stat-grid">
        <div><dt>Videos</dt><dd>{int(sys.library.videos)}</dd></div>
        <div><dt>Archived</dt><dd>{int(sys.library.archived)}</dd></div>
        <div><dt>Archive size</dt><dd>{bytes(sys.library.archived_size)}</dd></div>
        <div><dt>Channels</dt><dd>{int(sys.library.channels)}</dd></div>
        <div><dt>Subscriptions</dt><dd>{int(sys.library.subscriptions)}</dd></div>
        <div><dt>Gone from YouTube</dt><dd>{int(sys.library.unavailable)}</dd></div>
      </dl>

      <p class="dots small">
        <span class="muted">Jobs</span>
        <span>{int(sys.queue.running)} running</span>
        <span>{int(sys.queue.queued)} queued</span>
        <span class:error-text={sys.queue.failed > 0}>{int(sys.queue.failed)} failed</span>
      </p>
    {:else if system.error}
      <p class="form-error" role="alert">{system.error}</p>
    {:else}
      <p class="loading-line"><span class="spinner"></span> Loading…</p>
    {/if}
  </section>
</div>

<style>
  .settings {
    display: grid;
    grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
    gap: var(--space-4);
    align-items: start;
  }

  .column {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    min-width: 0;
  }

  .fields {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: var(--space-3);
  }

  .command {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
  }

  .command pre {
    flex: 1;
    min-width: 0;
    padding: var(--space-2) var(--space-3);
    background: var(--background);
    border: 1px solid var(--border-dark);
    border-radius: var(--radius);
    color: var(--terminal-green);
    font-size: 0.75rem;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .flags {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    color: var(--text-secondary);
  }

  .flags code {
    color: var(--terminal-green);
  }

  .path {
    font-size: 0.75rem;
  }

  .disk {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .disk-label {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: var(--space-2);
  }

  .bar {
    height: 8px;
  }

  .bar.full > span {
    background: linear-gradient(90deg, var(--warning), var(--error));
  }

  .stat-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--space-2);
  }

  .stat-grid div {
    padding: var(--space-2);
    background: var(--background);
    border: 1px solid var(--border-dark);
    border-radius: var(--radius);
  }

  .stat-grid dt {
    font-size: 0.6875rem;
    color: var(--text-muted);
  }

  .stat-grid dd {
    font-size: 1rem;
    font-weight: 700;
    color: var(--terminal-green);
  }

  @media (max-width: 900px) {
    .settings {
      grid-template-columns: minmax(0, 1fr);
    }
  }

  @media (max-width: 480px) {
    .stat-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
</style>
