# What yt-dlp can extract from YouTube

Checked on 2026-10-25 against yt-dlp 2026.10.21 with real extractions:
- a long-form video (25 uploaded subtitle tracks, 157 auto-caption languages, 20 dubbed audio languages);
- a Short;
- a past livestream;
- four Veritasium videos (chapters and "most replayed" data);
- a channel's Videos and Shorts tabs;
- a playlist.

"Stored" means a database column, "sidecar" means the `.info.json`, and "file" means the downloaded media.

## What YouHoard should keep

The rule: keep what belongs to the video and cannot be recovered once YouTube loses it. Skip what can be regenerated, derived from the file, or is only useful while streaming from YouTube. The database holds only what the UI sorts and filters on; the sidecar holds the full record.

**Always keep**
- The video at the chosen quality, with the original audio track.
- Text and structure:
  - title, description, tags, categories;
  - the exact upload time;
  - chapters;
  - availability at archive time (public, unlisted, members-only);
  - the most-replayed heatmap, which is tiny and gone if the video disappears.
- Uploaded subtitles in your languages: small text files, useful for accessibility and future search.
- The original-language auto caption when there is no uploaded track. Speech recognition in the video's own language is real content; machine translations are not.
- The best thumbnail, and the channel's avatar and banner, saved as files in the channel folder.
- Facts about the file you archived: codec, frame rate, HDR, audio language. Store them in the database for display and filtering.
- View, like and comment counts as a snapshot "at archive time". The sidecar copy is the record; the database copy is for sorting.

**Keep if you opt in (per subscription or video)**
- **Comments.** Slow to fetch and large, but irreplaceable context for some channels. Off by default, capped, and shown in the UI when kept.
- **Extra audio languages.** Each adds about 128 kb/s; twenty dubs is roughly 40% more at 1080p.
- **Live chat replay** for streams. These are large JSON files.
- **SponsorBlock segments,** stored as markers, never cut out of the file. The archive keeps the original.

**Don't keep**
- **Format tables, signed URLs, request headers, fragment lists.** They expire and are bulky; already dropped.
- **Extra thumbnail sizes and storyboards.** Scrub previews can be generated from the file with ffmpeg.
- **Machine-translated captions.** Low quality, regenerable, and each one is a rate-limited request.
- **Compressed-dynamics ("DRC") audio.** It only matters when streaming.
- **Comment authors' avatar images, and per-video copies of channel stats.**
- **Routine counter refreshes.** Use an explicit metadata refresh instead, mainly to catch videos that went private or were removed.

**What this changes from today**
1. Store the exact upload time, not just the date.
2. Store codec, frame rate, HDR, audio language, availability and age limit.
3. Make auto captions original-language only by default (next section).
4. Save channel avatars and banners.
5. Store playlist entries' channel and view count.
6. Stop one failed subtitle from failing the whole download (next section).

## Subtitles in several languages

This already works:
- The library setting is a list (Settings → subtitle languages, comma-separated).
- Each subscription can use the library default, none, or its own list.
- Every language is saved as `<name>.<lang>.vtt` and appears as a track in the player.

Three problems surfaced while checking:

1. **One failed language fails the whole video.** yt-dlp aborts the download when any subtitle fails, unless told to ignore every error, which would also hide real download failures. YouTube rate-limits its caption endpoint (HTTP 429), so more languages means more failed downloads. Fix: fetch subtitles in a second, best-effort step after the video, record which languages were saved, and let a later retry fill in the rest.
2. **Machine translations slip in.** When a language has no uploaded track, YouHoard falls back to YouTube's auto captions. For any language other than the video's own, that is a machine translation, so asking for five languages can produce five of them. YouTube labels the original-language auto track separately (`en-orig`, "English (Original)"), so they can be told apart.
3. **Codes must match YouTube's:** `en` versus `en-GB`, `pt-BR`, `zh-Hans`, `es-419`. yt-dlp accepts patterns like `en.*`, but those also pull in regional variants and the `-orig` track.

The recommended design:
- **Languages:** a picker for subtitle languages with an "All uploaded" choice, replacing the comma-separated box.
- **Auto captions:** off, original language only (the default), or also translations.
- **Per subscription:** the same controls, overriding the library default.
- **Video page:** each track labelled uploaded, auto or translated. The file name keeps YouTube's code (`en-orig`) so the type survives without the app.

For comparison, TubeArchivist had a comma-separated language list, a choice between uploaded and auto-generated captions, and an option to index subtitle text for search. How well it worked in practice is unknown; it faced the same YouTube limits.

## Per video

| Data | yt-dlp fields | YouHoard now | UX implication |
| --- | --- | --- | --- |
| Text | `title`, `description`, `tags`, `categories`, `language` (often empty) | Title and description stored; tags and categories in sidecar | Show tags and categories on the video page; index them for search |
| Dates | `upload_date`, `timestamp` (exact upload time), `release_timestamp` (premiere or stream start) | Date only | Show the time, sort precisely, show "premieres at" |
| Counters | `view_count`, `like_count`, `comment_count`, `channel_follower_count`. Dislikes and ratings no longer exist. | Views and likes stored | Label them "at archive time"; a later metadata refresh could update them |
| Kind and state | `media_type` (`video` or `livestream`), `live_status`, `was_live`, `availability` (public, unlisted, private, needs_auth, subscriber_only, premium_only), `age_limit` | Type stored; Shorts come from the Shorts tab or an aspect-ratio and duration guess, because `media_type` does not flag Shorts | Badges for unlisted, members-only and age-restricted; errors that say when cookies would help |
| Technical | `width`, `height`, `fps`, `dynamic_range` (SDR, HDR10, HLG), `vcodec`, `acodec`, bitrates, `audio_channels`, `filesize` | Width, height and size stored | One line like "1080p60 HDR · AV1 + Opus · 5.9 Mb/s"; filters for 60 fps and HDR |
| Channel reference | `channel`, `channel_id`, `uploader_id` (@handle), `channel_is_verified` | Channel stored | Verified badge |
| Chapters | `chapters`: start, end, title | Sidecar, and embedded in the file | Chapter list and timeline markers in the player |
| Most replayed | `heatmap`: 100 segments, each a start, end and 0–1 value, on popular videos only | Sidecar (dropped until 2026-10-25) | A heat strip on the timeline and "jump to the most replayed part" |
| Thumbnails | about 40 sizes, up to 1920×1080 | Best one saved as `.jpg` | None |

## What can be downloaded

| Stream | Available | YouHoard now | UX implication |
| --- | --- | --- | --- |
| Video | Up to 4320p; H.264 usually up to 1080p, plus VP9 and AV1; HDR and 60 fps variants; sometimes a higher-bitrate "Premium" 1080p | One video track; resolution cap; MP4 and H.264 preferred at equal resolution | A codec preference setting (compatibility or smaller AV1 files); show the chosen format |
| Audio | The original track plus dubbed or auto-dubbed languages (each labelled, the original marked default), compressed-dynamics ("DRC") variants, Opus and AAC | Original language only (yt-dlp's default) | Choose extra audio languages per subscription or video, kept as extra tracks with a switcher in the player; an audio-only option for podcast-style channels |
| Storyboards | `sb0`–`sb3` thumbnail sprite sheets | Not downloaded | Hover previews when scrubbing (or generate locally with ffmpeg) |

## Subtitles, captions, chat

| Data | Available | YouHoard now | UX implication |
| --- | --- | --- | --- |
| Uploaded subtitles | `subtitles` (sample: 25 languages); VTT, SRT, TTML, srv1–3, json3 | VTT for the library's languages (default English) | "All uploaded subtitles" option; a language picker |
| Auto captions | `automatic_captions`: speech recognition plus machine translations (sample: 157 languages) | Used when no uploaded track exists | Mark auto and translated tracks as such; never fetch all of them |
| Live chat replay | A `live_chat` JSON "subtitle" on stream replays where chat replay was kept (the NASA sample had none) | Not downloaded | Opt-in chat replay panel beside the player for streams (large files) |

## Comments

`getcomments` returns `id`, `text`, `author`, `author_id`, `author_url`, `author_thumbnail`, `author_is_uploader`, `author_is_verified`, `is_pinned`, `is_favorited` (hearted), `like_count`, `parent` (`root` or a comment ID, so threads can be rebuilt) and `timestamp`. It is slow: comments are paged, so YouHoard caps them at 1,000 per video.

YouHoard now: opt-in per subscription or library, stored in the sidecar, **not shown anywhere**.

UX implication: a comments tab on the video page with threads, pinned and uploader comments first, labelled "at archive time".

## Channels (from a tab listing)

- **Available:** name, ID, @handle, description, follower count, verified, keywords, avatar (900×900 and uncropped) and banner (up to 2560 px and uncropped).
- **Not available:** join date, country, total views and links. These are on the About page, which yt-dlp does not fully extract.
- **YouHoard now:** name, handle, description and subscriber count.
- **UX implication:** a channel header with banner and avatar. Save them as files in the channel folder (`channel.jpg`, `banner.jpg`) so they outlive the app.

## Listings (subscription inventory)

| Listing | Per-entry fields | YouHoard now | UX implication |
| --- | --- | --- | --- |
| Channel Videos or Streams tab | ID, title, duration, views; Streams also have upcoming, live or finished status. No dates unless the `approximate_date` extractor option is used ("2 weeks ago" becomes an approximate timestamp). | ID, title, duration, type, position, live status | Show views to help choose a backfill; approximate dates in the inventory |
| Channel Shorts tab | ID, title, views, `/shorts/` URL; no duration | Same | Same |
| Playlist | ID, title, duration, views, **uploader channel**; the playlist itself has title, description, owner, count, last modified and views | Uploader unknown until downloaded | Store the per-entry channel so queued playlist videos show their channel straight away |

## Account and discovery

- **Search:** `ytsearchN:query` returns IDs, titles, channels, durations and views. This would allow "search YouTube" in the Add dialog.
- **With a cookies file:**
  - Watch Later (`list=WL`) and Liked videos (`list=LL`) can be followed like playlists.
  - The subscribed-channels page (`/feed/channels`) allows "import my YouTube subscriptions".
  - Members-only and age-restricted videos become downloadable.

## Download-time extras

- **SponsorBlock:** mark sponsor segments as chapters, or cut them out. It queries an external service with video IDs. UX: skip sponsors in the player.
- **Clips:** download only a time range (`--download-sections`), or split a video by chapters. UX: "save a clip" from a long stream.
- **Recording live:** `--live-from-start` records a stream from its beginning. YouHoard currently waits until a stream has finished. UX: a "record live streams" option per subscription.

## Suggested UX work, by cost

1. **Data already on disk:** chapter markers, a most-replayed strip, a comments tab, tags and categories, exact upload time.
2. **Small backend additions:** store fps, codecs, HDR and audio language at download, plus availability and age limit; store playlist entries' channel and views. Use them for the technical line, badges and better inventory.
3. **New options:** extra audio languages with a track switcher; subtitle language choice including "all uploaded"; audio-only subscriptions; channel art saved as files.
4. **New features:** search-to-add; YouTube account import (cookies); chat replay; scrub previews; SponsorBlock; recording live streams; clips.
