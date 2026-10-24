# YouHoard roadmap

### Fixing the current state of slop

- Consolidate and de-slop the random docs.
- Write user flows for subscription actions.
- Move thoughts.md contents to this

## Product requirements

- Channel and playlist subscriptions are the primary workflow.
- Pasting a video URL into the web UI must remain straightforward.
- Each subscription independently selects regular videos, Shorts and livestream replays.
- Show what will be archived, report failures clearly, and make saved videos easy to find and play.
- Keep deployment small: FastAPI, SQLite, yt-dlp, ffmpeg and one frontend. No external search engine or broker.

Earlier exploration notes are in [thoughts.md](thoughts.md). They are historical input, not a commitment to implement every idea. Current behavior is described in [DESIGN.md](DESIGN.md) and [subscription flows](docs/subscriptions.md).

## Recovery branch

- [x] Enforce authentication and add first-run setup.
- [x] Share one persistent queue between API requests and scheduled checks.
- [x] Repair download processing, retry, output paths and restart recovery.
- [x] Bound source scans and apply per-subscription content filters.
- [x] Pass quality, comment and subtitle preferences into queued downloads.
- [x] Show real job states, errors and subscription check results.
- [x] Add authenticated local playback and safe media removal with re-download suppression.
- [x] Fix frontend serving/proxying and add integration tests and dependency locks.
- [ ] Verify against current YouTube, not just isolated tests.

## Before daily use

1. **Subscription preview and backfill.** Resolve a source before saving and show the initial plan. Separate future-only, latest N and complete archive modes. Make limits and content filters explicit.
2. **Live-source verification.** Exercise regular videos, Shorts and completed streams on real channels and a mixed playlist. Handle missing tabs and unavailable videos without misleading success.
3. **Useful settings.** Default quality, download preferences, disk space, cookie-file health and dependency versions. Only expose settings that work.
4. **Deployment and preservation.** One-container packaging, non-root file ownership, SQLite backup/restore and missing-file detection.
5. **TubeArchivist import.** Read-only preview of an exported sample, then import existing files and subscriptions without re-downloading.

## Later

- Source inventory and playlist membership, distinct from globally deduplicated files.
- Actual interruption of active transfers and postprocessing.
- Channel browsing, sorting, bulk library actions and tags.
- Watched/resume state and subtitle playback.
- Private-source management and clearer expired-cookie diagnostics.
- API/MCP tooling after the human workflow is dependable.

The [recovery assessment](docs/revival.md) contains the baseline findings and acceptance criteria. Channels and Settings remain unimplemented; a passing build is not a declaration of release readiness.
