"""The extras job: fetch the subtitles and live chat a download missed, next to the media."""

import asyncio
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from app import layout
from app.db import dumps, fetch_one, loads, now
from app.downloads import job_options
from app.jobs import JobRunner
from app.library import write_info_json
from app.tracks import LIVE_CHAT, TRANSLATED
from app.youtube import (
    Blocked,
    DownloadRequest,
    Extras,
    YouTubeError,
)


def merged(existing: Any, saved: list[dict[str, str]]) -> list[dict[str, str]]:
    """Subtitle tracks by language, the ones already recorded first."""
    tracks = {t["lang"]: t for t in existing or () if isinstance(t, dict) and t.get("lang")}
    for track in saved:
        tracks.setdefault(track["lang"], track)
    return list(tracks.values())


def place(workdir: Path, media: Path, extras: Extras) -> bool:
    """Move what was fetched next to the media, under its basename. Returns whether the chat came
    with it. The folders are on one filesystem, so this is a rename."""
    for track in extras.saved:
        os.replace(
            workdir / f"media.{track.lang}.vtt", media.with_name(f"{media.stem}.{track.lang}.vtt")
        )
    chat = workdir / f"media.{LIVE_CHAT}.json"
    if chat.is_file():
        os.replace(chat, media.with_name(f"{media.stem}.{LIVE_CHAT}.json"))
        return True
    return False


def record_in_sidecar(media: Path, saved: list[dict[str, str]]) -> None:
    """Add the tracks to `_youhoard.subtitles` in the .info.json beside the media, which is what a
    rescan rebuilds the video's subtitle tracks from."""
    path = layout.info_for(media)
    if path is None:
        return
    try:
        info = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(info, dict):
        return
    own = info.setdefault("_youhoard", {})
    own["subtitles"] = merged(own.get("subtitles"), saved)
    write_info_json(path, info)


def missing_words(extras: Extras) -> str:
    """What is still missing, as the error that retrying will show."""
    wanted = [track.lang for track in extras.missing if track.source != TRANSLATED]
    if extras.chat_missing:
        wanted.append("live chat")
    return f"YouTube didn't serve {', '.join(wanted)}"


async def run_extras(
    runner: JobRunner, job: dict[str, Any], cancel: threading.Event
) -> dict[str, Any]:
    db = runner.db
    video = await db.fetch_one("SELECT * FROM videos WHERE id = ?", (job["video_id"],))
    if not video["media_path"]:
        return {"skipped": "No longer archived"}
    try:
        media = layout.media_file(video["media_path"], video["youtube_id"])
    except layout.PathError:
        return {"skipped": "No longer archived"}
    if not media.is_file():
        return {"skipped": "The media file is missing"}

    options = await job_options(runner, job)
    youtube_id = video["youtube_id"]
    # Beside the download's folder, not in it, so a download of the same video can't collide.
    workdir = layout.incomplete_dir(youtube_id) / "extras"
    request = DownloadRequest(
        youtube_id=youtube_id,
        workdir=workdir,
        quality=None,
        subtitle_languages=options["subtitle_languages"],
        comments=False,
        auto_captions=options["auto_captions"],
        live_chat=options["live_chat"],
    )
    have = set(layout.subtitles_for(media))
    have_chat = layout.chat_for(media) is not None
    try:
        extras = await runner.youtube.fetch_extras(request, have, have_chat, cancel)
    except BaseException:
        await asyncio.to_thread(shutil.rmtree, workdir, True)
        raise

    saved = [track.as_dict() for track in extras.saved]

    def settle() -> bool:
        try:
            chat = place(workdir, media, extras)
            if saved:
                record_in_sidecar(media, saved)
            return chat
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    chat = await asyncio.to_thread(settle)
    if saved:
        async with db.transaction() as conn:
            row = await fetch_one(
                conn, "SELECT subtitle_tracks FROM videos WHERE id = ?", (video["id"],)
            )
            tracks = merged(loads(row["subtitle_tracks"]), saved)
            await conn.execute(
                "UPDATE videos SET subtitle_tracks = ?, updated_at = ? WHERE id = ?",
                (dumps(tracks), now(), video["id"]),
            )

    if extras.refused:
        raise Blocked(extras.refused)
    if extras.chat_missing or any(track.source != TRANSLATED for track in extras.missing):
        raise YouTubeError(missing_words(extras))
    return {
        "saved": [track.lang for track in extras.saved],
        "chat": chat,
        "missing": [track.lang for track in extras.missing],
    }
