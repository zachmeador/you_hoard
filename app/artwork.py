"""Channel avatars and banners, kept as files in the channel folder so they outlive the app."""

import asyncio
import logging
from pathlib import Path

from app import layout
from app.db import Database
from app.youtube import Source, YouTube

logger = logging.getLogger(__name__)

AVATAR_FILE = "channel.jpg"
BANNER_FILE = "banner.jpg"
JPEG = b"\xff\xd8\xff"
# Channels whose art is being saved right now, so a check and a new subscription do not both fetch it.
saving: set[int] = set()


def write_image(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


async def first_image(youtube: YouTube, urls: list[str]) -> bytes | None:
    for url in urls:
        try:
            data = await youtube.fetch_image(url)
        except Exception as error:
            logger.warning("Could not fetch channel art: %s", error)
            continue
        if data.startswith(JPEG):
            return data
        logger.warning("Channel art was not a JPEG image: %s", url)
    return None


async def save_channel_art(db: Database, youtube: YouTube, channel_id: int, source: Source) -> None:
    """Save a channel's avatar and banner in its folder unless they are already there.

    A failure is logged and nothing more: art is never worth failing a check for.
    """
    if channel_id in saving:
        return
    saving.add(channel_id)
    try:
        folder = await asyncio.to_thread(layout.channel_dir, source.youtube_id, source.channel_name)
        wanted = {
            "avatar_path": (folder / AVATAR_FILE, source.avatars),
            "banner_path": (folder / BANNER_FILE, source.banners),
        }
        row = await db.fetch_one(
            "SELECT avatar_path, banner_path FROM channels WHERE id = ?", (channel_id,)
        )
        changed: dict[str, str] = {}
        for column, (path, urls) in wanted.items():
            if not await asyncio.to_thread(path.is_file):
                data = await first_image(youtube, urls) if urls else None
                if data is None:
                    continue
                await asyncio.to_thread(write_image, path, data)
            relative = layout.relative(path)
            if row and row[column] != relative:
                changed[column] = relative
        if changed:
            assignments = ", ".join(f"{column} = ?" for column in changed)
            await db.execute(
                f"UPDATE channels SET {assignments} WHERE id = ?", (*changed.values(), channel_id)
            )
    except Exception as error:
        logger.warning("Could not save art for channel %s: %s", source.youtube_id, error)
    finally:
        saving.discard(channel_id)
