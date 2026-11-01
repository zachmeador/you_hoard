# Cookie setup

YouTube refuses signed-out requests with a bot check, and account cookies are the only documented way past it ([research](../research/youtube-access.md#cookies-and-accounts)). Today that means exporting a file, getting it onto the server and setting `YTDLP_COOKIE_FILE`, and nothing says when the cookies stop working. Setup has to happen in the browser, and reconnecting has to be easy, because cookies can die within hours of heavy use.

| Question | Answer after this work |
| --- | --- |
| How do I give YouHoard my cookies? | Paste or upload them on System |
| Did YouTube accept them? | The Test button, and when it last ran |
| Why have downloads stopped? | The Queue says whether cookies need loading or reconnecting |
| When did they stop working? | `cookies.expired` on the Activity page |

## Decisions

### One file, kept private

- A saved file lives at `DATA_DIR/cookies.txt`, readable only by the app's user (0600). It stays out of the database, so a backup never carries account credentials.
- `config.cookie_file` is the only code that decides which file is in use: `YTDLP_COOKIE_FILE` if set, otherwise the saved one. With the env var set, System says so and offers no way to replace or remove it.
- Cookie contents never leave the server. No API response, log line or event carries them, and a test enforces that. The size limit is checked in the route, because FastAPI's own 422 for a `Field` limit echoes the input back.

### yt-dlp rewrites the file

`YoutubeDL.__exit__` saves its cookie jar back over `cookiefile`, truncating the file in place. That keeps rotated cookies, which is worth having, but used directly it fails in two ways: a call that's running when new cookies are saved writes the old ones back when it closes, and a call that starts during a write can read half a file.

- One helper in `app/youtube.py` wraps all eight `yt_dlp.YoutubeDL(...)` uses. Each call gets its own private copy of the file.
- When a call closes, its copy replaces the file by rename, unless the file was saved or removed after the copy was made. A generation number, bumped by saving and removing, tells which.
- A file that can't be written back, like a read-only `YTDLP_COOKIE_FILE`, still works, since yt-dlp only touches the copy.

### Saving

- `PUT /api/system/cookies` takes the file's text as JSON. The page reads an upload in the browser and sends it the same way, so the app gains no multipart dependency.
- The text goes through `cookie_state` before anything changes. `unreadable` and `anonymous` are refused with a message saying which, and the file in place stays.
- Saving writes a temporary file, created as 0600 so no umask can widen it, and renames it into place.
- Saving neither contacts YouTube nor ends a pause.

### Testing

- Test makes one call through `YouTubeGate`, like every other YouTube call: it lists the first entry of the account's private Liked Videos (`https://www.youtube.com/playlist?list=LL`), as Tube Archivist does. Only a signed-in session can see that list.
- During a pause it answers 503 like other lookups and reaches nothing. System offers Resume now beside it, because loading new cookies is the reason to end a pause. A refusal counts like any other, so the button can't be used to hammer YouTube.
- Accepted means YouTube treats the session as signed in. It doesn't promise that a video will download; only a completed download shows that, and the page's words don't claim more.
- The result goes in `events`, and System reads the latest one since the file was saved. No new table.

### Saying when to reconnect

- When YouTube rotates a session out, yt-dlp loses `LOGIN_INFO` from its jar and warns "The provided YouTube account cookies are no longer valid". Its write-back then leaves the file reading `anonymous`. Saving refuses `anonymous`, so a saved file that reads that way has died, and `/api/system` reports it as `expired`.
- The adapter turns that warning into a `cookies.expired` event, once per saved file, so Activity says when. `app/youtube.py` stays the only code that reads yt-dlp's words.
- The Queue's `refused` callout says what to do, from `youtube_pause_cause` and `cookies`. No cookies means load them; `expired`, or `signed_in` with YouTube refusing anyway, means reconnect. Either links to System.

### The page

System's Cookies row becomes a section: state and source, a paste box and file picker, Test, Remove, and Resume now while YouTube work is paused. Beside them, how to export safely:

- Use a spare account. The [yt-dlp wiki](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies) warns that using an account this way risks a temporary or permanent ban.
- Sign in from a private window, export with a cookies.txt extension, then close the window and don't open that session again. YouTube rotates cookies on open tabs, so a session you keep using goes stale on the server. Browsers usually turn extensions off in private windows, so the page has to say to allow this one.

### Not in this work

- Keeping cookies in sync from a browser extension, as Tube Archivist does.
- A sign-in window streamed from the server.
- More than one account.

## API contract

- `GET /api/system` changes and adds:

  ```json
  {
    "cookies": "signed_in",
    "cookies_source": "saved",
    "cookies_tested": {"at": "…", "result": "accepted"}
  }
  ```

  `cookies` gains `expired`. `cookies_source` is `saved`, `env` or null. `cookies_tested` is the latest test since the file was saved, or null.
- `PUT /api/system/cookies` with `{"text": "…"}` answers `{"cookies": "signed_in"}`. It's 422 with the reason if the text can't be used, and 409 while `YTDLP_COOKIE_FILE` is set.
- `DELETE /api/system/cookies` removes the saved file, and is 409 while `YTDLP_COOKIE_FILE` is set.
- `POST /api/system/cookies/test` answers `{"result": "accepted"}` or `{"result": "rejected", "detail": "…"}`. It's 503 while YouTube is paused and 409 with no cookies loaded.
- New events, all in Activity's App group: `cookies.loaded`, `cookies.removed`, `cookies.tested` and, by the app, `cookies.expired`.

## Tasks

Tests use `tests/fake_youtube.py` and never contact real YouTube. The first real check is the owner's, with a spare account.

### Backend

- [ ] `config.cookie_file`, read by the adapter and `/api/system`
- [ ] One helper around `yt_dlp.YoutubeDL`: a private copy per call, written back unless the file was saved or removed meanwhile
- [ ] `PUT` and `DELETE /api/system/cookies`: checked before saving, atomic, 0600, recorded as events
- [ ] `POST /api/system/cookies/test` through the gate, with `check_cookies` on the adapter and the fake
- [ ] The `expired` state, the `cookies.expired` event, `cookies_source` and `cookies_tested`
- [ ] Tests: saving, each refusal, 0600 after a save and after a write-back, the env var's precedence, a running call not undoing a save or a removal, Test during a pause reaching nothing, and contents absent from responses, logs and events

### Frontend

- [ ] Types and API client follow the contract
- [ ] Cookies section on System: paste, file picker, Test, Remove, Resume now and how to export safely
- [ ] The Queue's `refused` callout, `HINTS` in `src/lib/jobs.js` and System's warnings point at the section, not at `YTDLP_COOKIE_FILE`
- [ ] Event words in `src/lib/events.js`
- [ ] Checked in the running app at desktop and phone width

### Docs

- [ ] DESIGN.md, README.md, `.env.example` and the comment in `compose.yaml`
- [ ] The research doc's section on how YouHoard handles cookies
