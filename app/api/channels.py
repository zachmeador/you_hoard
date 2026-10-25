"""Channels with library counts."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app import layout
from app.api.deps import art_url, get_db, not_found
from app.db import Database
from app.youtube import channel_url

router = APIRouter()

CHANNEL_SELECT = """
SELECT c.*,
       count(v.id) AS video_count,
       count(v.media_path) AS archived_count,
       coalesce(sum(v.media_size), 0) AS archived_size,
       (SELECT id FROM subscriptions s WHERE s.channel_id = c.id) AS subscription_id
FROM channels c
LEFT JOIN videos v ON v.channel_id = c.id AND v.deleted_at IS NULL
"""
SORTS = {
    "name": "c.name COLLATE NOCASE",
    "size": "archived_size DESC, c.name COLLATE NOCASE",
    "videos": "archived_count DESC, c.name COLLATE NOCASE",
}


def channel_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "youtube_id": row["youtube_id"],
        "name": row["name"],
        "handle": row["handle"],
        "description": row["description"],
        "subscriber_count": row["subscriber_count"],
        "verified": bool(row["verified"]),
        "avatar_url": art_url(row["id"], row["avatar_path"], "avatar"),
        "banner_url": art_url(row["id"], row["banner_path"], "banner"),
        "video_count": row["video_count"],
        "archived_count": row["archived_count"],
        "archived_size": row["archived_size"],
        "subscription_id": row["subscription_id"],
        "youtube_url": channel_url(row["youtube_id"]),
    }


@router.get("")
async def list_channels(
    q: str | None = None,
    sort: Literal[tuple(SORTS)] = "name",
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    db: Database = Depends(get_db),
):
    having = "HAVING (count(v.id) > 0 OR subscription_id IS NOT NULL)"
    where, params = ("WHERE c.name LIKE ?", [f"%{q.strip()}%"]) if q else ("", [])
    query = f"{CHANNEL_SELECT} {where} GROUP BY c.id {having}"
    total = await db.fetch_value(f"SELECT count(*) FROM ({query})", params)
    rows = await db.fetch_all(
        f"{query} ORDER BY {SORTS[sort]} LIMIT ? OFFSET ?",
        [*params, per_page, (page - 1) * per_page],
    )
    return {
        "items": [channel_out(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/{channel_id}")
async def get_channel(channel_id: int, db: Database = Depends(get_db)):
    row = await db.fetch_one(f"{CHANNEL_SELECT} WHERE c.id = ? GROUP BY c.id", (channel_id,))
    if not row:
        raise not_found("Channel")
    return channel_out(row)


async def channel_art(db: Database, channel_id: int, column: str, what: str) -> FileResponse:
    row = await db.fetch_one(f"SELECT {column} FROM channels WHERE id = ?", (channel_id,))
    if not row or not row[column]:
        raise not_found(what)
    try:
        path = layout.resolve(row[column])
    except layout.PathError as error:
        raise not_found(what) from error
    if not path.is_file():
        raise not_found(what)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


@router.get("/{channel_id}/avatar")
async def avatar(channel_id: int, db: Database = Depends(get_db)):
    return await channel_art(db, channel_id, "avatar_path", "Avatar")


@router.get("/{channel_id}/banner")
async def banner(channel_id: int, db: Database = Depends(get_db)):
    return await channel_art(db, channel_id, "banner_path", "Banner")
