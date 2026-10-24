"""YouHoard's API, worker lifecycle and production frontend."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.endpoints import auth, channels, downloads, subscriptions, videos
from app.core.config import settings
from app.core.database import Database
from app.core.downloader import Downloader
from app.core.logging_setup import setup_logging
from app.core.recovery import RecoveryManager
from app.core.scheduler import SubscriptionScheduler

ROOT = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings.get_storage_path().mkdir(parents=True, exist_ok=True)
    db = Database(settings.DATABASE_PATH)
    await db.init_db()
    app.state.db = db
    recovery = RecoveryManager(db)
    if await recovery.check_database_empty():
        result = await recovery.scan_and_recover()
        logger.info("Recovered %s videos from local storage", result.videos_created)
    downloader = Downloader(db)
    app.state.downloader = downloader
    scheduler = SubscriptionScheduler(db, downloader)
    app.state.scheduler = scheduler
    await downloader.start()
    await scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()
        await downloader.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="YouHoard", version="0.1.0", lifespan=lifespan)
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(videos.router, prefix="/api/videos", tags=["videos"])
    app.include_router(channels.router, prefix="/api/channels", tags=["channels"])
    app.include_router(subscriptions.router, prefix="/api/subscriptions", tags=["subscriptions"])
    app.include_router(downloads.router, prefix="/api/downloads", tags=["downloads"])
    app.mount("/app/static/css", StaticFiles(directory=ROOT / "app/static/css"), name="styles")
    # Build before starting production. Never expose storage or cookie/info sidecars directly.
    dist = ROOT / "app/static/dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/api/health")
    async def health_check():
        return {"status": "healthy", "message": "YouHoard is running"}

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path == "api" or full_path.startswith(
            ("api/", "storage/", "assets/", "app/", "src/")
        ):
            raise HTTPException(status_code=404, detail="Not found")
        index = dist / "index.html"
        if not index.exists():
            raise HTTPException(
                status_code=503,
                detail="Frontend not built. Run npm run build, or use Vite on port 5173.",
            )
        return FileResponse(index)

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)
