"""Every number that sets how fast YouHoard talks to YouTube.

Two more live elsewhere: `max_concurrent_downloads`, a setting that caps parallel downloads, and
`YTDLP_REQUEST_INTERVAL`, the config value that spaces out when adapter calls begin.
"""

# Seconds yt-dlp sleeps between requests while extracting a video, and between the pages of a
# channel or playlist listing.
REQUEST_SLEEP = 0.75
LISTING_SLEEP = 1
# Seconds yt-dlp sleeps between subtitle files; YouTube rate-limits subtitles first.
SUBTITLE_SLEEP = 5

# Seconds, as a range to draw from, that no other job of the kind starts after one starts or
# finishes. The gate enforces it across all workers.
REST = {"download": (120.0, 240.0), "check": (20.0, 40.0)}

# How long YouTube work waits after a bot check, longer each time YouTube refuses in a row.
BLOCK_PAUSES = (3600, 2 * 3600, 4 * 3600, 8 * 3600, 12 * 3600)
# How long YouTube work waits after it refuses a subtitle or live chat. The video came through, so
# this stays off the ladder above.
EXTRAS_PAUSE = 3600
# Downloads that fail for no particular reason, this many in a row, pause YouTube work for this
# long, also off the ladder. A completed download ends the streak.
FAILURE_STREAK = 5
FAILURE_PAUSE = 3600

# Seconds a job waits before its next try after failing for no particular reason.
RETRY_DELAYS = (15 * 60, 60 * 60, 4 * 60 * 60)

# Seconds a download waits to try again after a premiere is due to start, and, when YouTube doesn't
# say when it starts, after each try.
PREMIERE_DELAY = 10 * 60
PREMIERE_RECHECK = 60 * 60

# How many times the adapter repeats a lookup or listing that failed for no particular reason, and
# the seconds before the first repeat; each later one waits three times as long. Downloads aren't
# repeated here: the job retries them on RETRY_DELAYS.
CALL_RETRIES = 2
CALL_RETRY_SLEEP = 5
