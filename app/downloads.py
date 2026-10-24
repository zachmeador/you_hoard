"""The download job: fetch one video into the library with its sidecars."""

import asyncio
import shutil
import threading
from typing import Any

from app import layout
from app.db import fetch_one, loads, now
from app.jobs import JobRunner, Progress
from app.library import record_archived, save_video_info, write_info_json
from app.youtube import Cancelled, DownloadRequest, Unavailable


async def run_download(
    runner: JobRunner, job: dict[str, Any], cancel: threading.Event
) -> dict[str, Any]:
    db = runner.db
    video = await db.fetch_one("SELECT * FROM videos WHERE id = ?", (job["video_id"],))
    if video["media_path"]:
        return {"skipped": "Already archived"}
    defaults = await runner.settings.all()
    options = loads(job["options"]) or {}

    def choose(key: str, default_key: str) -> Any:
        value = options.get(key)
        return defaults[default_key] if value is None else value

    youtube_id = video["youtube_id"]
    request = DownloadRequest(
        youtube_id=youtube_id,
        workdir=layout.incomplete_dir(youtube_id),
        quality=choose("quality", "default_quality"),
        subtitle_languages=choose("subtitle_languages", "subtitle_languages"),
        comments=choose("download_comments", "download_comments"),
    )
    progress = runner.progress.setdefault(job["id"], Progress())
    try:
        info = await runner.youtube.download(request, progress.update, cancel)
    except Cancelled:
        if not runner.stopping:
            await asyncio.to_thread(shutil.rmtree, request.workdir, True)
        raise
    except Unavailable:
        await db.execute(
            "UPDATE videos SET unavailable_at = coalesce(unavailable_at, ?) WHERE id = ?",
            (now(), video["id"]),
        )
        raise

    progress.update({"status": "processing"})
    async with db.transaction() as conn:
        await save_video_info(conn, info)
        channel = await fetch_one(
            conn,
            "SELECT c.youtube_id, c.name FROM videos v JOIN channels c ON c.id = v.channel_id "
            "WHERE v.id = ?",
            (video["id"],),
        )
        refreshed = await fetch_one(conn, "SELECT * FROM videos WHERE id = ?", (video["id"],))

    def place() -> tuple[str, int]:
        write_info_json(request.workdir / "media.info.json", info)
        directory = layout.channel_dir(
            channel["youtube_id"] if channel else "unknown", channel["name"] if channel else None
        )
        existing = layout.existing_media(directory, youtube_id)
        basename = (
            existing.stem
            if existing
            else layout.video_basename(youtube_id, refreshed["title"], refreshed["published_at"])
        )
        media = layout.place_download(request.workdir, directory, basename)
        return layout.relative(media), media.stat().st_size

    media_path, size = await asyncio.to_thread(place)
    async with db.transaction() as conn:
        await record_archived(
            conn, video["id"], media_path, size, info.get("width"), info.get("height")
        )
        await conn.execute("UPDATE videos SET unavailable_at = NULL WHERE id = ?", (video["id"],))
    return {"media_path": media_path, "media_size": size, "height": info.get("height")}
