# What yt-dlp can extract from YouTube

Checked on 2026-10-25 against yt-dlp 2026.10.21 with real extractions:
- a long-form video (25 uploaded subtitle tracks, 157 auto-caption languages, 20 dubbed audio languages);
- a Short;
- a past livestream;
- four Veritasium videos (chapters and "most replayed" data);
- a channel's Videos and Shorts tabs;
- a playlist.

"Stored" means a database column, "sidecar" means the `.info.json`, and "file" means the downloaded media.

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
