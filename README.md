# YouHoard

A single-user YouTube archive built with FastAPI, SQLite, Svelte and yt-dlp. Follow channels/playlists, choose whether to keep regular videos, Shorts or livestream replays, or paste an individual video URL.

No Redis or Elasticsearch. Media and metadata are stored as ordinary files.

**In development.** The recovery branch repairs core workflows; it is not yet a verified TubeArchivist replacement. See the [roadmap](ROADMAP.md) and [known gaps](docs/revival.md).

## Run locally

Requires Python 3.11+, Node.js 20+, [uv](https://docs.astral.sh/uv/), and ffmpeg on `PATH`.

```sh
uv sync --frozen
npm ci
npm run dev
```

Open `http://localhost:5173` and create your login on first run. There are no default credentials. The backend runs on port 8000. Optional environment settings are shown in [.env.example](.env.example).

For a built frontend:

```sh
npm run build
uv run uvicorn main:app --host 127.0.0.1 --port 8000
```

Open `http://localhost:8000`. Run one application process, not multiple Uvicorn workers. Keep it on a trusted LAN/tailnet; public deployment is not supported.

## Checks

```sh
uv run pytest
uv run ruff check app main.py tests
uv run ruff format --check app main.py tests
npm run check
npm run build
```

Integration tests use temporary databases/media storage and a YouTube test double. They do not verify current YouTube compatibility.

For the optional browser test, build the frontend, install Chromium with `uv run --with playwright python -m playwright install chromium`, then run:

```sh
RUN_BROWSER_TESTS=1 uv run --with playwright python -m pytest -m browser
```

Set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` to use an existing Chrome/Chromium binary. The test covers setup, subscription filters, downloads, local playback and mobile navigation.

See [subscription behavior](docs/subscriptions.md), [architecture](DESIGN.md), and the API at `/docs`.

## License

MIT
