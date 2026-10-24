# Subscriptions

A subscription follows a YouTube channel or playlist. The same video can be discovered through several sources, but its YouTube ID identifies one library record and one local copy.

## Add a source

1. Paste a channel or playlist URL. The form detects its type; it can also be selected explicitly.
2. Select regular videos, Shorts, livestream replays, or any combination. These choices belong to this subscription, not the entire library.
3. Choose the recent-entry limit, quality cap, comments, subtitle languages and schedule.
4. Choose whether to download automatically. It is off by default; discovery alone creates pending library entries that can be downloaded manually.
5. Save. An enabled subscription queues an initial check and schedules future checks. A disabled subscription is saved without checking.

**The initial check includes existing uploads.** The limit applies to each selected channel tab, or to the playlist. It is a bounded recent scan, not a full archive or a guarantee that every upload since the previous check will be found. Explicit future-only/backfill modes and a preview are still needed.

## Content types

- Channel subscriptions query only the selected `/videos`, `/shorts` and `/streams` tabs. The source tab determines the video type.
- Playlist entries use individual metadata to identify their uploader and content type. Completed livestreams are recognized from live metadata. Shorts URLs identify Shorts; dimensions/duration are a fallback, not a guaranteed classification.
- Upcoming, currently live and still-processing livestreams are skipped. Livestream replay downloads begin after the recording becomes available.
- Excluding a type prevents new discovery/downloads of that type. It does not delete previously saved videos.

## Check now

Check Now returns a queued job, not a finished result. Repeated requests reuse an existing queued/running check for the source. Progress, errors and results appear in Downloads; the subscription card shows its most recent check.

Discovery compares source IDs against the library, adds missing metadata and optionally queues downloads with the subscription's quality, comments and subtitle preferences. Each playlist video's uploader is resolved independently of the playlist owner. Existing failed downloads require an explicit retry.

## Edit, pause and resume

Editing affects subsequent checks and newly queued downloads. Already queued downloads retain their preferences. Audio-track selection is not implemented.

Pause disables future scheduled checks. It does not stop a current check or remove queued downloads. A manual check is still available. Resume restores the schedule; it does not trigger an immediate check.

## Remove a source or video

Removing a subscription leaves its library videos and their files intact. A running check must finish before the subscription can be removed.

Removing a video's local files retains a `deleted` record. Discovery will not download it again. The Removed filter exposes these records; Download explicitly restores one. Active/queued downloads must finish or be removed from the queue before their files can be removed.
