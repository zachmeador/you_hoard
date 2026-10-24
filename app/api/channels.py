"""Channels with library counts."""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_db, not_found
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


def channel_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "youtube_id": row["youtube_id"],
        "name": row["name"],
        "handle": row["handle"],
        "description": row["description"],
        "subscriber_count": row["subscriber_count"],
        "video_count": row["video_count"],
        "archived_count": row["archived_count"],
        "archived_size": row["archived_size"],
        "subscription_id": row["subscription_id"],
        "youtube_url": channel_url(row["youtube_id"]),
    }


@router.get("")
async def list_channels(
    q: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    db: Database = Depends(get_db),
):
    having = "HAVING (count(v.id) > 0 OR subscription_id IS NOT NULL)"
    where, params = ("WHERE c.name LIKE ?", [f"%{q.strip()}%"]) if q else ("", [])
    query = f"{CHANNEL_SELECT} {where} GROUP BY c.id {having}"
    total = await db.fetch_value(f"SELECT count(*) FROM ({query})", params)
    rows = await db.fetch_all(
        f"{query} ORDER BY c.name COLLATE NOCASE LIMIT ? OFFSET ?",
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
