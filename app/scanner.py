"""Library rescan: reconcile the database with the media files on disk."""

import asyncio
import json
import os
import threading
from pathlib import Path
from typing import Any

from app import layout
from app.config import config
from app.db import fetch_one, from_timestamp
from app.jobs import JobRunner
from app.library import ensure_video, record_archived, save_video_info, upsert_channel
from app.youtube import Cancelled

BATCH = 500


def find_media(root: Path) -> tuple[dict[str, Path], int]:
    """Map YouTube IDs to media files under root, skipping hidden folders."""
    found: dict[str, Path] = {}
    duplicates = 0
    for directory, folders, files in os.walk(root):
        folders[:] = sorted(folder for folder in folders if not folder.startswith("."))
        for name in sorted(files):
            path = Path(directory, name)
            youtube_id = layout.video_id_from_media(path)
            if youtube_id is None:
                continue
            if youtube_id in found:
                duplicates += 1
            else:
                found[youtube_id] = path
    return found, duplicates


def channel_from_folder(folder: str) -> tuple[str, str] | None:
    """(channel id, name) from "<name> [<id>]" or TubeArchivist's bare "<id>" folders."""
    if folder.endswith("]") and " [" in folder:
        name, _, channel_id = folder[:-1].rpartition(" [")
        if layout.CHANNEL_ID.fullmatch(channel_id):
            return channel_id, name
    if folder.startswith("UC") and layout.CHANNEL_ID.fullmatch(folder):
        return folder, folder
    return None


async def run_scan(
    runner: JobRunner, job: dict[str, Any], cancel: threading.Event
) -> dict[str, Any]:
    db = runner.db
    root = config.media_root
    found, duplicates = await asyncio.to_thread(find_media, root) if root.is_dir() else ({}, 0)
    result = {
        "files": len(found),
        "added": 0,
        "relinked": 0,
        "missing": 0,
        "duplicates": duplicates,
    }

    archived = await db.fetch_all(
        "SELECT id, youtube_id, media_path FROM videos WHERE media_path IS NOT NULL"
    )
    linked: set[str] = set()
    for start in range(0, len(archived), BATCH):
        if cancel.is_set():
            raise Cancelled("Cancelled")
        async with db.transaction() as conn:
            for video in archived[start : start + BATCH]:
                path = found.get(video["youtube_id"])
                try:
                    current = layout.media_file(video["media_path"], video["youtube_id"])
                except layout.PathError:
                    current = None
                if current is not None and current.is_file():
                    linked.add(video["youtube_id"])
                elif path is not None:
                    await conn.execute(
                        "UPDATE videos SET media_path = ?, media_size = ? WHERE id = ?",
                        (layout.relative(path), path.stat().st_size, video["id"]),
                    )
                    linked.add(video["youtube_id"])
                    result["relinked"] += 1
                else:
                    await conn.execute(
                        "UPDATE videos SET media_path = NULL, media_size = NULL WHERE id = ?",
                        (video["id"],),
                    )
                    result["missing"] += 1

    unlinked = [
        (youtube_id, path) for youtube_id, path in found.items() if youtube_id not in linked
    ]
    for start in range(0, len(unlinked), BATCH):
        if cancel.is_set():
            raise Cancelled("Cancelled")
        batch = unlinked[start : start + BATCH]
        infos = await asyncio.to_thread(lambda items=batch: [_read_info(path) for _, path in items])
        async with db.transaction() as conn:
            for (youtube_id, path), info in zip(batch, infos, strict=True):
                if info and info.get("id") == youtube_id:
                    video_id, _ = await save_video_info(conn, info)
                else:
                    channel = channel_from_folder(path.parent.name)
                    channel_id = await upsert_channel(conn, *channel) if channel else None
                    video_id = await ensure_video(
                        conn, youtube_id, _title(path), channel_id=channel_id
                    )
                    if channel_id:
                        await conn.execute(
                            "UPDATE videos SET channel_id = coalesce(channel_id, ?) WHERE id = ?",
                            (channel_id, video_id),
                        )
                row = await fetch_one(
                    conn, "SELECT media_path FROM videos WHERE id = ?", (video_id,)
                )
                if row["media_path"] is None:
                    stat = path.stat()
                    await record_archived(
                        conn,
                        video_id,
                        layout.relative(path),
                        stat.st_size,
                        (info or {}).get("width"),
                        (info or {}).get("height"),
                        archived_at=from_timestamp(stat.st_mtime),
                    )
                    result["added"] += 1
    return result


def _read_info(media: Path) -> dict[str, Any] | None:
    path = layout.info_for(media)
    if path is None:
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _title(media: Path) -> str:
    stem = layout.BRACKETED_ID.sub("", media.stem).strip()
    if len(stem) > 11 and layout.DATE.fullmatch(stem[:10]):
        stem = stem[10:].strip()
    return stem or media.stem
