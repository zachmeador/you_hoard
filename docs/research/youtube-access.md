# YouTube access and bot checks

Checked on 2026-10-26. The code facts were verified against YouHoard at `16ac112` and the installed yt-dlp 2026.10.21. The upstream issue and release facts come from pages read that day; they change quickly, so recheck them before relying on them.

## How yt-dlp reports refusals

yt-dlp turns YouTube's playability errors into distinct messages (`_video.py` in its YouTube extractor):

| Refusal | yt-dlp's message | What's established |
| --- | --- | --- |
| Sign-in required | "Sign in to confirm you’re not a bot", plus a cookies hint | Hits anonymous requests; account cookies are the documented fix. A PO token doesn't get past it: bgutil's maintainers say so, and in [yt-dlp #15865](https://github.com/yt-dlp/yt-dlp/issues/15865) (February 2026) every client was refused and a maintainer rejected a token provider as the fix |
| Rate limit | "This content isn't available, try again later", plus "rate-limited by YouTube for up to an hour" | The only refusal with a stated duration. yt-dlp suggests `-t sleep`; its wiki suggests 5–10 s between videos |
| CAPTCHA | "YouTube is requiring a captcha challenge before playback" | Reported separately from sign-in. YouHoard doesn't recognise it (defect 3) |
| Age gate | "Sign in to confirm your age" | About the video, not the connection; needs a signed-in account |

Failures that aren't refusals:

- **Missing PO token.** A PO token proves that a request comes from a genuine YouTube client. It's minted by running Google's BotGuard challenge in a browser-like runtime. Some clients need one for player, video-stream (GVS) and subtitle requests, and most web tokens are bound to a single video. Without one, formats go missing or the stream returns 403.
  - The [PO Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide) (substantive revision 2026-03-10) recommends a provider plugin and the `mweb` client for GVS tokens.
  - Providers: [bgutil](https://github.com/Brainicism/bgutil-ytdlp-pot-provider), a Node/Deno script or a server (2.0.2 released 2026-10-07), and [WebPoClient](https://github.com/coletdjnz/yt-dlp-getpot-wpc), which drives Chrome and is experimental.
  - A plugin that loads may still not run: in [bgutil #277](https://github.com/Brainicism/bgutil-ytdlp-pot-provider/issues/277) (2026-10-23) the plugin was found but its script timed out.
- **JavaScript challenges.** yt-dlp solves YouTube's signature and `n` challenges with the EJS solver scripts plus an external runtime, required since [2025.11.12](https://github.com/yt-dlp/yt-dlp/issues/15012). The minimum runtimes in 2026.10.21 (`yt_dlp/utils/_jsruntime.py`) are Deno 2.3, Node 22, Bun 1.2.11 and QuickJS 2023-12-09. The EJS package has to match the yt-dlp version.
- **Reduced formats.** Some sessions get only format 18 (360p), so a workaround can succeed and still drop to 360p.
  - In [#17666](https://github.com/yt-dlp/yt-dlp/issues/17666) (2026-09-10), `mweb` and `web_embedded` went SABR-only apart from format 18. yt-dlp's SABR downloader is still an unmerged PR ([#13515](https://github.com/yt-dlp/yt-dlp/pull/13515), test build 2026-10-21).
  - In the `android_vr` 403 incident ([#17456](https://github.com/yt-dlp/yt-dlp/issues/17456), 2026-08-18), switching to `android` worked for one user. Another got only format 18, and no formats at all with cookies.
- **Inconsistent reports.** In [#17904](https://github.com/yt-dlp/yt-dlp/issues/17904) (2026-10-24), one user got the bot check while another listed 54 formats for the same URL.

## Cookies and accounts

- **OAuth is gone.** yt-dlp raises "Login with OAuth is no longer supported", so cookies are the only way to use an account.
- **Loaded isn't accepted.** yt-dlp counts a session as signed in when YouTube's session cookies and `LOGIN_INFO` are present, and warns when supplied cookies stop counting. A cookie file that loads isn't proof that YouTube accepts the session.
- **Rotation.** YouTube "rotates account cookies frequently on open YouTube browser tabs". So a one-time export from a browser you keep using goes stale once the browser rotates the session. A real browser session works only while something keeps the server's copy current. There are two ways around this:
  - **Freeze the session.** The [extractor wiki](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies) says to sign in from a private window, export, then close the window so nothing ever opens that session again. `--cookies-from-browser` reads the regular profile, not the private window, so this method needs a cookie-export extension.
  - **Follow the session.** Keep re-syncing from a live browser, as Tube Archivist's extension does (see [Other archivers](#other-archivers)).
- **Account risk.** The wiki says to use cookies only when needed and warns that using an account with yt-dlp risks a temporary or permanent ban. It suggests a throwaway account.
- **Google's official routes don't replace cookies.**
  - Google OAuth tokens aren't a YouTube browser session.
  - The [YouTube API policies](https://developers.google.com/youtube/terms/developer-policies-guide) forbid offline downloads.
  - Google OAuth [refuses embedded browsers](https://developers.google.com/identity/protocols/oauth2/policies#secure-browsers).
- **Same-origin limit.** A page served by YouHoard can't read youtube.com's cookies. A browser extension can, with the `cookies` permission and host access.

## Other archivers

| App | Documented approach |
| --- | --- |
| [Tube Archivist](https://docs.tubearchivist.com/settings/application/) | Cookie import by hand or through its [browser extension](https://docs.tubearchivist.com/browser-extension/user-docs/). The extension's Continuous Cookie Sync re-sends the browser's cookies whenever they change, at most every 10 s; its Copy Now button makes a one-time copy that goes stale. TA validates a cookie by fetching the account's private Liked Videos playlist, and holds one cookie per instance. Its docs report accounts flagged and cookies expiring within a few hours, and say YouTube may invalidate a cookie used outside a browser. It also has a configurable PO-token provider URL, and recommends request spacing and limiting comments |
| [Pinchflat](https://github.com/kieraneglin/pinchflat/wiki/Frequently-Asked-Questions) | Caps concurrency and staggers indexing; fast indexing through RSS or the YouTube API, with a monthly full scan; [cookie modes](https://github.com/kieraneglin/pinchflat/wiki/YouTube-Cookies) of off, when needed (one retry with cookies) and always |
| [MeTube](https://github.com/alexta69/metube/wiki/Using-browser-cookies) | Upload, replace and delete cookies in the UI; bundles a bgutil server on loopback; images follow stable yt-dlp, with an optional nightly |
| [Youtarr](https://github.com/DialmasterOrg/Youtarr/blob/main/docs/TROUBLESHOOTING.md) | Cookie upload and test; log export redacts secrets |

## YouHoard at `16ac112`

### Pacing

| What | Value | Where |
| --- | --- | --- |
| Download workers | 2 by default, 1–8 | `app/settings.py`, `app/api/system.py` |
| Rest after each download | 10–30 s per worker | `DOWNLOAD_REST` in `app/jobs.py` |
| Checks and scans | One separate worker | `app/jobs.py` |
| Gap between adapter calls | At least 2 s (`YTDLP_REQUEST_INTERVAL`) | `YouTube._run` |
| yt-dlp request sleep | 0.75 s; 1 s for channel listings | `REQUEST_SLEEP`, `YouTube.list_entries` |
| Subtitle sleep | 5 s per file | `SUBTITLE_SLEEP` |
| Comments, when enabled | Up to 1,000 per video, at most 100 of them replies | `YouTube.download` |

The 2-second gap spaces out when operations start, not HTTP requests. The lock is released before yt-dlp runs and one operation makes many requests, so parallel downloads, a check and a URL lookup can overlap.

For comparison, yt-dlp's `-t sleep` preset waits 0.75 s between requests, 5 s between subtitle files and 10–20 s before each download. Its extractor wiki (June 2025) estimated about 300 videos an hour as a guest and 2,000 with an account. Those are historical estimates, not quotas.

### Retries and pauses

| Error | What happens |
| --- | --- |
| `Blocked`: "sign in to confirm you", "try again later", HTTP 429, "too many requests" or "rate-limit" | All queued downloads and checks wait 1 hour, then 2, 4, 8 and 12 hours while refusals continue (`BLOCK_PAUSES`). The job keeps its attempt |
| Generic `YouTubeError`, including HTTP 403 | That job alone retries after 15 minutes, 1 hour and 4 hours (`RETRY_DELAYS`), 4 attempts in all |
| `Inaccessible` or `Unavailable` | That job fails at once. `Unavailable` also marks the video as gone from YouTube |
| Generic errors in metadata calls | The adapter retries after 5 and 15 seconds |
| Downloads | No adapter retry; yt-dlp retries 5 times for HTTP, 10 for fragments and 3 for extraction |

### Defects

Each defect was confirmed in the code. The classifier results came from running `classify` on real yt-dlp messages.

1. **An age-gated video pauses everything.** `BLOCKED` contains "sign in to confirm you", which also matches "Sign in to confirm your age", and it's checked before `INACCESSIBLE`. `classify` returns `Blocked`, so one age-restricted video holds the whole queue for an hour. The real bot message uses a curly apostrophe ("you’re"), so a narrower pattern has to allow for both forms.
2. **Listings reset the backoff.** Any successful download *or check* sets `_blocks = 0` in `JobRunner._run`. Listings can keep working while every video request is refused, so with several subscriptions the pause can stay at 1 hour while every download fails.
3. **CAPTCHA refusals aren't recognised.** No `BLOCKED` pattern matches yt-dlp's captcha wording, so the rest of the message decides. Usually that means a generic per-job retry. If YouTube's reason also says "Video unavailable", the job is classified `Unavailable`: the video is marked gone from YouTube and the download fails without a retry.
4. **The pause lives in memory.** `youtube_paused_until` and `_blocks` start at zero in each `JobRunner`. After a restart, delayed jobs keep their `run_after`, but new work and newly due checks run straight away and the backoff starts over.
5. **The pause doesn't stop running jobs.** `_pause_youtube` reschedules queued jobs and signals nothing to running ones.
6. **URL lookups ignore the pause.** `fetch_info`, `resolve_video`, `add_video`, `resolve_source` and `create_subscription` call yt-dlp directly. Their failures become API errors and never start a pause.
7. **Failed extras count as success.** Subtitles and live chat run with `ignoreerrors=True`, so a rejected extras request still ends in a successful job, which also resets the backoff.
8. **System's bot-check count misses most bot checks.** It counts failed download jobs from the last 24 hours whose error mentions "bot". Bot checks are requeued rather than failed, and checks aren't counted.
9. **"Cookies: Loaded" only means the file exists.** System reports cookies when `YTDLP_COOKIE_FILE` points at a file. Nothing checks that it parses or that YouTube accepts it.
10. **Nothing stops all YouTube work.**
    - A download policy of `none` doesn't stop checks or cancel queued downloads.
    - Disabling a subscription doesn't cancel its queued or running jobs.
    - Only queued jobs can be paused, and concurrency can't go below 1.

`tests/test_bot_checks.py` and `tests/test_download_phases.py` pass (11 tests). They run against the fake YouTube and cover the queue pause with one worker, growing and resetting pauses, held checks and worker rest. They say nothing about real YouTube.

## Not known

- Google publishes no YouTube thresholds, scoring inputs or block durations. The only stated duration is yt-dlp's "up to an hour" for the rate limit.
- There's no known limit on the number of videos. A video count undercounts requests anyway, since extraction, checks, subtitles, comments and retries all reach YouTube.
- No source compares success rates for client switches, PO tokens, cookies or proxies.
- Google's note that [shared networks can trigger unusual-traffic blocks](https://support.google.com/websearch/answer/86640) covers Search, not YouTube.
