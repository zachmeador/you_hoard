# YouHoard design

A single-user YouTube archive: follow channels and playlists, save individual videos, browse and play the archive in the browser, and import an existing TubeArchivist library. One process, SQLite, yt-dlp and ffmpeg. No search engine, broker or YouTube API key.

## Principles

1. **The files outlive the app.** Every archived video sits next to a readable `.info.json`, thumbnail and subtitles, under human-readable names. Losing the database loses app state (subscriptions, queue history, watched marks), not the archive. TubeArchivist kept metadata only in Elasticsearch; YouHoard does not repeat that.
2. **SQLite is the index.** It is versioned with migrations and can be rebuilt from the files with a library rescan.
3. **Durable facts and transient work are separate.** A video row records what is true (archived file, removed by the user, gone from YouTube). Queued, downloading and failed come from the jobs table.
4. **Subscriptions keep an inventory.** A check lists what a channel or playlist contains; a download policy decides what to archive. Nothing is downloaded by surprise.
5. **yt-dlp is the only YouTube boundary** (`app/youtube.py`). Tests replace it with a fake.

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
    <YYYY-MM-DD> <Title> [<video id>].mp4         # or .mkv/.webm
    <YYYY-MM-DD> <Title> [<video id>].info.json   # slimmed yt-dlp metadata, comments
    <YYYY-MM-DD> <Title> [<video id>].jpg
    <YYYY-MM-DD> <Title> [<video id>].en.vtt
  .youhoard/incomplete/<video id>/                 # in-progress downloads
```

- The `[id]` suffix is yt-dlp's convention; TubeArchivist's import and Jellyfin's YouTube metadata plugin key on it.
- Names are fixed when a file is first archived. A later title change on YouTube does not rename anything; channel folders are found by their `[channel id]` suffix.
- Sidecars share the media file's basename, so `videos.media_path` is the only path stored. Files imported from TubeArchivist in place (`<channel id>/<video id>.mp4`, `<video id>.en.vtt`) follow the same rule.
- Downloads complete in `.youhoard/incomplete` and are moved into place on the same filesystem, so media servers never see partial files.
- Every served or removed path is resolved inside `MEDIA_DIR`.

## Data model

Migrations live in `app/migrations/NNN_name.sql` and are tracked with `PRAGMA user_version`. Timestamps are UTC ISO 8601 strings (`2026-10-24T18:00:00Z`).

| Table | Purpose |
| --- | --- |
| `channels` | YouTube uploaders (`youtube_id` = `UC…`). |
| `videos` | One row per video the library knows. `media_path` (relative to `MEDIA_DIR`) is set when archived. `deleted_at` marks local files removed by the user: never downloaded automatically again. `unavailable_at` records that YouTube reported the video gone. `watched_at`. `channel_id` may be null until metadata is known. |
| `subscriptions` | A followed channel or playlist with its `download_policy`, content types (channel tabs), quality/subtitle/comment overrides and `next_check_at`. |
| `source_entries` | Inventory: every video a subscription's source has listed, with position, `baseline` flag and `removed_at`. Joined to `videos` by YouTube ID. |
| `jobs` | `download` and `check` (and `scan`) work. Partial unique indexes allow one active job per video or subscription. `options` is input, `result` output. `run_after` defers premieres and retry backoff. |
| `settings` | Runtime settings as JSON values: default quality, subtitle languages, comments, concurrency, default check interval. |
| `users`, `sessions` | One account; sessions store a SHA-256 of the token. |

A video's status is derived (`app/library.py`): `archived` (has a file) → `downloading` / `queued` (latest download job) → `deleted` → `failed` → `missing` (known, not archived, nothing pending).

## Subscriptions

Adding a source resolves it to a canonical ID (channel `UC…` or playlist ID), so handle changes do not break it. The first check lists the source completely; later checks page through the newest entries until they reach known ones (playlists are always listed completely). Entries absent from a complete listing get `removed_at`.

Download policies:

- `none`: track the inventory only.
- `new` (default): archive entries that appear after the first check.
- `recent`: `new` plus the latest `recent_count` entries per content type from the first check.
- `all`: archive everything listed.

Channel subscriptions follow the selected tabs (`/videos`, `/shorts`, `/streams`), which also set each entry's type. Playlists take every entry. Upcoming and live entries are skipped until they finish. A video already in the library is never queued again by a check, including ones the user removed (`deleted_at`) or whose download failed (retry is explicit).

## Downloads

A download job extracts metadata once, defers upcoming/live videos, then downloads with the subscription or library quality cap. Formats are chosen by resolution first (so 1440p/2160p are real), merged into MP4 when the codecs allow and MKV otherwise. After postprocessing the job moves the media, thumbnail (JPEG), subtitles (VTT) and a slimmed `.info.json` into place and records the actual resolution and size.

Transient failures retry with backoff (15 min, 1 h, 4 h) before failing. "Video unavailable"-type errors fail immediately and set `unavailable_at`. Running downloads can be cancelled.

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
| `/api/videos` | list/filter/sort, get, add by URL, download, delete local files, watched, `media` (range requests), `thumbnail`, `subtitles/{lang}` |
| `/api/channels` | list with counts, get |
| `/api/subscriptions` | `resolve`, create, list, get, update, delete, `check`, `entries`, download one entry |
| `/api/jobs` | list with live progress, cancel, retry, pause, resume, remove, clear finished, retry failed |
| `/api/settings`, `/api/system`, `/api/library/rescan` | runtime settings, versions/disk/library stats, rescan |

## Frontend

Svelte 5 single-page app in `src/`, built by Vite into `app/static/dist` and served by FastAPI. Hash routes: Library, Channels, Subscriptions (with inventory), Queue, Settings. During development Vite proxies `/api` to port 8000.

## Configuration

Environment variables (or `.env`): `DATA_DIR` (database, logs), `MEDIA_DIR` (library), `HOST`, `PORT`, `LOG_LEVEL`, `YTDLP_COOKIE_FILE`, `YTDLP_JS_RUNTIME` (default `deno`, installed with yt-dlp's `deno` extra), `YTDLP_REQUEST_INTERVAL`. Everything else is a runtime setting in the UI.

## Command line

`python -m app` (`app/__main__.py`): `import-tubearchivist`, `rescan` (the same job as the UI button), `backup <path>` (SQLite online backup, safe while running) and `reset-password <user>`.

## Packaging

`Dockerfile` builds the frontend, then a Python image with ffmpeg and the locked dependencies (including Deno), running as UID 1000 with `/data` and `/media` volumes. `YTDLP_UPDATE_ON_START=1` upgrades yt-dlp at container start. CI runs lint, tests, the frontend check/build and an image build; Dependabot bumps the lockfile weekly.
