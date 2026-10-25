"""Channels and videos: metadata from yt-dlp, derived status, and archive records."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from app.db import dumps, fetch_one, from_timestamp, now
from app.tracks import file_audio_languages, file_codecs

AVAILABILITIES = {
    "public",
    "unlisted",
    "private",
    "needs_auth",
    "subscriber_only",
    "premium_only",
}

VIDEO_SELECT = """
SELECT v.*, s.status, s.job_id, s.job_status, s.job_error,
       c.youtube_id AS channel_youtube_id, c.name AS channel_name
FROM videos v
JOIN video_status s ON s.video_id = v.id
LEFT JOIN channels c ON c.id = v.channel_id
"""

# Keys dropped from .info.json sidecars: signed URLs that expire, and bulky format tables.
INFO_DROP = {
    "formats",
    "requested_formats",
    "requested_downloads",
    "requested_subtitles",
    "automatic_captions",
    "subtitles",
    "thumbnails",
    "http_headers",
    "url",
    "manifest_url",
    "fragments",
    "downloader_options",
    "filepath",
    "filename",
    "_filename",
    "_format_sort_fields",
    "_has_drm",
    "_version",
}


def published_at(info: dict[str, Any]) -> str | None:
    """YYYY-MM-DDTHH:MM:SSZ when YouTube gives the exact upload time, else YYYY-MM-DD."""
    timestamp = info.get("timestamp")
    if isinstance(timestamp, int | float) and not isinstance(timestamp, bool):
        try:
            return from_timestamp(timestamp)
        except (OverflowError, OSError, ValueError):
            pass
    for key in ("upload_date", "release_date"):
        value = str(info.get(key) or "")
        if len(value) == 8 and value.isdigit():
            return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    if isinstance(info.get("release_timestamp"), int | float):
        return datetime.fromtimestamp(info["release_timestamp"], UTC).date().isoformat()
    return None


def _number(value: Any, kind: type = int) -> Any:
    if isinstance(value, int | float) and not isinstance(value, bool) and value >= 0:
        return kind(value)
    return None


def archive_facts(info: dict[str, Any]) -> dict[str, Any]:
    """Facts about a downloaded file, from the final yt-dlp info or from our own sidecar."""
    own = info.get("_youhoard") or {}
    vcodec, acodec = file_codecs(info)
    return {
        "fps": _number(info.get("fps"), float),
        "vcodec": vcodec,
        "acodec": acodec or own.get("acodec"),
        "dynamic_range": info.get("dynamic_range") or None,
        "audio_languages": own.get("audio_languages") or file_audio_languages(info),
        "subtitle_tracks": own.get("subtitles"),
    }


def classify(info: dict[str, Any]) -> str:
    if info.get("was_live") or info.get("live_status") in ("was_live", "post_live", "is_live"):
        return "live"
    url = str(info.get("original_url") or info.get("webpage_url") or "")
    if "/shorts/" in url:
        return "short"
    width, height = info.get("width") or 0, info.get("height") or 0
    if 0 < (info.get("duration") or 0) <= 180 and 0 < width < height:
        return "short"
    return "video"


def quality_label(width: int | None, height: int | None) -> str | None:
    sides = [side for side in (width, height) if side]
    return f"{min(sides)}p" if sides else None


def slim_info(info: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in info.items() if key not in INFO_DROP}


def write_info_json(path: Path, info: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(slim_info(info), ensure_ascii=False, indent=1), "utf-8")
    temporary.replace(path)


async def upsert_channel(
    conn: aiosqlite.Connection,
    youtube_id: str,
    name: str | None = None,
    handle: str | None = None,
    description: str | None = None,
    subscriber_count: int | None = None,
    verified: bool | None = None,
) -> int:
    row = await fetch_one(
        conn,
        """INSERT INTO channels (youtube_id, name, handle, description, subscriber_count, verified)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (youtube_id) DO UPDATE SET
               name = coalesce(?, name),
               handle = coalesce(excluded.handle, handle),
               description = coalesce(excluded.description, description),
               subscriber_count = coalesce(excluded.subscriber_count, subscriber_count),
               verified = coalesce(?, verified),
               updated_at = ?
           RETURNING id""",
        (
            youtube_id,
            name or youtube_id,
            handle,
            description,
            subscriber_count,
            bool(verified),
            name,
            None if verified is None else int(verified),
            now(),
        ),
    )
    return row["id"]


async def channel_from_info(conn: aiosqlite.Connection, info: dict[str, Any]) -> int | None:
    channel_id = info.get("channel_id")
    if not channel_id:
        return None
    handle = info.get("uploader_id")
    return await upsert_channel(
        conn,
        channel_id,
        info.get("channel") or info.get("uploader"),
        handle=handle if isinstance(handle, str) and handle.startswith("@") else None,
        subscriber_count=info.get("channel_follower_count"),
        verified=True if info.get("channel_is_verified") else None,
    )


async def save_video_info(
    conn: aiosqlite.Connection, info: dict[str, Any], video_type: str | None = None
) -> tuple[int, bool]:
    """Insert or refresh a video's metadata from a yt-dlp info dict. Returns (id, created)."""
    channel_id = await channel_from_info(conn, info)
    duration = info.get("duration")
    availability = info.get("availability")
    values = {
        "title": info.get("title") or info.get("fulltitle") or info["id"],
        "description": info.get("description"),
        "duration": int(duration) if isinstance(duration, int | float) else None,
        "published_at": published_at(info),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "availability": availability if availability in AVAILABILITIES else None,
        "age_limit": _number(info.get("age_limit")),
        "comment_count": _number(info.get("comment_count")),
    }
    existing = await fetch_one(
        conn, "SELECT id, video_type FROM videos WHERE youtube_id = ?", (info["id"],)
    )
    if existing:
        kind = video_type or ("live" if classify(info) == "live" else existing["video_type"])
        await conn.execute(
            """UPDATE videos SET channel_id = coalesce(?, channel_id), title = ?, description = ?,
                   duration = coalesce(?, duration), published_at = coalesce(?, published_at),
                   view_count = ?, like_count = ?, availability = coalesce(?, availability),
                   age_limit = coalesce(?, age_limit), comment_count = coalesce(?, comment_count),
                   video_type = ?, updated_at = ?
               WHERE id = ?""",
            (channel_id, *values.values(), kind, now(), existing["id"]),
        )
        return existing["id"], False
    cursor = await conn.execute(
        """INSERT INTO videos (youtube_id, channel_id, title, description, duration, published_at,
               view_count, like_count, availability, age_limit, comment_count, video_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (info["id"], channel_id, *values.values(), video_type or classify(info)),
    )
    return cursor.lastrowid, True


async def ensure_video(
    conn: aiosqlite.Connection,
    youtube_id: str,
    title: str | None,
    video_type: str = "video",
    channel_id: int | None = None,
    duration: int | None = None,
) -> int:
    """A library row for a video known only from a listing; metadata fills in on download."""
    await conn.execute(
        """INSERT OR IGNORE INTO videos (youtube_id, channel_id, title, duration, video_type)
           VALUES (?, ?, ?, ?, ?)""",
        (youtube_id, channel_id, title or youtube_id, duration, video_type),
    )
    row = await fetch_one(conn, "SELECT id FROM videos WHERE youtube_id = ?", (youtube_id,))
    return row["id"]


async def record_archived(
    conn: aiosqlite.Connection,
    video_id: int,
    media_path: str,
    media_size: int,
    width: int | None = None,
    height: int | None = None,
    archived_at: str | None = None,
    *,
    facts: dict[str, Any] | None = None,
) -> None:
    facts = facts or {}
    await conn.execute(
        """UPDATE videos SET media_path = ?, media_size = ?, width = ?, height = ?,
               fps = ?, vcodec = ?, acodec = ?, dynamic_range = ?, audio_languages = ?,
               subtitle_tracks = ?, archived_at = ?, deleted_at = NULL, updated_at = ?
           WHERE id = ?""",
        (
            media_path,
            media_size,
            width,
            height,
            facts.get("fps"),
            facts.get("vcodec"),
            facts.get("acodec"),
            facts.get("dynamic_range"),
            dumps(facts.get("audio_languages") or None),
            dumps(facts.get("subtitle_tracks")),
            archived_at or now(),
            now(),
            video_id,
        ),
    )
