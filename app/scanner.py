"""Library rescan: reconcile the database with the media files on disk."""

import asyncio
import json
import os
import threading
from pathlib import Path
from typing import Any

import aiosqlite

from app import layout
from app.artwork import AVATAR_FILE, BANNER_FILE
from app.config import config
from app.db import Database, fetch_one, from_timestamp, loads
from app.jobs import JobRunner, Refused
from app.library import archive_facts, ensure_video, record_archived, save_video_info
from app.youtube import Cancelled

BATCH = 500
# A rescan refuses to mark more than this many videos missing, or more than half the library,
# unless forced.
MISSING_LIMIT = 10


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
        if layout.YOUTUBE_CHANNEL_ID.fullmatch(channel_id):
            return channel_id, name
    if layout.YOUTUBE_CHANNEL_ID.fullmatch(folder):
        return folder, folder
    return None


async def folder_channel(conn: aiosqlite.Connection, folder: str) -> int | None:
    """The channel a folder belongs to, created from its name only if unknown."""
    parsed = channel_from_folder(folder)
    if parsed is None:
        return None
    await conn.execute("INSERT OR IGNORE INTO channels (youtube_id, name) VALUES (?, ?)", parsed)
    row = await fetch_one(conn, "SELECT id FROM channels WHERE youtube_id = ?", (parsed[0],))
    return row["id"]


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
    force = (loads(job.get("options")) or {}).get("force")
    missing = sum(1 for video in archived if video["youtube_id"] not in found)
    if missing > max(MISSING_LIMIT, len(archived) // 2) and not force:
        # An unmounted or mistyped media folder looks like a library whose files all vanished.
        raise Refused(
            f"Rescan stopped: {missing:,} of {len(archived):,} archived videos aren't in the "
            f"media folder ({root}). Nothing was changed. If the folder is right and those files "
            "really are gone, rescan anyway."
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
                    channel_id = await folder_channel(conn, path.parent.name)
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
                        facts=archive_facts(info) if info else None,
                    )
                    result["added"] += 1
    await link_channel_art(db)
    return result


async def link_channel_art(db: Database) -> None:
    """Point channels at the avatar and banner files in their folders."""
    folders = await asyncio.to_thread(layout.channel_folders)
    for channel in await db.fetch_all(
        "SELECT id, youtube_id, avatar_path, banner_path FROM channels"
    ):
        folder = folders.get(channel["youtube_id"])
        paths = {}
        for column, filename in (("avatar_path", AVATAR_FILE), ("banner_path", BANNER_FILE)):
            path = folder / filename if folder else None
            found = layout.relative(path) if path and path.is_file() else None
            if found != channel[column]:
                paths[column] = found
        if paths:
            assignments = ", ".join(f"{column} = ?" for column in paths)
            await db.execute(
                f"UPDATE channels SET {assignments} WHERE id = ?", (*paths.values(), channel["id"])
            )


def _read_info(media: Path) -> dict[str, Any] | None:
    path = layout.info_for(media)
    if path is None:
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _title(media: Path) -> str:
    if legacy := layout.LEGACY_TA_NAME.match(media.stem):
        return media.stem[legacy.end() :].replace("_", " ").strip() or media.stem
    stem = layout.BRACKETED_ID.sub("", media.stem).strip()
    if len(stem) > 11 and layout.DATE.fullmatch(stem[:10]):
        stem = stem[10:].strip()
    return stem or media.stem
