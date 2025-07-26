# YouHoard

A youtube archiver app that cares about simplicity and feature richness.

`youhoard` uses sqlite, fastapi, and yt-dlp. No need to spin up redis, elasticsearch, kubernetes, or terraform a new data center just to have a webapp that makes yt archiving easier. 

## Current status

Version: 0.0.1

Very alpha, not worth trying unless you want to submit PRs.

Missing many features that I want, will be added over time. 

## Running It

For development:

```bash
# Install dependencies
uv sync
npm install

# Run both frontend and backend with combined logs
npm run dev
```

This runs the backend (FastAPI on port 8000) and frontend (Vite on port 5173) together with color-coded logs. 

## Is it vibe coded?

Yes.

## License

MIT