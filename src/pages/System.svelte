<script>
  /** @import { Channel, Job, Settings } from '../lib/types' */
  import { onMount, untrack } from 'svelte'
  import { api } from '../lib/api.js'
  import { copyText } from '../lib/clipboard.js'
  import { confirmAction } from '../lib/confirm.svelte.js'
  import { bytes, int, interval, parseTime, qualityLabel, rel } from '../lib/format.js'
  import { jobResult } from '../lib/jobs.js'
  import { Loader } from '../lib/loader.svelte.js'
  import { poll } from '../lib/poll.js'
  import { href } from '../lib/router.svelte.js'
  import { librarySettings } from '../lib/settings.svelte.js'
  import { system } from '../lib/system.svelte.js'
  import { notify } from '../lib/toasts.svelte.js'
  import { clock } from '../lib/ui.svelte.js'
  import FieldSelect from '../components/FieldSelect.svelte'
  import Icon from '../components/Icon.svelte'
  import LanguagePicker from '../components/LanguagePicker.svelte'

  /** @typedef {Omit<Settings, 'options'>} Form */

  /** @type {Form | null} */
  let form = $state(null)
  /** @type {Form | null} */
  let saved = $state(null)
  let saving = $state(false)
  /** @type {Loader<{ items: Channel[] }>} */
  const largest = new Loader()
  /** @type {Loader<{ items: Job[] }>} */
  const scans = new Loader()
  let botChecks = $state(0)

  const info = $derived(system.info)
  const dirty = $derived(JSON.stringify(form) !== JSON.stringify(saved))
  const options = $derived(librarySettings.options)
  const intervals = $derived(options.check_intervals.map((h) => ({ value: h, label: interval(h) })))
  const trashChoices = $derived.by(() =>
    [...new Set([...options.trash_days, form?.trash_days ?? 0])]
      .sort((a, b) => a - b)
      .map((days) => ({ value: days, label: days > 0 ? `Keep ${days} ${days === 1 ? 'day' : 'days'} in the trash` : 'Delete right away' }))
  )
  // The newest scan job, whatever its status (the list sorts by status first).
  const lastScan = $derived(
    (scans.data?.items ?? []).reduce((/** @type {Job | null} */ newest, job) => (!newest || job.id > newest.id ? job : newest), null)
  )
  const refused = $derived(lastScan?.status === 'failed' && /^Rescan stopped/.test(lastScan.error ?? ''))
  const used = $derived(info?.disk ? Math.round((info.disk.used / info.disk.total) * 100) : 0)
  const ageDays = $derived.by(() => {
    const m = /^(\d{4})\.(\d{1,2})\.(\d{1,2})/.exec(info?.yt_dlp ?? '')
    return m ? Math.floor((clock.now - new Date(+m[1], +m[2] - 1, +m[3]).getTime()) / 86400000) : null
  })
  const top = $derived((largest.data?.items ?? []).filter((c) => c.archived_size > 0))
  const topMax = $derived(top[0]?.archived_size ?? 1)

  /** @param {Settings} settings @returns {Form} */
  function formOf(settings) {
    const { options: _options, ...rest } = settings
    return { ...rest, subtitle_languages: [...rest.subtitle_languages], audio_languages: [...rest.audio_languages] }
  }

  $effect(() => {
    const current = librarySettings.current
    if (current && !dirty) untrack(() => {
      saved = formOf(current)
      form = formOf(current)
    })
  })

  onMount(() => {
    librarySettings.load().catch((e) => notify.error(e))
    system.refresh().catch(() => {})
    largest.run(() => api.channels.list({ sort: 'size', per_page: 8 }))
    loadScans()
    api.jobs
      .list({ kind: 'download', status: 'failed', limit: 200 })
      .then((res) => {
        const since = Date.now() - 86400000
        botChecks = res.items.filter((j) => /bot/i.test(j.error ?? '') && (parseTime(j.finished_at)?.getTime() ?? 0) > since).length
      })
      .catch(() => {})
    return poll(
      async () => {
        await system.refresh()
        loadScans()
      },
      15_000,
      { immediate: false }
    )
  })

  const loadScans = () => scans.run(() => api.jobs.list({ kind: 'scan', limit: 20 }), { quiet: !!scans.data })

  async function save() {
    if (!form) return
    saving = true
    try {
      const updated = await api.settings.update({
        ...form,
        max_concurrent_downloads: Math.min(8, Math.max(1, form.max_concurrent_downloads))
      })
      librarySettings.set(updated)
      saved = formOf(updated)
      form = formOf(updated)
      notify.success('Settings saved')
    } catch (e) {
      notify.error(e)
    } finally {
      saving = false
    }
  }

  /** @param {number} step */
  function bump(step) {
    if (form) form.max_concurrent_downloads = Math.min(8, Math.max(1, form.max_concurrent_downloads + step))
  }

  /** @param {boolean} [force] */
  async function rescan(force = false) {
    if (force) {
      const ok = await confirmAction({
        title: 'Rescan anyway?',
        message:
          "Videos whose files aren't in the media folder get marked missing. No files are deleted, and a later " +
          'rescan links anything that comes back.',
        confirmLabel: 'Rescan anyway',
        danger: true
      })
      if (!ok) return
    }
    try {
      const { job_id } = await api.system.rescan(force)
      notify.success(`Library rescan queued (job #${job_id})`)
      loadScans()
    } catch (e) {
      notify.error(e)
    }
  }

  const command = $derived(
    `uv run python -m app import-tubearchivist \\\n  --backup /path/to/ta/cache/backup/ta_backup-….zip \\\n  --ta-media ${info?.media_dir ?? '/media'}/tubearchivist`
  )

  async function copyCommand() {
    if (await copyText(command)) notify.success('Command copied')
  }
</script>

<svelte:head>
  <title>System · YouHoard</title>
</svelte:head>

<header class="ph"><h1>System</h1></header>

<div class="sys">
  <div>
    <section aria-labelledby="def-h">
      <h2 class="label" id="def-h">Settings</h2>
      {#if form}
        {@const f = form}
        <form
          onsubmit={(event) => {
            event.preventDefault()
            save()
          }}
        >
          <div class="form-grid">
            <FieldSelect
              label="Default quality"
              value={f.default_quality}
              options={options.qualities.map((q) => ({ value: q, label: qualityLabel(q) }))}
              onchange={(value) => {
                f.default_quality = value
              }}
            />
            <FieldSelect
              label="Default check interval"
              value={f.check_interval_hours}
              options={intervals.some((o) => o.value === f.check_interval_hours)
                ? intervals
                : [...intervals, { value: f.check_interval_hours, label: interval(f.check_interval_hours) }]}
              hint="For new subscriptions"
              onchange={(value) => {
                f.check_interval_hours = Number(value)
              }}
            />
            <div class="field">
              <span class="label">Subtitle languages</span>
              <LanguagePicker
                label="Subtitle languages"
                value={f.subtitle_languages}
                options={options.languages}
                all
                onchange={(list) => {
                  f.subtitle_languages = list
                }}
              />
            </div>
            <div class="field">
              <span class="label">Extra audio languages</span>
              <LanguagePicker
                label="Extra audio languages"
                value={f.audio_languages}
                options={options.languages}
                onchange={(list) => {
                  f.audio_languages = list
                }}
              />
            </div>
            <div class="field">
              <span class="label">Concurrent downloads</span>
              <div style="display: flex; align-items: center; gap: 10px">
                <span class="stepper">
                  <button type="button" aria-label="Fewer concurrent downloads" onclick={() => bump(-1)}>−</button>
                  <output aria-label="Concurrent downloads">{f.max_concurrent_downloads}</output>
                  <button type="button" aria-label="More concurrent downloads" onclick={() => bump(1)}>+</button>
                </span>
                <span class="hint">Applies immediately</span>
              </div>
            </div>
            <FieldSelect
              label="Removed files"
              value={f.trash_days}
              options={trashChoices}
              hint="Restorable from the video's page until then"
              onchange={(value) => {
                f.trash_days = Number(value)
              }}
            />
          </div>
          <div class="toggles">
            <div class="toggle-row">
              <input type="checkbox" class="sw" id="s-auto" bind:checked={f.auto_captions} />
              <label for="s-auto">Fill in missing subtitles with auto captions</label>
            </div>
            <div class="toggle-row">
              <input type="checkbox" class="sw" id="s-comments" bind:checked={f.download_comments} />
              <label for="s-comments">Download comments into the .info.json</label>
            </div>
            <div class="toggle-row">
              <input type="checkbox" class="sw" id="s-chat" bind:checked={f.live_chat} />
              <label for="s-chat">Save live chat replays</label>
            </div>
            <div class="toggle-row">
              <input type="checkbox" class="sw" id="s-sponsor" bind:checked={f.sponsorblock} />
              <label for="s-sponsor">Save SponsorBlock segments as markers</label>
            </div>
          </div>
          <div class="form-foot">
            <button type="submit" class="btn primary" disabled={saving}>Save settings</button>
            <span class="dirty" class:on={dirty}>Unsaved changes</span>
          </div>
        </form>
      {/if}
    </section>

    <section aria-labelledby="scan-h">
      <h2 class="label" id="scan-h">
        Library rescan
        <span class="r">
          <button type="button" class="btn sm" onclick={() => rescan()}><Icon name="refresh" />Rescan now</button>
        </span>
      </h2>
      {#if lastScan?.status === 'queued' || lastScan?.status === 'running'}
        <p class="p">Rescanning…</p>
      {:else if lastScan?.status === 'failed'}
        <p class="p">{rel(lastScan.finished_at, clock.now)}: {lastScan.error}</p>
        {#if refused}
          <button type="button" class="btn danger sm" onclick={() => rescan(true)}>Rescan anyway</button>
        {/if}
      {:else if lastScan}
        <p class="p">Last run {rel(lastScan.finished_at, clock.now)}: {jobResult(lastScan)}</p>
      {/if}
    </section>

    <section aria-labelledby="ta-h">
      <h2 class="label" id="ta-h">Import from TubeArchivist</h2>
      <p class="p" style="margin-bottom: 10px">
        Run on the host. Without <code class="mono">--apply</code> it only reports what it would do.
      </p>
      <div class="cmd">
        <pre>{command}</pre>
        <button type="button" class="btn sm" onclick={copyCommand}><Icon name="copy" />Copy</button>
      </div>
      <dl class="flags">
        <dt><code>--apply</code></dt>
        <dd>Import channels, videos, watched state, subscriptions and the ignore list</dd>
        <dt><code>--organize</code></dt>
        <dd>With <code>--apply</code>, rename files into YouHoard's layout</dd>
        <dt><code>--ta-cache</code></dt>
        <dd>When the cache folder isn't next to the backup</dd>
        <dt><code>--es-url</code></dt>
        <dd>Read a running Elasticsearch instead (with <code>TA_ES_PASSWORD</code>)</dd>
      </dl>
    </section>
  </div>

  <div>
    {#if info}
      <section aria-labelledby="health-h">
        <h2 class="label" id="health-h">Health</h2>
        <ul class="health">
          <li><span class="mk"></span><span class="k">YouHoard</span><span class="v">{info.version}</span><span class="x"></span></li>
          <li>
            <span class="mk" class:warn={ageDays != null && ageDays > 90}></span>
            <span class="k">yt-dlp</span>
            <span class="v">{info.yt_dlp}</span>
            <span class="x">{ageDays != null ? `${int(ageDays)} days old` : ''}</span>
          </li>
          <li>
            <span class="mk" class:warn={!info.js_runtime}></span>
            <span class="k">JS runtime</span>
            <span class="v">
              {#if info.js_runtime}{info.js_runtime}{:else}None found<small>YouTube needs a JavaScript runtime such as Deno.</small>{/if}
            </span>
            <span class="x"></span>
          </li>
          <li>
            <span class="mk" class:warn={!info.ffmpeg}></span>
            <span class="k">ffmpeg</span>
            <span class="v">{info.ffmpeg ?? 'Missing'}</span>
            <span class="x"></span>
          </li>
          <li>
            <span class="mk" class:warn={!info.cookies && botChecks > 0}></span>
            <span class="k">Cookies</span>
            <span class="v">
              {#if info.cookies}Loaded
              {:else}None loaded{#if botChecks > 0}<small>
                  {botChecks} bot {botChecks === 1 ? 'check' : 'checks'} in the last 24 h. Set YTDLP_COOKIE_FILE if they continue.
                </small>{/if}{/if}
            </span>
            <span class="x"></span>
          </li>
          <li>
            <span class="mk"></span>
            <span class="k">Media folder</span>
            <span class="v"><span class="mono">{info.media_dir}</span></span>
            <span class="x"></span>
          </li>
        </ul>
      </section>

      <section aria-labelledby="disk-h">
        <h2 class="label" id="disk-h">
          Storage
          {#if info.disk}
            <span class="r muted usedpct">{used}% of {bytes(info.disk.total)} used</span>
          {/if}
        </h2>
        {#if info.disk}
          {@const other = Math.max(0, info.disk.used - info.library.archived_size)}
          <div class="disk-big">
            <div
              class="hbar"
              role="img"
              aria-label="Archive {bytes(info.library.archived_size)}, other {bytes(other)}, free {bytes(info.disk.free)}"
            >
              <i style:flex={info.library.archived_size}></i>
              <i class="d" style:flex={other} style:background-image="var(--hatch)"></i>
              <i class="n" style:flex={info.disk.free} style:background="var(--bg-2)" style:background-image="none"></i>
            </div>
            <div class="nums">
              <div><b>{bytes(info.library.archived_size)}</b><span>Archive</span></div>
              <div class="o"><b>{bytes(other)}</b><span>Other files</span></div>
              <div class="fr"><b>{bytes(info.disk.free)}</b><span>Free</span></div>
            </div>
          </div>
        {:else}
          <p class="p">Disk usage is unavailable for the media folder.</p>
        {/if}
        {#if info.trash.videos > 0}
          <p class="p trash-line">
            {int(info.trash.videos)} removed {info.trash.videos === 1 ? 'video' : 'videos'} in the trash, {bytes(info.trash.size)}
          </p>
        {/if}
      </section>

      <section aria-labelledby="lib-h">
        <h2 class="label" id="lib-h">Library</h2>
        <dl class="ledger">
          <div><dt>Videos</dt><dd>{int(info.library.videos)}</dd></div>
          <div><dt>Archived</dt><dd>{int(info.library.archived)}</dd></div>
          <div><dt>Channels</dt><dd>{int(info.library.channels)}</dd></div>
          <div><dt>Subscriptions</dt><dd>{int(info.library.subscriptions)}</dd></div>
          <div class="gone"><dt><i class="lz"></i> Gone from YouTube</dt><dd>{int(info.library.unavailable)}</dd></div>
        </dl>
      </section>
    {/if}

    {#if top.length}
      <section aria-labelledby="big-h">
        <h2 class="label" id="big-h">Largest channels</h2>
        <ul class="bars">
          {#each top as channel (channel.id)}
            <li>
              <a class="nm" href={href('/library', { channel: channel.id })}>{channel.name}</a>
              <span class="b"><i style:width="{(channel.archived_size / topMax) * 100}%"></i></span>
              <span class="v">{bytes(channel.archived_size)}</span>
            </li>
          {/each}
        </ul>
      </section>
    {/if}
  </div>
</div>
