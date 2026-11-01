# YouHoard design

A single-user YouTube archive: follow channels and playlists, save individual videos, browse and play the archive in the browser, and import an existing TubeArchivist library. One process, SQLite, yt-dlp and ffmpeg. No search engine, broker or YouTube API key.

## Principles

1. **The files outlive the app.** Every archived video sits next to a readable `.info.json`, thumbnail and subtitles, under human-readable names. Losing the database loses app state (subscriptions, queue history, watched marks), not the archive. TubeArchivist kept metadata only in Elasticsearch; YouHoard does not repeat that.
2. **SQLite is the index.** It is versioned with migrations and can be rebuilt from the files with a library rescan.
3. **Durable facts and transient work are separate.** A video row records what is true (archived file, removed by the user, gone from YouTube). Queued, downloading and failed come from the jobs table.
4. **Subscriptions keep an inventory.** A check lists what a channel or playlist contains; a download policy decides what to archive. Nothing is downloaded by surprise.
5. **yt-dlp is the only YouTube boundary** (`app/youtube.py`). Tests replace it with a fake.
6. **The app can say why.** Each job records why it's where it is, and each decision goes in the `events` table, so a question about what the app did has an answer in the app rather than in its logs.

## Process

`main.py` builds the FastAPI app. On startup it applies migrations, then starts the `JobRunner` (`app/jobs.py`):

- download workers (count from the `max_concurrent_downloads` setting, adjustable at runtime),
- one general worker for subscription checks and library scans,
- a scheduler tick (every 30 s) that queues checks for subscriptions whose `next_check_at` has passed.

Run one process. On shutdown, running downloads are aborted at the next progress update and return to the queue; yt-dlp resumes their partial files on the next start.

## Library layout

```text
<MEDIA_DIR>/
  <Channel name> [<channel id>]/
    channel.jpg, banner.jpg                        # channel art, for subscribed channels
    <YYYY-MM-DD> <Title> [<video id>].mp4          # or .mkv/.webm; extra audio languages as tracks
    <YYYY-MM-DD> <Title> [<video id>].info.json    # slimmed yt-dlp metadata (see below)
    <YYYY-MM-DD> <Title> [<video id>].jpg
    <YYYY-MM-DD> <Title> [<video id>].en.vtt       # one per saved subtitle language
    <YYYY-MM-DD> <Title> [<video id>].live_chat.json   # stream chat replay, when kept
  .youhoard/incomplete/<video id>/                 # in-progress downloads
  .youhoard/trash/<removed at> <video id>/         # removed files and trashed.json, until they expire
```

- The `[id]` suffix is yt-dlp's convention; TubeArchivist's import and Jellyfin's YouTube metadata plugin key on it.
- Names are fixed when a file is first archived. A later title change on YouTube does not rename anything; channel folders are found by their `[channel id]` suffix.
- Sidecars share the media file's basename, so `videos.media_path` is the only path stored. Files imported from TubeArchivist in place (`<channel id>/<video id>.mp4`, `<video id>.en.vtt`) follow the same rule.
- Downloads complete in `.youhoard/incomplete` and are moved into place on the same filesystem, so media servers never see partial files.
- Every served or removed path is resolved inside `MEDIA_DIR`.
- Removing a video's files moves the media and its sidecars into a trash entry (`app/trash.py`), with a `trashed.json` manifest of where they came from and when they expire (`trash_days`, default 30; 0 deletes right away). A restore moves them back and refuses to overwrite anything. The scheduler deletes expired entries hourly, touching only the files an entry's manifest names. Rescans skip hidden folders, so they never pick files out of the trash.
- Nothing deletes a folder that still has files in it: emptied folders are removed with `rmdir`, and the only recursive delete is a download's own `.youhoard/incomplete/<video id>` folder.
- The `.info.json` holds:
  - yt-dlp's metadata without expiring URLs or format tables;
  - chapters, the most-replayed `heatmap`, and `comments` when kept;
  - `sponsorblock_chapters` when SponsorBlock is on;
  - a `_youhoard` block recording each subtitle track's source (uploaded, auto or translated) and the file's audio languages, so a rescan can rebuild them.

## Data model

Migrations live in `app/migrations/NNN_name.sql` and are tracked with `PRAGMA user_version`. Rules derived from the tables live as views in `app/views.sql`, rebuilt at every start, so changing a rule needs no migration. Timestamps are UTC ISO 8601 strings (`2026-10-24T18:00:00Z`).

| Table | Purpose |
| --- | --- |
| `channels` | YouTube uploaders (`youtube_id` = `UC…`), with verified flag and avatar/banner paths. |
| `videos` | One row per video the library knows. `media_path` (relative to `MEDIA_DIR`) is set when archived. `deleted_at` marks local files removed by the user: never downloaded automatically again. `unavailable_at` records that YouTube reported the video gone. `lost_at` records that a rescan couldn't find its file. `watched_at`. `channel_id` may be null until metadata is known. Also `published_at` (with time when known), availability, age limit, comment count, and the archived file's fps, codecs, dynamic range, audio languages and subtitle tracks. |
| `subscriptions` | A followed channel or playlist with its `download_policy`, content types (channel tabs), download-option overrides (null means the library default) and `next_check_at`. |
| `source_entries` | Inventory: every video a subscription's source has listed, with position, `baseline` flag, `removed_at`, view count and uploader. Joined to `videos` by YouTube ID. |
| `jobs` | `download`, `check` and `scan` work. Only `app/jobs.py` writes this table, and every status change goes through `JobRunner._move`, checked against `MOVES`. Partial unique indexes allow one active job per video or subscription. `origin` says who asked for it (`user`, `policy` or `schedule`), `reason` why it's in its current status, and `refusals` how often YouTube has refused it. `run_after` is its own retry or premiere wait and nothing else. `via_subscription_id` is the subscription a download came through. `options` is input, `result` output. Ids are never reused, because `events` outlives the rows. |
| `events` | The append-only record of what happened: job moves, pauses on YouTube, subscriptions switched off and on, starts and stops. Each row says who did it (`owner`, `app` or `cli`). Only `app/events.py` writes it, and it logs the same line. Ids are plain integers rather than foreign keys, so the record outlives what it describes. |
| `youtube_pause` | One row: when the pause ends, what caused it, what YouTube said, and the run of refusals. Only `app/gate.py` writes it. |
| `settings` | Runtime settings as JSON values: library download defaults (quality, subtitle languages, auto captions, comments, audio languages, live chat, SponsorBlock), concurrency, default check interval, days removed files stay in the trash. |
| `users`, `sessions` | One account; sessions store a SHA-256 of the token. |

A video's status is derived (`video_status` in `app/views.sql`): `archived` (has a file) → `downloading` / `queued` (latest download job) → `deleted` → `failed` → `missing` (known, not archived, nothing pending). While that job is queued, paused or running, videos and inventory entries also carry it as `job` (state, reason, `waiting_on`, `waits_until`, attempts, error), which tells a paused or waiting video from one that is up next.

A job's state is derived once, by the `job_state` view. It's the job's status, except that a queued job is `waiting` while its own `run_after` is ahead or, for downloads and checks, while YouTube is paused. `waiting_on` says which of those it's waiting for, and `wait_ends` when that ends. Every read uses the view, the worker's claim included, so what the Queue page shows and what runs next can't disagree. Nothing copies the pause onto job rows.

## Subscriptions

Adding a source resolves it to a canonical ID (channel `UC…` or playlist ID), so handle changes do not break it. The first check lists the source completely; later checks page through the newest entries until they reach known ones (playlists are always listed completely). Entries absent from a complete listing get `removed_at`.

Download policies:

- `none`: track the inventory only.
- `new` (default): archive entries that appear after the first check.
- `recent`: `new` plus the latest `recent_count` entries per content type from the first check.
- `all`: archive everything listed.

Channel subscriptions follow the selected tabs (`/videos`, `/shorts`, `/streams`), which also set each entry's type. Playlists take every entry. Upcoming and live entries are skipped until they finish. A video already in the library is never queued again by a check, including ones the user removed (`deleted_at`) or whose download failed (retry is explicit).

The `entry_selection` view holds this rule. It gives each entry a `skip_reason` (`policy_none`, `subscription_off`, `removed`, `not_ready`, `tab_off` or `before_subscribing`), or none when the policy selects it. A check applies the view and the inventory page shows it, so the two can't drift.

Switching a subscription off, by disabling it or setting its policy to `none`, pauses the downloads its policy had queued, so they stop without being lost; they wait in the Queue page's Paused tab. Switching it back on resumes exactly those. Downloads asked for one by one and jobs the owner paused aren't touched either way (`subscription_changed` in `app/checks.py`). A subscription that's off queues nothing, even from a check that was already running.

Checks fall due on each subscription's own schedule, counted on from its last due time, so a long pause doesn't leave them bunched together for good.

## Downloads

Download options resolve per video (the job's options), then per subscription, then library settings (`app/options.py`). They are resolved when the job runs, so editing a subscription affects its waiting downloads.

A download job extracts metadata once and defers upcoming or live videos. It then works in two phases (`app/youtube.py`):

1. **Media.** Video plus the original audio, and any requested extra audio languages that exist, as additional tracks. Formats are chosen by resolution first (so 1440p/2160p are real), then MP4-compatible codecs, then H.264. Output is MP4 when the streams fit and MKV otherwise. A failure here fails the job.
2. **Extras, best effort.** Subtitles for the chosen languages (uploaded first, then auto captions including machine translations), live chat replay, and SponsorBlock segments (stored, never cut). A failure here only loses that extra. YouTube rate-limits translated captions heavily.

The job then moves the media, thumbnail (JPEG), subtitles (VTT), chat and `.info.json` into place, and records the file's facts.

Transient failures retry with backoff (15 min, 1 h, 4 h) before failing. "Video unavailable"-type errors fail immediately and set `unavailable_at`. Running downloads can be cancelled.

YouTube gets a gentle pace, and `app/pace.py` holds every number that sets it. After a download starts or finishes, no other starts for 2–4 minutes; after a check, 20–40 s. The gate enforces this across all workers, and jobs stay queued meanwhile. yt-dlp sleeps 0.75 s between extraction requests and 5 s between subtitle files, and each adapter call's start is spaced from the last one by `YTDLP_REQUEST_INTERVAL`.

Every YouTube call goes through one gate (`app/gate.py`): downloads, checks and the API's URL lookups. A refusal from any of them pauses all of them, rather than letting each caller run into it. Refusals are a bot check, a CAPTCHA, a 429 or "try again later". A refused subtitle or live chat pauses for a fixed hour: its video is kept and counts as a success, but the next videos would lose theirs. A refused translated caption pauses nothing: YouTube limits those on their own, so losing one says little about the connection. Five generic download failures in a row also pause for a fixed hour, in case the connection is the trouble. While the gate is paused, calls are turned away before they reach YouTube:

- a URL lookup answers 503;
- a job goes back to the queue without using an attempt, and queued YouTube jobs show as waiting, retried ones included;
- a running listing stops at its next entry, and a call that was waiting its turn doesn't start;
- the scheduler queues no checks.

A download that's already transferring finishes. A job counts YouTube's refusals of it and goes behind every job YouTube hasn't refused (`QUEUE_ORDER` in `app/jobs.py`), so one video it won't serve can't hold up the queue. Run now puts a job at the front instead, skipping its own wait. Pauses after a refusal last 1, 2, 4, 8, then 12 hours while YouTube keeps refusing. Only a completed download that began after the latest refusal resets that ladder: listings and lookups keep working through a bot check, so they prove nothing. An age-gated video isn't a refusal: it fails on its own, like other videos that need an account. The pause, its cause, the run of refusals and YouTube's last message are kept in the database, so a restart neither forgets the pause nor starts the ladder over. The Queue page shows the pause and what caused it, with "Resume now" (`POST /api/jobs/resume-youtube`), which ends the pause but keeps the count. It can also pause all YouTube work on request (`POST /api/jobs/pause-youtube`). Nothing was refused, so that doesn't climb the ladder, and a longer pause already running stands.

System says what a cookie file offers without asking YouTube: whether it can be read, and whether it holds a signed-in session by yt-dlp's own test. Only using it shows whether YouTube accepts it.

## TubeArchivist import

`python -m app import-tubearchivist` (`app/tubearchivist.py`) reads a TubeArchivist backup zip or a live Elasticsearch. Formats were checked against TubeArchivist's source from v0.1.7 to current master.

- Backups are Elasticsearch bulk files (`es_<index>-<date>-<page>.json`). Older single-file and versioned-index variants are handled; leftovers from earlier, unfinished backups are skipped and listed.
- Each video is matched to `<ta media>/<channel id>/<video id>.mp4`. Pre-0.4 names (`<YYYYMMDD>_<id>_<title>.mp4`) are recognized everywhere in YouHoard.
- Without `--apply` nothing is written and the report lists what would happen.
- With `--apply` it adds:
  - channels;
  - videos: type, watched state, `unavailable_at` for TubeArchivist's inactive videos, real file size and resolution, download date;
  - subscribed channels, with content types from TubeArchivist's per-tab limits and policy `new`, with checks spread over a day;
  - subscribed playlists, with their entries as inventory;
  - TubeArchivist's ignore list, as removed videos;
  - `.info.json` sidecars, holding comments in yt-dlp's format and the raw TubeArchivist document;
  - thumbnails, copied from TubeArchivist's cache.
- Re-runs change nothing.
- `--organize` renames media and sidecars into the YouHoard layout. It refuses to cross filesystems, never overwrites, rolls back a partial rename, and resumes after an interruption.
- Not imported, only counted: pending downloads, custom playlists, unsubscribed playlists.

## API

JSON under `/api`; the OpenAPI schema is at `/docs`. Auth is an HttpOnly session cookie (or `Authorization: Bearer`); cookie-authenticated mutations must be same-origin.

| Prefix | Endpoints |
| --- | --- |
| `/api/auth` | `status`, `setup`, `login`, `logout` |
| `/api/videos` | list/filter/sort, `counts`, get (with chapters, heatmap, SponsorBlock segments, subtitles, files), `resolve` and add by URL, download with per-video options, remove local files (into the trash) and `restore` them, watched, `media` (range requests), `thumbnail`, `subtitles/{lang}`, `comments`, `chat` |
| `/api/channels` | list with counts and sorting, get, `avatar`, `banner` |
| `/api/subscriptions` | `resolve`, create, list, get, update, delete, `check`, `entries`, download one entry |
| `/api/jobs` | list with live progress (filter by `kind` and repeated `status`, which matches a job's state), `ids` of a filter, cancel, retry, run now, pause and resume (one job, or many by id), remove, clear finished, retry failed (except videos gone from YouTube), pause and resume all YouTube work |
| `/api/events` | the record, newest first, by job, video, subscription or group, paged by id |
| `/api/settings`, `/api/system`, `/api/library/rescan` | runtime settings, versions/disk/library/trash stats, pace and recent activity, rescan (`force` skips the missing-files check) |

## Frontend

Svelte 5 (runes) single-page app in `src/`, built by Vite into `app/static/dist` and served by FastAPI. During development Vite proxies `/api` to port 8000.

- **Design:** the Strongroom design, with [docs/design/mockup.html](docs/design/mockup.html) as the reference.
  - Brass color tokens for dark and light, and color only for state and actions.
  - Inter, self-hosted.
  - Each fact appears once in the UI.
- **Hash routes:**
  - `#/library`: grid or list, status tabs, filters, channel filter;
  - `#/video/:id`: player with chapters, most-replayed strip, SponsorBlock markers and labelled subtitle tracks; details, files, comments, chat replay;
  - `#/subscriptions` and `#/subscriptions/:id` (inventory and overrides);
  - `#/queue`;
  - `#/activity` (the record, by group, job, video or subscription);
  - `#/system` (settings, health, storage).
- **Code:** `src/lib/api.js` is the API client; `src/lib/types.d.ts` types the API for `npm run check`.

## Configuration

Environment variables (or `.env`): `DATA_DIR` (database, logs), `MEDIA_DIR` (library), `HOST`, `PORT`, `LOG_LEVEL`, `YTDLP_COOKIE_FILE`, `YTDLP_JS_RUNTIME` (default `deno`, installed with yt-dlp's `deno` extra), `YTDLP_REQUEST_INTERVAL`, `UMASK` (applied by both the server and the command line). Everything else is a runtime setting in the UI.

## Command line

`python -m app` (`app/__main__.py`): `import-tubearchivist`, `rescan` (the same job as the UI button), `backup <path>` (SQLite online backup, safe while running) and `reset-password <user>`.

A rescan refuses to run when it would mark more than half of the archived videos missing (and more than 10), since an unmounted or mistyped media folder looks exactly like that. It fails with the counts and changes nothing; the UI's "Rescan anyway" or `rescan --force` overrides it.

## Packaging

`Dockerfile` builds the frontend, then a Python image with ffmpeg and the locked dependencies (including Deno), with `/data` and `/media` volumes. It runs as UID 1000 by default and works as any user (Compose `user:`): caches live in `/tmp`, and the virtualenv is writable so `YTDLP_UPDATE_ON_START=1` can upgrade yt-dlp at start. The code is copied last, so an update only rebuilds and pulls small layers. `compose.tailscale.yaml` runs it behind a Tailscale container for HTTPS on a tailnet: YouHoard shares that container's network, listens only on localhost, and Tailscale Serve proxies `https://youhoard.<tailnet>.ts.net` to it.

CI runs lint, tests and the frontend check/build, then builds the image and smoke-tests it as 99:100 with `UMASK=002`. Pushes to `main` publish it to `ghcr.io/zachmeador/you_hoard` as `:main` and `:sha-<commit>`. Dependabot bumps the lockfile weekly.
