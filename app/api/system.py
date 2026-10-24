"""Runtime settings, system status and library maintenance."""

import asyncio
import re
import shutil
import subprocess
from functools import cache
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from app import __version__
from app.api.deps import get_db, get_runner, get_settings, get_youtube
from app.config import config
from app.db import Database
from app.jobs import JobRunner
from app.settings import Settings
from app.youtube import QUALITIES, YouTube

router = APIRouter()
CHECK_INTERVALS = [1, 3, 6, 12, 24, 72, 168]


class SettingsUpdate(BaseModel):
    default_quality: Literal[tuple(QUALITIES)] | None = None
    subtitle_languages: list[str] | None = None
    download_comments: bool | None = None
    max_concurrent_downloads: int | None = Field(None, ge=1, le=8)
    check_interval_hours: int | None = Field(None, ge=1, le=720)

    @field_validator("subtitle_languages")
    @classmethod
    def languages(cls, value: list[str] | None) -> list[str] | None:
        return [lang.strip() for lang in value if lang.strip()] if value is not None else None


async def settings_out(settings: Settings) -> dict:
    return {
        **(await settings.all()),
        "options": {
            "qualities": QUALITIES,
            "check_intervals": CHECK_INTERVALS,
            "policies": ["none", "new", "recent", "all"],
            "content_types": ["video", "short", "live"],
        },
    }


@router.get("/settings")
async def get_settings_values(settings: Settings = Depends(get_settings)):
    return await settings_out(settings)


@router.put("/settings")
async def update_settings(
    body: SettingsUpdate,
    settings: Settings = Depends(get_settings),
    runner: JobRunner = Depends(get_runner),
):
    values = {key: value for key, value in body.model_dump().items() if value is not None}
    await settings.update(values)
    runner.wake()
    return await settings_out(settings)


@cache
def ffmpeg_version() -> str | None:
    path = shutil.which("ffmpeg")
    if not path:
        return None
    try:
        output = subprocess.run(
            [path, "-version"], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    match = re.match(r"ffmpeg version (\S+)", output)
    return match.group(1) if match else "unknown"


@router.get("/system")
async def system_status(db: Database = Depends(get_db), youtube: YouTube = Depends(get_youtube)):
    versions = await asyncio.to_thread(youtube.versions)
    ffmpeg = await asyncio.to_thread(ffmpeg_version)
    try:
        usage = await asyncio.to_thread(shutil.disk_usage, config.media_root)
        disk = {"total": usage.total, "used": usage.used, "free": usage.free}
    except OSError:
        disk = None
    library = await db.fetch_one(
        """SELECT count(*) AS videos, count(media_path) AS archived,
                  coalesce(sum(media_size), 0) AS archived_size,
                  count(unavailable_at) AS unavailable,
                  (SELECT count(*) FROM channels) AS channels,
                  (SELECT count(*) FROM subscriptions) AS subscriptions
           FROM videos WHERE deleted_at IS NULL"""
    )
    queue = await db.fetch_one(
        """SELECT count(CASE WHEN status = 'queued' THEN 1 END) AS queued,
                  count(CASE WHEN status = 'running' THEN 1 END) AS running,
                  count(CASE WHEN status = 'failed' THEN 1 END) AS failed
           FROM jobs"""
    )
    return {
        "version": __version__,
        "yt_dlp": versions["yt_dlp"],
        "ffmpeg": ffmpeg,
        "js_runtime": versions["js_runtime"],
        "cookies": bool(config.YTDLP_COOKIE_FILE and config.YTDLP_COOKIE_FILE.is_file()),
        "media_dir": str(config.media_root),
        "disk": disk,
        "library": library,
        "queue": queue,
    }


@router.post("/library/rescan", status_code=202)
async def rescan_library(runner: JobRunner = Depends(get_runner)):
    return {"job_id": await runner.enqueue("scan", priority=1)}
