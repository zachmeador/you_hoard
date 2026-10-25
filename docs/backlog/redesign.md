# Redesign: Strongroom

Rebuild the Svelte frontend to match [docs/design/mockup.html](../design/mockup.html), and add the backend data the design needs. In progress since 2026-10-25. The API contract is [redesign-api.md](redesign-api.md). The backend (sections 3 and 4) and frontend (sections 1 and 2) are built in parallel by Sonnet 5.5 subagents, then integrated and verified here.

## Decisions

- **Color:** Brass. Stone neutrals, a brass accent used only for the primary action, focus and "where you are", and a five-hue state family at matched OKLCH lightness and chroma. "Gone from YouTube" is orchid. The color rules are in the mockup's header comment.
- **Type:** Inter only, self-hosted from `@fontsource-variable/inter`; monospace for paths and IDs. Nothing under 12px, no condensed widths, default font smoothing.
- **Chrome:** no logo or wordmark. A solid "Add" button opens the add dialog for a video, channel or playlist.
- **Every fact appears once.** No page subtitles, no counts repeated between the sidebar and pages. The nav shows only live activity ("N running") and problems (a System dot).
- **Thumbnails are content.** Real images as YouTube serves them; the fallback placeholder is neutral.
- **Opt-in data has a library default in Settings,** overridable per subscription and per video: comments, extra audio languages, live chat replay, SponsorBlock markers.
- **Subtitles:** keep YouTube's auto and machine-translated tracks for the chosen languages when no uploaded track exists, and label each track's source.

## 1. Foundation

- [ ] Brass tokens for dark and light, Inter, and the type scale and weights from the mockup.
- [ ] Shell:
  - sidebar (Add, nav, channel list, account) at 1180px and wider;
  - top bar below that;
  - bottom tab bar on phones.
- [ ] Routes: `#/library`, `#/video/:id`, `#/subscriptions`, `#/subscriptions/:id`, `#/queue`, `#/system`. Channels become a Library filter, and the sidebar channel list links to it.
- [ ] Components:
  - buttons and segmented control, select, search;
  - status glyph set and corner-layout thumbnail;
  - list rows, archived bar, policy control;
  - dialog, toast, menu.

## 2. Screens

- [ ] **Library:** grid and list (remembered), status tabs that wrap, filters, sort, date-grouped grid, channel header when filtered.
- [ ] **Video page:** player sized to the video's aspect ratio, chapters, Details and Files panels, subtitles, actions, more from the channel.
- [ ] **Subscriptions:** table with archived bars, last check, next check, enabled switch, actions.
- [ ] **Subscription detail:**
  - policy control and tabs;
  - overrides;
  - checks panel;
  - inventory table with per-entry download.
- [ ] **Queue:** Running, Waiting, Up next, Failed and History sections with live progress.
- [ ] **System:** health, storage, settings (including the opt-in defaults), rescan, TubeArchivist import instructions.
- [ ] **Add dialog:** resolve a video, channel or playlist, then confirm.

## 3. API additions the design needs

- [x] Return `unavailable_at`, and filter the video list by gone from YouTube.
- [x] Count waiting jobs (queued with a future `run_after`) separately from queued.
- [x] Status counts for the library tabs (`GET /api/videos/counts`). The grid groups dates from the loaded page.
- [x] A per-video file list (media plus sidecars) and each subtitle track's source.
- [x] Settings for the opt-in defaults; subscription and video overrides.
- [x] `POST /api/videos/resolve` so the Add dialog can preview a video (added during integration).

## 4. From the research (confirmed by the owner)

- [x] Store the exact upload time, codec, frame rate, HDR, audio language, availability and age limit.
- [x] Subtitles best-effort after the video; record which languages were saved and from what source.
- [x] Data for the heatmap, comments, live chat replay and SponsorBlock markers. The UI is in section 2.
- [x] Playlist entries: store the uploader channel and views.
- [x] Extra audio languages, downloaded as additional tracks. Switching in the player is a follow-up.
- [x] Channel avatar and banner saved as files.

## Follow-ups found while building

- **Audio track switching.** Browsers only switch tracks in a muxed file in Safari (`audioTracks`). Elsewhere it needs a per-track stream (an ffmpeg remux endpoint). Decide whether it's worth it.
- **Translated captions.** YouTube answered HTTP 429 to every translated-caption request in the live check. A later "fill in missing subtitles" job with backoff would recover some.
- **Playlist uploaders.** Flat playlist listings include the uploader for only a few entries; the rest fill in when downloaded.

## 5. Verification

- [ ] An opt-in Playwright test of the main flows against the fake YouTube.
- [ ] A live check against YouTube, plus phone and desktop widths in dark and light.
