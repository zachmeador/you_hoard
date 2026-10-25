# YouHoard roadmap

What exists is described in [DESIGN.md](DESIGN.md). Work in progress is planned and tracked in [docs/backlog](docs/backlog/README.md).

## Next

- **Packaging.** Publish the image to GitHub's container registry, and support `PUID`/`PGID`/`UMASK` for NAS setups such as Unraid.
- **Search.** SQLite FTS5 over titles, descriptions and subtitles, which is what TubeArchivist used Elasticsearch for. Today's search matches titles, descriptions and channel names.
- **Catching up after an import.** Imported subscriptions only download uploads that appear after their first check. They should also fetch what was published after the channel's newest archived video.
- **Metadata refresh.** Periodically re-check archived videos to detect ones that went private or were removed (`unavailable_at`), and fill in titles for files imported without metadata.
- **Missing subtitles.** A fill-in job with backoff for tracks YouTube rate-limited, translated captions especially.
- **Collections.** Local playlists, including TubeArchivist's custom playlists (the importer currently counts and skips them).
- **Playback.** Resume position, keyboard shortcuts, next/previous within a channel, and switching audio tracks outside Safari.
- **Notifications.** Webhook or Apprise on failed downloads and repeated bot checks.
- **Automation.** Long-lived API tokens (sessions already accept `Authorization: Bearer`), then MCP tools.

## Ideas

Tags on videos and channels. Sources other than YouTube: yt-dlp supports them, but the data model assumes YouTube IDs.
