"""YouHoard: the API, the job runner and the built frontend in one process."""

import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import auth, channels, jobs, subscriptions, system, videos
from app.auth import current_user
from app.config import config
from app.db import Database
from app.jobs import JobRunner
from app.settings import Settings
from app.youtube import YouTube

DIST = Path(__file__).resolve().parent / "app" / "static" / "dist"


def setup_logging() -> None:
    config.log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = logging.handlers.RotatingFileHandler(
        config.log_dir / "youhoard.log", maxBytes=10_000_000, backupCount=5, encoding="utf-8"
    )
    console = logging.StreamHandler()
    root = logging.getLogger()
    root.handlers = []
    for handler in (file_handler, console):
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(config.LOG_LEVEL.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)


def create_app(youtube: YouTube | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging()
        config.media_root.mkdir(parents=True, exist_ok=True)
        db = Database(config.database_path)
        await db.migrate()
        app.state.db = db
        app.state.settings = Settings(db)
        app.state.youtube = youtube or YouTube()
        app.state.runner = JobRunner(db, app.state.youtube, app.state.settings)
        await app.state.runner.start()
        try:
            yield
        finally:
            await app.state.runner.stop()

    app = FastAPI(title="YouHoard", version=__version__, lifespan=lifespan)
    protected = [Depends(current_user)]
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(videos.router, prefix="/api/videos", tags=["videos"], dependencies=protected)
    app.include_router(
        channels.router, prefix="/api/channels", tags=["channels"], dependencies=protected
    )
    app.include_router(
        subscriptions.router,
        prefix="/api/subscriptions",
        tags=["subscriptions"],
        dependencies=protected,
    )
    app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"], dependencies=protected)
    app.include_router(system.router, prefix="/api", tags=["system"], dependencies=protected)

    @app.get("/api/health", tags=["system"])
    async def health():
        return {"status": "ok"}

    if (DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        if path == "api" or path.startswith(("api/", "assets/")):
            raise HTTPException(status_code=404, detail="Not found")
        index = DIST / "index.html"
        if not index.is_file():
            raise HTTPException(
                status_code=503,
                detail="Frontend not built: run `npm run build`, or use `npm run dev`",
            )
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True, reload_dirs=["app"])
