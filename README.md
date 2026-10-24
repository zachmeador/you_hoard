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

1. **Copy TubeArchivist's metadata somewhere safe first.** Metadata for videos that have disappeared from YouTube exists only in its Elasticsearch data. Keep the backup zips from TubeArchivist's `cache/backup` folder, plus a copy of its Elasticsearch volume.
2. Point `MEDIA_DIR` (or the `/media` mount) at TubeArchivist's media folder, or at a folder that contains it.
3. Preview the import. It is a dry run and changes nothing:

   ```sh
   uv run python -m app import-tubearchivist --backup /path/to/ta_backup.zip --ta-cache /path/to/ta/cache
   ```

   Add `--ta-media <folder>` if the TubeArchivist media folder is a subfolder of `MEDIA_DIR`. With Docker: `docker compose exec youhoard python -m app import-tubearchivist …`. A live Elasticsearch works too: `--es-url http://host:9200 --es-password …`.
4. Run it again with `--apply`. Files stay where they are. It adds channels, videos (watched state, removed-from-YouTube flag), subscribed channels and playlists (set to download only new uploads), the ignore list, `.info.json` sidecars with comments, and thumbnails from the cache.
5. Optionally add `--organize` to rename files into YouHoard's readable layout. Renames happen on the same filesystem; nothing is copied or re-downloaded.

## Other commands

```sh
uv run python -m app rescan                  # reconcile the database with the media folder
uv run python -m app reset-password <user>   # set a new password
```

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
npm run check && npm run build
```

Tests run the real API against temporary SQLite databases and media folders, with a fake YouTube in place of yt-dlp. They do not prove compatibility with current YouTube; that needs a live check.

## License

MIT
