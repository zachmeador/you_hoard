# YouHoard roadmap

What exists is described in [DESIGN.md](DESIGN.md); the October 2026 reshape and its reasoning are in [docs/2026-10-reshape.md](docs/2026-10-reshape.md).

## Before migrating the TubeArchivist library

- [ ] Dry-run `import-tubearchivist` against a real backup and a sample of the media folder; fix any field the importer misreads.
- [ ] Import a slice (one channel) with `--apply`, browse and play it, then `--organize` it.
- [ ] Run subscriptions for a week on real channels (videos, Shorts, streams, a playlist) and watch the queue for failures.
- [ ] Build and run the Docker image on the server, with the media mount owned by the container user; test `python -m app backup` and a restore.

## Next

- **Search.** SQLite FTS5 over titles, descriptions and subtitles, which is what TubeArchivist used Elasticsearch for.
- **Metadata refresh.** Periodically re-check archived videos to detect ones that went private or were removed (`unavailable_at`), and fill in titles for files imported without metadata.
- **Collections.** Local playlists, including TubeArchivist's custom playlists (the importer currently counts and skips them).
- **Channel pages.** Avatars and banners (TubeArchivist's cache has them), per-channel stats.
- **Playback.** Resume position, keyboard shortcuts, next/previous within a channel.
- **Notifications.** Webhook or Apprise on failed downloads and repeated bot checks.
- **Automation.** Long-lived API tokens (sessions already accept `Authorization: Bearer`), then MCP tools.

## Ideas

From the original notes: tags on videos and channels; per-video download options when adding (subtitles, comments, not only quality); audio track selection; SponsorBlock segments; sources other than YouTube (yt-dlp supports them, but the data model assumes YouTube IDs).
