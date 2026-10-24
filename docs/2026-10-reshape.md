# October 2026 reshape

Branch `reshape/archive-core`, on top of the GPT revival checkpoint (`ea52689`). The goal was an app that can take over a multi-terabyte TubeArchivist library. That meant settling the decisions that cannot be changed after the import.

## Decisions

- **Self-describing files.** TubeArchivist kept all metadata in Elasticsearch, so its files (`<channel id>/<video id>.mp4`) mean nothing without it. YouHoard writes `<Channel> [<channel id>]/<date> <Title> [<video id>].<ext>` with `.info.json`, `.jpg` and `.vtt` sidecars sharing the basename. The `[id]` suffix is yt-dlp's convention, so TubeArchivist's import and Jellyfin's YouTube plugin can read it. Sidecars are derived from the media path, so imported files can stay in TubeArchivist's layout until `--organize`.
- **Migrations from day one.** `PRAGMA user_version` with numbered SQL files. The old schema was collapsed into a new `001_initial.sql`; old development databases are refused with instructions rather than patched.
- **Inventory-based subscriptions.** A check records everything a source lists (`source_entries`); a policy (`none`, `new`, `recent`, `all`) chooses what to archive. This replaces "scan the latest N and download them", fixes playlists being modeled as fake channels, and enables previews, backfill and "removed from YouTube" detection.
- **Derived status.** Videos store durable facts (file, removed by user, gone upstream, watched). Queued, downloading and failed come from the latest job through the `video_status` view, instead of two state machines kept in sync by hand.
- **No APScheduler.** `subscriptions.next_check_at` plus a 30-second tick in the job runner. Checks spread themselves with ±10% jitter.
- **Downloads.** Formats are chosen by resolution first. The old `vcodec:h264` sort made every quality above 1080p silently resolve to 1080p. Output is merged into MP4 when the codecs allow and MKV otherwise. Downloads finish in `.youhoard/incomplete` and are moved into place. Running downloads can be cancelled, using a yt-dlp progress-hook abort. Transient failures back off over 15 min, 1 h and 4 h before failing; "gone" errors fail immediately and flag the video.
- **yt-dlp currency.** `yt-dlp[default,deno]` installs the Deno JavaScript runtime that YouTube has required since November 2025. Dependabot bumps the lock weekly, and the container can upgrade yt-dlp on start.
- **Simpler security.** scrypt (stdlib) replaces unmaintained passlib. Sessions store a SHA-256 of the token. The same-origin check compares hosts, so it works behind TLS-terminating proxies.

## Removed

APScheduler, passlib/bcrypt, jinja2, python-multipart. Also: the 485-line startup "recovery" (replaced by an explicit rescan); `app.meta.json` sidecars; tags tables (never writable); `audio_tracks` (never applied); `scheduler_events` (duplicated job results); about 20 unused settings; the Svelte 4 frontend; and the revival docs that described the old code.

## Verification

- Integration tests drive the HTTP API against temporary SQLite and media folders with a fake YouTube: auth, library, subscriptions and policies, the queue, rescans and the TubeArchivist import.
- A live smoke test against YouTube on 2026-10-24 (results in the PR/commit notes).
- Not verified locally: the Docker image build (no Docker on the development machine; CI builds it), and the TubeArchivist import against a real backup.
