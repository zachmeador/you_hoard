"""One metadata insertion path for individual videos and discovered videos."""

import re
from datetime import datetime

from app.core.database import Database
from app.core.metadata import VideoType, classify_video_type


def upload_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").isoformat()
    except (ValueError, TypeError):
        return value


async def save_video(
    db: Database, info: dict, video_type: VideoType | None = None
) -> tuple[int, bool]:
    youtube_id = info.get("id", "")
    channel_id = info.get("channel_id")
    if not re.fullmatch(r"[\w-]{11}", youtube_id, re.ASCII) or not channel_id:
        raise ValueError(
            "Expected a YouTube video with uploader metadata, not a channel or playlist"
        )
    if not re.fullmatch(r"[\w-]+", channel_id, re.ASCII):
        raise ValueError("Invalid uploader ID")
    async with db.get_db() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        await conn.execute(
            "INSERT INTO channels (youtube_id, name) VALUES (?, ?) ON CONFLICT(youtube_id) DO NOTHING",
            (channel_id, info.get("channel") or info.get("uploader") or "Unknown Channel"),
        )
        cursor = await conn.execute("SELECT id FROM channels WHERE youtube_id = ?", (channel_id,))
        channel = await cursor.fetchone()
        cursor = await conn.execute(
            """INSERT INTO videos (youtube_id, channel_id, title, description, duration,
                upload_date, view_count, like_count, video_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(youtube_id) DO NOTHING""",
            (
                youtube_id,
                channel["id"],
                info.get("title") or "Unknown Title",
                info.get("description"),
                int(info["duration"]) if info.get("duration") is not None else None,
                upload_date(info.get("upload_date")),
                info.get("view_count"),
                info.get("like_count"),
                video_type or classify_video_type(info),
            ),
        )
        created = cursor.rowcount == 1
        cursor = await conn.execute("SELECT id FROM videos WHERE youtube_id = ?", (youtube_id,))
        video = await cursor.fetchone()
        await conn.commit()
        return video["id"], created
