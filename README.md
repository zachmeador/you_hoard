# YouHoard

A single-user, self-hosted YouTube archive. Follow channels and playlists, save individual videos, and browse and play the archive in your browser. It can import an existing TubeArchivist library without re-downloading anything.

FastAPI, SQLite, yt-dlp and ffmpeg in one process. No Elasticsearch, Redis or YouTube API key. Every archived video sits next to a readable `.info.json`, thumbnail and subtitles, so the files stay useful without the app. See [DESIGN.md](DESIGN.md) for how it works and [ROADMAP.md](ROADMAP.md) for what is next.

**Status:** in development. Use it on a trusted LAN or tailnet; it is not hardened for the public internet.

## Run with Docker

```sh
docker compose up -d --build
```

Edit [compose.yaml](compose.yaml) first: mount your archive folder at `/media` and set `user:` to the owner of those files. Open `http://localhost:8000` and create your account. `YTDLP_UPDATE_ON_START=1` upgrades yt-dlp on each start, since YouTube regularly breaks older releases.

## Run from source

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 22+ and ffmpeg. yt-dlp's JavaScript runtime (Deno) is installed with the Python dependencies.

```sh
uv sync
npm ci
npm run dev
```

Open `http://localhost:5173`. The API runs on port 8000. For a production-style run, `npm run build`, then `uv run uvicorn main:app --host 0.0.0.0 --port 8000` and open port 8000. Configuration is in [.env.example](.env.example). Run a single process (no multiple Uvicorn workers).

## Moving from TubeArchivist

1. **Make a fresh backup.** Start TubeArchivist once; it does not need to download anything. Then use Settings → Actions → Backup. That writes a zip of all its metadata to its `cache/backup` folder. Stop it again. For extra safety, also keep a copy of its Elasticsearch volume: metadata for videos that have since left YouTube exists nowhere else.
2. **Point YouHoard at the files.** Set `MEDIA_DIR` (or the `/media` mount) to TubeArchivist's media folder, or to a folder containing it on the same filesystem.
3. **Preview the import.** This is a dry run and writes nothing:

   ```sh
   uv run python -m app import-tubearchivist --backup /path/to/ta/cache/backup/ta_backup-….zip
   ```

   - Add `--ta-media <folder>` when TubeArchivist's media folder is a subfolder of `MEDIA_DIR`.
   - The cache folder, used for thumbnails, is found next to the backup; otherwise pass `--ta-cache`.
   - With Docker: `docker compose exec youhoard python -m app import-tubearchivist …`.
   - The importer can also read a running Elasticsearch: `--es-url http://host:9200` with `TA_ES_PASSWORD` set.

   Read the counts and warnings: videos matched to files, missing files, orphans, subscriptions, the ignore list and comments.
4. **Apply it.** Run the same command with `--apply`. Files stay exactly where they are, and older TubeArchivist file names work too. It adds:
   - channels and videos, with watched state and the removed-from-YouTube flag;
   - subscribed channels (keeping the tabs you followed) and playlists, set to download only new uploads;
   - the ignore list;
   - an `.info.json` with comments next to each video, plus its thumbnail from the cache.

   Running it again changes nothing.
5. **Optionally organize.** Once you trust it, run with `--apply --organize` to rename files into YouHoard's readable layout. It uses same-filesystem renames, never overwrites, and never re-downloads.

## Other commands

```sh
uv run python -m app rescan                  # reconcile the database with the media folder
uv run python -m app backup <file>           # copy the database safely while it runs
uv run python -m app reset-password <user>   # set a new password
```

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
npm run check && npm run build
```

Tests run the real API against temporary SQLite databases and media folders, with a fake YouTube in place of yt-dlp. They do not prove compatibility with current YouTube; that needs a live check.

The end-to-end browser test is opt-in. It drives the built frontend in your installed Google Chrome, or in the Chromium at `PLAYWRIGHT_CHROMIUM_EXECUTABLE`:

```sh
npm run build
RUN_BROWSER_TESTS=1 uv run --with playwright python -m pytest -m browser
```

## License

MIT
