# Redesign API contract

Changes to the API for the Strongroom rebuild. Everything not listed stays as it is today (see the routers in `app/api/` and `src/lib/types.d.ts`). New fields may be null.

## Option resolution

Download options resolve per video, then per subscription, then library settings. The options are:
- quality;
- subtitle languages, and whether auto captions may fill in;
- comments;
- extra audio languages;
- live chat replay;
- SponsorBlock.

## Videos

The Video object adds:

| Field | Type |
| --- | --- |
| `published_at` | `"YYYY-MM-DDTHH:MM:SSZ"` when YouTube gives the exact time, else `"YYYY-MM-DD"` |
| `unavailable_at` | timestamp or null (the `unavailable` boolean stays) |
| `availability` | `public`, `unlisted`, `private`, `needs_auth`, `subscriber_only`, `premium_only`, or null |
| `age_limit` | int |
| `fps` | number |
| `vcodec` | codec family: `avc1`, `vp9`, `av01`, `hevc` |
| `acodec` | `mp4a`, `opus` |
| `dynamic_range` | `SDR`, `HDR10`, `HLG`, … |
| `audio_languages` | `[str]`: the audio tracks in the file, default first |
| `comment_count` | int: YouTube's count at archive time |

`GET /api/videos/{id}` also adds:

| Field | Type |
| --- | --- |
| `tags`, `categories` | `[str]` |
| `chapters` | `[{start, end, title}]`, in seconds |
| `heatmap` | `[{start, end, value}]`, value 0–1 |
| `sponsor_segments` | `[{start, end, category}]` |
| `subtitles` | `[{lang, name, source, url}]`; source is `uploaded`, `auto`, `translated` or `unknown` |
| `files` | `[{path, kind, size}]`; kind is `media`, `info`, `thumbnail`, `subtitles`, `chat` or `other`; path is relative to the media folder |
| `comments` | `{saved: int, url}` or null |
| `chat_url` | string or null |

New and changed endpoints:

| Endpoint | Behavior |
| --- | --- |
| `GET /api/videos` | New param `unavailable=true\|false`; `sort` also takes `views` |
| `GET /api/videos/counts` | Same filters as the list except `status` → `{all, archived, downloading, queued, failed, missing, deleted, unavailable}`, for the status tabs |
| `GET /api/videos/{id}/comments?sort=top\|new&page=&per_page=` | `{items: [Comment], total}`. Items are top-level comments, each with `replies: [Comment]`. Pinned first under `top`. |
| `GET /api/videos/{id}/chat` | `{items: [{t, author, text}]}` from the saved live chat replay; `t` is seconds into the video |
| `POST /api/videos` and `POST /api/videos/{id}/download` | Accept optional per-video options: `quality`, `subtitle_languages`, `auto_captions`, `download_comments`, `audio_languages`, `live_chat`, `sponsorblock` |

Comment: `{id, text, author, author_id, author_is_uploader, author_is_verified, is_pinned, is_favorited, like_count, timestamp}`.

## Channels

- **Channel object adds:** `verified: bool`, `avatar_url`, `banner_url` (strings or null).
- **`GET /api/channels`:** `sort=name|size|videos` (default `name`).
- **New endpoints:** `GET /api/channels/{id}/avatar` and `/banner` return images saved in the channel folder as `channel.jpg` and `banner.jpg`. They are fetched when a channel subscription is created or checked.

## Subscriptions

- **Subscription object adds overrides** (null means the library default): `audio_languages: [str]`, `auto_captions: bool`, `live_chat: bool`, `sponsorblock: bool`. Its `channel` includes `avatar_url`.
- **Create and update** accept the new overrides.
- **Inventory entries add** `channel_name` and `view_count`. For playlists that is the uploader from the listing.

## Jobs

`counts` adds `waiting`: queued jobs whose `run_after` is in the future. `queued` now counts only jobs ready to run.

## Settings

| Setting | Default |
| --- | --- |
| `audio_languages` | `[]` |
| `auto_captions` | `true` |
| `live_chat` | `false` |
| `sponsorblock` | `false` |

`options` adds `languages: [{code, name}]`, a curated list of common YouTube language codes for the subtitle and audio pickers.
