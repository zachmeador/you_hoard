"""Runtime settings, system status and library maintenance."""

import asyncio
import re
import shutil
import subprocess
from functools import cache
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from app import __version__, trash
from app.api.deps import clean_languages, get_db, get_runner, get_settings, get_youtube
from app.config import config
from app.db import Database, now
from app.jobs import JobRunner
from app.languages import language_options
from app.settings import Settings
from app.youtube import QUALITIES, YouTube

router = APIRouter()
CHECK_INTERVALS = [1, 3, 6, 12, 24, 72, 168]
TRASH_DAYS = [0, 7, 30, 90]


class SettingsUpdate(BaseModel):
    default_quality: Literal[tuple(QUALITIES)] | None = None
    subtitle_languages: list[str] | None = None
    auto_captions: bool | None = None
    download_comments: bool | None = None
    audio_languages: list[str] | None = None
    live_chat: bool | None = None
    sponsorblock: bool | None = None
    max_concurrent_downloads: int | None = Field(None, ge=1, le=8)
    check_interval_hours: int | None = Field(None, ge=1, le=720)
    trash_days: int | None = Field(None, ge=0, le=365)

    @field_validator("subtitle_languages", "audio_languages")
    @classmethod
    def languages(cls, value: list[str] | None) -> list[str] | None:
        return clean_languages(value)


async def settings_out(settings: Settings) -> dict:
    return {
        **(await settings.all()),
        "options": {
            "qualities": QUALITIES,
            "check_intervals": CHECK_INTERVALS,
            "trash_days": TRASH_DAYS,
            "policies": ["none", "new", "recent", "all"],
            "content_types": ["video", "short", "live"],
            "languages": language_options(),
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
        """SELECT count(CASE WHEN status = 'queued' AND coalesce(run_after, '') <= ? THEN 1 END)
                      AS queued,
                  count(CASE WHEN status = 'queued' AND run_after > ? THEN 1 END) AS waiting,
                  count(CASE WHEN status = 'running' THEN 1 END) AS running,
                  count(CASE WHEN status = 'failed' THEN 1 END) AS failed
           FROM jobs""",
        (now(), now()),
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
        "trash": await asyncio.to_thread(trash.summary),
    }


class Rescan(BaseModel):
    # Skip the check that stops a rescan from marking most of the library missing.
    force: bool = False


@router.post("/library/rescan", status_code=202)
async def rescan_library(body: Rescan | None = None, runner: JobRunner = Depends(get_runner)):
    options = {"force": True} if body and body.force else None
    return {"job_id": await runner.enqueue("scan", options=options, priority=1)}
