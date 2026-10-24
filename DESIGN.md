# YouHoard design

## Scope

A single-user YouTube archive, primarily driven by channel and playlist subscriptions. Saving one video by pasting its URL is equally supported. Content-type selection—regular videos, Shorts and livestream replays—is a per-subscription control.

FastAPI serves the API and built Svelte frontend. SQLite stores application state; yt-dlp and ffmpeg handle extraction and downloads. No external database, search service or message broker is required.

## Application lifecycle

`main.py` constructs the application and owns startup/shutdown:

1. Initialize SQLite and the configured storage directory.
2. Recover a YouHoard-format file library if the video table is empty.
3. Create one downloader/worker pool shared by API requests and APScheduler.
4. Requeue interrupted jobs, then start workers and subscription schedules.
5. On shutdown, stop scheduling and let current jobs finish.

Run one application process. Multiple Uvicorn workers would each run a scheduler and recovery pass; this deployment mode is not supported.

## Queue

`job_queue` persists downloads, subscription discovery and metadata extraction. Enqueue and claim operations use SQLite transactions. A source can have one queued, running or paused job of a given type. Workers claim jobs by descending priority, then insertion order. `MAX_CONCURRENT_DOWNLOADS` bounds the worker pool across all job types.

Job state is `queued` → `downloading`/`processing` → `completed`/`failed`. Paused jobs are not claimed. Retry resets the same failed job. Progress is held in memory during transfers; completion and failure are persisted for the specific job, not every attempt for its video.

Only queued jobs can be paused or removed while unfinished. Cancelling an asyncio task does not terminate a yt-dlp thread, so active cancellation is not exposed as if it worked. Graceful shutdown waits for in-progress operations; interrupted jobs resume on restart after a forced stop.

`app/core/ytdlp_service.py` runs blocking yt-dlp operations in worker threads. Request spacing is serialized; retries preserve the underlying error. Download output templates and progress hooks are supplied by the downloader.

## Library and storage

YouTube IDs uniquely identify videos and channels. Manual additions and discovery share the metadata insertion path in `app/core/library.py`. Playlist videos are assigned to their actual uploader, not their playlist's owner.

```text
storage/
  channels/
    <channel-id>_<name>/
      <video-id>_<title>/
        video.mp4
        video.info.json
        thumbnail.jpg
        app.meta.json
```

The container may differ from MP4. Existing ID-prefixed directories are reused after title changes. SQLite stores relative media filenames and actual file size/resolution; playback also accepts the directory-only paths written by early versions.

All served paths are resolved beneath the storage root. Media removal is limited to a matching managed video directory. Removing media keeps a `deleted` record to suppress automatic re-download; explicit Download restores it. Removing a subscription never deletes its videos.

File sidecars make a YouHoard-format library recoverable, but do not replace a database backup: subscriptions, sessions and removal history are database state. TubeArchivist import is a separate, unimplemented operation.

## Subscriptions

[Subscription behavior](docs/subscriptions.md) defines creation, content filters, checks, schedules and removal. Scheduler events record the actual discovery result. The UI follows asynchronous jobs rather than treating enqueue as success.

The current policy scans the most recent N entries per selected channel tab, or per playlist. Automatic downloading is opt-in and includes matches from the initial scan. Full inventory, membership tracking and explicit future-only/backfill policies remain open.

## API and frontend

API routes live under `/api/auth`, `/api/videos`, `/api/channels`, `/api/subscriptions` and `/api/downloads`. FastAPI's `/docs` describes the request/response schemas. Authentication covers library mutation, jobs, thumbnails and range-capable local playback.

Svelte uses hash routing and the shared stylesheet in `app/static/css/main.css`. The main workflows are Home, Videos, Subscriptions and Downloads. Native dialogs provide focus handling and Escape dismissal. Channels and Settings are placeholders and are not in navigation.

Vite proxies API and shared stylesheet requests during development. Production serves `app/static/dist/index.html` and its assets; it never substitutes HTML for an API error.

## Checks and remaining work

Run `uv run pytest`, `uv run ruff check app main.py tests`, `uv run ruff format --check app main.py tests`, `npm run check` and `npm run build`. Tests use temporary SQLite/media storage and replace the YouTube boundary; the threaded adapter is exercised separately.

[ROADMAP.md](ROADMAP.md) tracks remaining work. The [recovery assessment](docs/revival.md) records the defects that motivated this pass and the release checks still required.
