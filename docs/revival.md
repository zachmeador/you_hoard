# Recovery assessment

## Product scope

YouHoard is a single-user YouTube archive. The primary workflow is following channels and playlists; pasting a video URL is a first-class shortcut. Each subscription independently selects regular videos, Shorts and livestream replays.

The application should make three things clear: what it will download, whether the archive succeeded, and where to find the saved video. It should not require a separate search engine, message broker, YouTube API key or AI service.

## Baseline findings

The July 2025 implementation had several blocking defects:

- API authentication dependencies returned an authentication object without validating a session.
- Download processing called missing methods; retry and resume targeted a removed worker implementation.
- yt-dlp blocked the event loop and replaced the archive's output template.
- Jobs were disposable tasks with no restart recovery, and the scheduler used a separate downloader instance.
- The subscription UI expected immediate results from an asynchronous job. Content filters relied on incomplete metadata, and discovery could enumerate an entire source.
- Quality options differed between the UI and backend. Downloaded resolution could be misreported.
- Delete left media on disk and removed the record needed to prevent automatic re-download.
- Production served development HTML. Missing API routes returned HTML with HTTP 200.
- Downloads, Channels and Settings were placeholder pages. No local player or first-run setup UI existed.
- No test source files were tracked, the frontend check command referenced a missing config, and dependency locks were ignored.

## Recovery scope

The recovery branch addresses authentication, first-run setup, a shared persistent queue, bounded subscription discovery, content-type controls, download monitoring/retry, local playback and confined file access. Removed media remains remembered so a subscription does not immediately download it again.

Channel discovery uses the selected Videos, Shorts and Streams tabs. Playlist entries require individual metadata extraction; Shorts classification falls back to dimensions and duration when no Shorts URL is available. That fallback is not an authoritative YouTube classification. Ongoing/upcoming streams are skipped; recording a stream while it is live is not implemented.

Verification covers API-to-SQLite/file workflows with a YouTube test double, the threaded yt-dlp adapter, and an opt-in browser test that plays a generated local video. This establishes application behavior, not compatibility with current YouTube extraction. A live download and representative channel/playlist checks remain release requirements.

## Remaining gaps

| Priority | Gap | Acceptance criteria |
| --- | --- | --- |
| Before daily use | Subscription preview and backfill policy | Show the resolved source and planned initial download count. Distinguish only future uploads, latest N and a complete archive. No surprise backfill. |
| Before daily use | Live YouTube verification | Verify a manual video, a mixed playlist and channels with each content filter against the current yt-dlp release. Record unavailable-tab and authentication behavior. |
| Before daily use | Operational settings | Show disk space and dependency health; configure default quality and download preferences. Do not expose controls that are not applied. |
| Before migration | TubeArchivist import | Preview an exported sample, map IDs and existing files, then import media and subscriptions without re-downloading. The existing recovery scanner only understands YouHoard's layout. |
| Before deployment | Container packaging and backup | One container, persistent app data and separate media mount, non-root UID/GID, ffmpeg and supported yt-dlp runtime. Test SQLite backup/restore. |
| Next | Source inventory | Track subscription/playlist membership separately from globally deduplicated videos. Show saved, queued, ignored and unavailable entries. |
| Next | Active transfer control | Pause/cancel the actual transfer and postprocessing. Current controls intentionally support only queued jobs. |
| Next | Library UX | Channel browsing, sorting, bulk actions, tags, watched/resume state and caption playback. Channels and Settings remain unimplemented and are not in navigation. |
| Next | Recovery and storage guards | Missing-file reconciliation, free-space checks, explicit import/export and file-only recovery tests. No automatic media deletion. |
| Later | Private sources | Cookie-file validation, expired-login diagnostics and private-playlist tests. A mounted cookie file is supported by configuration but has no management UI. |
| Later | Automation | API/MCP integrations after the human workflow is dependable. |

[ROADMAP.md](../ROADMAP.md) tracks the work. [Subscription behavior](subscriptions.md) defines the current actions and their effects.
