<h1 align="center">YouHoard</h1>

<p align="center">
  A self-hosted YouTube archive that keeps your videos as plain, well-named files.<br>
  Follow channels and playlists, save single videos, and watch it all in your browser.
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#features">Features</a> ·
  <a href="#moving-from-tubearchivist">Moving from TubeArchivist</a> ·
  <a href="#contributing">Contributing</a>
</p>

> [!WARNING]
> **Project status: functional slop-cannon.** YouHoard works end to end: it follows channels, downloads, imports TubeArchivist libraries and plays everything back. But most of it was written fast by AI coding agents, it has tests rather than users, and parts of it haven't met real-world data yet. If you'd like to help turn the slop into software, PRs are very welcome. See [Contributing](#contributing).

<!-- Screenshot: the library -->

## Why YouHoard

Videos disappear from YouTube all the time: channels get deleted, uploads go private, takedowns happen. YouHoard keeps your own copy, in plain files that make sense without the app.

- **The files outlive the app.** Every video sits in a readable folder next to its metadata, thumbnail and subtitles. A media server or a file browser can make sense of it, and losing the database loses app state, not the archive.
- **One container, nothing else to run.** FastAPI, SQLite, yt-dlp and ffmpeg in a single process. No Elasticsearch, no Redis, no YouTube API key.
- **Nothing downloads by surprise.** Subscriptions keep an inventory of everything a channel or playlist lists, and a policy you pick decides what gets archived.
- **Leave TubeArchivist without re-downloading.** The importer adopts an existing library in place, with its metadata, comments, watched marks and subscriptions.

## Features

**Archive**
- Channels, playlists and single videos, from 360p up to 4K. Files are MP4 when the codecs allow and MKV otherwise.
- Subtitles in as many languages as you like. When a video has no uploaded track, YouTube's automatic and machine-translated captions fill in, labelled by source.
- Optional extras: comments, extra audio languages (as tracks in the same file), live chat replays and SponsorBlock segments (marked, never cut).
- Library-wide defaults for all of it, overridable per subscription and per video.

**Follow**
- Subscribe to a channel's Videos, Shorts and Live tabs, or to a playlist.
- Pick a policy: **Track only**, **New uploads**, **Latest N** or **Everything**.
- Routine checks stop at the first uploads they already know, so they take seconds. Videos that vanish from a channel are marked in its inventory.

**Watch**
- A dense library with grid and list views, status tabs, search, filters and sorting.
- A player with chapters, a most-replayed strip, SponsorBlock markers and labelled subtitle tracks.
- Comments (top or newest, with replies) and live chat replay next to the video.
- Watched marks, dark and light themes, and a layout that works on a phone.

<!-- Screenshot: a video page -->

**Run**
- A live queue with progress, pause, cancel and retry. Failed downloads retry with backoff.
- Your copy stays when a video leaves YouTube, and the library can filter for videos known to be gone.
- Removed files go to a trash for 30 days, and you can restore them from the video's page. Turn the trash off in **System** to delete right away.
- A rescan refuses to mark most of the library missing, so an unmounted or mistyped media folder can't scramble it.
- Command-line tools for rescans, online database backups and password resets.

## Quick start

YouHoard runs as one Docker container. Every push to `main` publishes an image to `ghcr.io/zachmeador/you_hoard:main`; there are no tagged releases yet.

Save this as `compose.yaml`, or grab [the one in this repository](compose.yaml). Mount your archive folder at `/media`, and set `user:` to the owner of those files so YouHoard can write there:

```yaml
services:
  youhoard:
    image: ghcr.io/zachmeador/you_hoard:main
    restart: unless-stopped
    user: "1000:1000"           # the owner of your media folder
    ports:
      - "8000:8000"
    environment:
      YTDLP_UPDATE_ON_START: "1"
    volumes:
      - ./data:/data            # database and logs
      - /path/to/media:/media   # the archive
```

Any `user:` works. On a NAS such as Unraid, media shares usually belong to `99:100`: use that, and add `UMASK: "002"` so new files stay writable for the share's group.

Create the data folder yourself, so it belongs to you rather than root, then start it:

```bash
mkdir -p data
docker compose up -d
```

Open http://localhost:8000, create your account, and use **Add** to paste a channel, playlist or video URL. To update later, run `docker compose pull && docker compose up -d`. To build the image yourself instead, clone this repository, swap `image:` for `build: .`, and run `docker compose up -d --build`.

> [!TIP]
> YouTube breaks old yt-dlp releases regularly. With `YTDLP_UPDATE_ON_START=1` the container upgrades yt-dlp every time it starts, so a restart usually fixes a sudden wave of failed downloads.

## Configuration

Most settings live in the app under **System**: default quality, subtitle languages, the optional extras, how many downloads run at once and how often subscriptions are checked. Environment variables cover the deployment:

| Variable | Default | What it does |
| --- | --- | --- |
| `YTDLP_UPDATE_ON_START` | off (`1` in `compose.yaml`) | Upgrades yt-dlp when the container starts |
| `YTDLP_COOKIE_FILE` | none | A Netscape-format cookies file, for private playlists or when YouTube asks for a bot check |
| `YTDLP_REQUEST_INTERVAL` | `2` | Seconds between YouTube requests |
| `YTDLP_JS_RUNTIME`, `YTDLP_JS_RUNTIME_PATH` | `deno` | The JavaScript runtime yt-dlp needs for YouTube. Deno comes with YouHoard. |
| `UMASK` | inherited (`022`) | Octal mask for new files and folders. `002` keeps them group-writable. |
| `SESSION_DAYS` | `30` | How long a login lasts |
| `LOG_LEVEL` | `INFO` | Log verbosity |
| `DATA_DIR`, `MEDIA_DIR` | `/data`, `/media` | Where the database and the archive live. From source, they default to `./data` and `./media`. |

[`.env.example`](.env.example) lists the same variables for running from source.

## The archive on disk

```text
media/
├── Tape Rescue Club [UCq8Hx2N3vT0mFkL5bW1zR7d]/
│   ├── channel.jpg
│   ├── banner.jpg
│   ├── 2019-06-14 Shopping mall walkthrough, 1991 (VHS) [aB3dE5fG7hJ].mp4
│   ├── 2019-06-14 Shopping mall walkthrough, 1991 (VHS) [aB3dE5fG7hJ].info.json
│   ├── 2019-06-14 Shopping mall walkthrough, 1991 (VHS) [aB3dE5fG7hJ].jpg
│   └── 2019-06-14 Shopping mall walkthrough, 1991 (VHS) [aB3dE5fG7hJ].en.vtt
└── .youhoard/
    ├── incomplete/            downloads in progress
    └── trash/                 removed videos, until they expire
```

- The `[id]` suffixes follow yt-dlp's convention, so other tools can match files to YouTube.
- The `.info.json` holds yt-dlp's metadata, plus comments and SponsorBlock segments when you keep them. A live chat replay goes in a `.live_chat.json` next to it.
- Names are set once, when a video is archived. A later title change on YouTube renames nothing.
- Downloads finish in `.youhoard/incomplete` and move into place in one step, so media servers never see half a file.
- If the database is lost, a rescan rebuilds the library from these files. Subscriptions and settings live only in the database, so back it up (see [Commands](#commands)).

## Moving from TubeArchivist

The importer reads TubeArchivist's metadata and adopts its files where they are. Nothing is re-downloaded.

1. **Make a fresh backup.** Start TubeArchivist once; it doesn't need to download anything. Use Settings → Actions → Backup, which writes a zip of all its metadata to its `cache/backup` folder, then stop it. For extra safety, keep a copy of its Elasticsearch volume too: metadata for videos that have since left YouTube exists nowhere else.
2. **Point YouHoard at the files.** Mount TubeArchivist's media folder at `/media`, or a folder that contains it on the same filesystem. Mount its cache folder as well, so the importer can read the backup and thumbnails. Read-only is fine:

   ```yaml
       volumes:
         - ./data:/data
         - /path/to/tubearchivist/media:/media
         - /path/to/tubearchivist/cache:/ta-cache:ro
   ```

3. **Preview the import.** This dry run writes nothing:

   ```bash
   docker compose exec youhoard python -m app import-tubearchivist --backup /ta-cache/backup/ta_backup-….zip
   ```

   - Add `--ta-media <folder>` when TubeArchivist's media folder is a subfolder of `/media`.
   - Thumbnails come from the cache folder next to the backup; pass `--ta-cache` if it's elsewhere.
   - The importer can read a running Elasticsearch instead: `--es-url http://host:9200` with `TA_ES_PASSWORD` set.

   Read the counts and warnings: videos matched to files, missing files, orphans, subscriptions, the ignore list and comments.
4. **Apply it.** Run the same command with `--apply`. Files stay exactly where they are, and older TubeArchivist file names work too. It adds:
   - channels and videos, with watched marks and the removed-from-YouTube flag;
   - subscribed channels (keeping the tabs you followed) and playlists, set to **New uploads**;
   - the ignore list;
   - an `.info.json` with comments next to each video, plus its thumbnail from the cache.

   Running it again changes nothing.
5. **Organize, if you like.** Once you trust it, run with `--apply --organize` to rename the files into YouHoard's layout. It renames within one filesystem, never overwrites and never re-downloads. TubeArchivist can't follow the new names, so do this last.

> [!NOTE]
> Imported subscriptions only download uploads that appear after their first check. To fill a gap from while TubeArchivist was down, switch a subscription to **Latest N** with a count that covers it.

## Commands

```bash
docker compose exec youhoard python -m app rescan                   # reconcile the database with the media folder
docker compose exec youhoard python -m app backup /data/backup.db   # copy the database safely while it runs
docker compose exec youhoard python -m app reset-password <user>    # set a new password
```

When running from source, use `uv run python -m app …` instead. A rescan that would mark most of the library missing stops without changing anything; add `--force` if those files really are gone.

## HTTPS

YouHoard speaks plain HTTP and leaves certificates to whatever sits in front of it.

**With Tailscale**, [`compose.tailscale.yaml`](compose.tailscale.yaml) runs YouHoard next to a Tailscale container. It gets its own address on your tailnet, `https://youhoard.<your-tailnet>.ts.net`, with a certificate Tailscale renews for you, and no ports open on the host.

1. In the [Tailscale admin console](https://login.tailscale.com/admin), turn on MagicDNS and HTTPS certificates on the DNS page, then generate an auth key under Settings → Keys.
2. Save it in a `.env` file next to the compose file: `TS_AUTHKEY=tskey-auth-…`.
3. Set the media mount and `user:` as in the quick start, then run `docker compose -f compose.tailscale.yaml up -d`.

The first visit can take a few seconds while the certificate is issued. In the admin console, turn off key expiry for the new `youhoard` machine, or it drops off your tailnet after six months.

Even without HTTPS, Tailscale encrypts everything between your devices, so plain `http://` over a tailnet is still private. HTTPS adds the padlock and the browser features that need it.

**With your own reverse proxy** (Caddy, Nginx Proxy Manager, Traefik), point it at port 8000 and pass `X-Forwarded-Proto` and `X-Forwarded-Host`. YouHoard uses them to mark its login cookie secure and to check that changes come from its own pages. Tailscale's proxy sends both already.

## Security

YouHoard has a single account and is meant for a trusted network: your LAN, a VPN or a tailnet. It hasn't been hardened for the open internet.

## How it works

- **One process.** FastAPI serves the API and the Svelte frontend. A job runner inside it handles downloads, subscription checks and library scans, with a scheduler tick every 30 seconds. Run one process, not several workers.
- **SQLite is the index.** Migrations are numbered SQL files. A video's status (archived, downloading, queued, failed, missing) is derived from durable facts plus its latest job, so there's no second state machine to keep in sync.
- **yt-dlp is the only door to YouTube** (`app/youtube.py`). Downloads run in two phases: the media must succeed, while subtitles, chat and SponsorBlock are best effort.
- **Tests use a fake YouTube,** so the suite is fast and offline. That proves the app, not YouTube compatibility; live checks do that.

[DESIGN.md](DESIGN.md) has the details: the data model, subscription policies, the download pipeline and the importer.

## Contributing

The bar for a useful PR is low and the need is real. Good places to start:

- **Use it and report what breaks.** YouTube changes constantly, so issues about failed downloads, odd channels or strange yt-dlp output are gold.
- **Try the TubeArchivist import on a real backup.** The dry run writes nothing. Open an issue with anything it misreads.
- **Pick something from the [roadmap](ROADMAP.md):** full-text search, catching up after an import, a subtitle fill-in job, audio track switching outside Safari, or tagged releases.
- **Read a module and make it smaller.** Simplifications, deletions and clearer names are all welcome.

### Development setup

You need Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 22+ and ffmpeg. Deno, which yt-dlp needs for YouTube, installs with the Python dependencies.

```bash
uv sync
npm ci
npm run dev   # the API on :8000 and the frontend with hot reload on :5173
```

Open http://localhost:5173. Copy [`.env.example`](.env.example) to `.env` to choose where the database and archive go.

Before opening a PR, run:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
npm run check && npm run build
```

The end-to-end browser test is opt-in. It drives the built frontend in your installed Chrome, or in the Chromium at `PLAYWRIGHT_CHROMIUM_EXECUTABLE`:

```bash
npm run build
RUN_BROWSER_TESTS=1 uv run --with playwright python -m pytest -m browser
```

### Finding your way around

| Path | What's there |
| --- | --- |
| `app/` | The backend: API routers in `app/api/`, the job runner, the yt-dlp boundary (`youtube.py`) and the TubeArchivist importer |
| `app/migrations/` | Numbered SQL migrations. A schema change is a new file. |
| `src/` | The Svelte 5 frontend, built into `app/static/dist` |
| `tests/` | Integration tests that drive the real API against a fake YouTube |
| `docs/` | yt-dlp research notes, the design reference and the backlog |

### House rules

- Read [DESIGN.md](DESIGN.md) first. It explains the decisions that are expensive to change.
- Only `app/youtube.py` talks to yt-dlp, and tests use the fake in `tests/fake_youtube.py`.
- In the UI, each fact appears once: no repeated counts and no subtitles under page titles.
- Keep PRs focused, and say how you tested them.

## Acknowledgements

YouHoard stands on [yt-dlp](https://github.com/yt-dlp/yt-dlp), [FFmpeg](https://ffmpeg.org), [SponsorBlock](https://sponsor.ajay.app), [Deno](https://deno.com) and [Inter](https://rsms.me/inter/). [TubeArchivist](https://github.com/tubearchivist/tubearchivist) showed what a self-hosted YouTube archive can be.

## License

[MIT](LICENSE)
