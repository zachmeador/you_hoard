"""Followed channels and playlists, their inventories and checks."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.api.deps import get_db, get_runner, get_settings, get_youtube, not_found
from app.checks import apply_policy, queue_entry_download
from app.db import Database, dumps, fetch_one, later, loads, now
from app.jobs import JobRunner
from app.library import upsert_channel
from app.settings import Settings
from app.youtube import (
    QUALITIES,
    Inaccessible,
    Unavailable,
    YouTube,
    YouTubeError,
    parse_source_url,
    source_url,
)

router = APIRouter()
Quality = Literal[tuple(QUALITIES)]
VideoType = Literal["video", "short", "live"]
Policy = Literal["none", "new", "recent", "all"]
OVERRIDES = ("quality", "subtitle_languages", "download_comments")

SUBSCRIPTION_SELECT = """
SELECT sub.*, c.youtube_id AS channel_youtube_id, c.name AS channel_name
FROM subscriptions sub LEFT JOIN channels c ON c.id = sub.channel_id
"""
COUNTS_SELECT = """
SELECT e.subscription_id,
       count(*) AS entries,
       count(e.removed_at) AS removed,
       count(CASE WHEN s.status = 'archived' THEN 1 END) AS archived,
       count(CASE WHEN s.status IN ('queued', 'downloading') THEN 1 END) AS queued,
       count(CASE WHEN s.status = 'failed' THEN 1 END) AS failed,
       count(CASE WHEN v.id IS NULL THEN 1 END) AS not_selected
FROM source_entries e
LEFT JOIN videos v ON v.youtube_id = e.youtube_id
LEFT JOIN video_status s ON s.video_id = v.id
"""
EMPTY_COUNTS = {
    "entries": 0,
    "archived": 0,
    "queued": 0,
    "failed": 0,
    "not_selected": 0,
    "removed": 0,
}


class SubscriptionFields(BaseModel):
    enabled: bool | None = None
    content_types: list[VideoType] | None = Field(None, min_length=1)
    download_policy: Policy | None = None
    recent_count: int | None = Field(None, ge=1, le=1000)
    quality: Quality | None = None
    subtitle_languages: list[str] | None = None
    download_comments: bool | None = None
    check_interval_hours: int | None = Field(None, ge=1, le=720)

    @field_validator("content_types")
    @classmethod
    def unique_types(cls, value: list[str] | None) -> list[str] | None:
        return sorted(set(value), key=["video", "short", "live"].index) if value else value

    @field_validator("subtitle_languages")
    @classmethod
    def languages(cls, value: list[str] | None) -> list[str] | None:
        return [lang.strip() for lang in value if lang.strip()] if value is not None else None


class NewSubscription(SubscriptionFields):
    url: str


class SourceUrl(BaseModel):
    url: str


class CheckRequest(BaseModel):
    full: bool = False


def subscription_out(row: dict[str, Any], counts: dict | None, jobs: dict) -> dict[str, Any]:
    active, finished = jobs.get("active"), jobs.get("finished")
    return {
        "id": row["id"],
        "kind": row["kind"],
        "youtube_id": row["youtube_id"],
        "title": row["title"],
        "url": source_url(row["kind"], row["youtube_id"]),
        "channel": {
            "id": row["channel_id"],
            "youtube_id": row["channel_youtube_id"],
            "name": row["channel_name"],
        }
        if row["channel_id"]
        else None,
        "owner_name": row["owner_name"],
        "enabled": bool(row["enabled"]),
        "content_types": loads(row["content_types"]),
        "download_policy": row["download_policy"],
        "recent_count": row["recent_count"],
        "quality": row["quality"],
        "subtitle_languages": loads(row["subtitle_languages"]),
        "download_comments": None
        if row["download_comments"] is None
        else bool(row["download_comments"]),
        "check_interval_hours": row["check_interval_hours"],
        "next_check_at": row["next_check_at"] if row["enabled"] else None,
        "last_checked_at": row["last_checked_at"],
        "created_at": row["created_at"],
        "counts": {**EMPTY_COUNTS, **(counts or {})},
        "last_check": {
            "job_id": finished["id"],
            "status": finished["status"],
            "error": finished["error"],
            "finished_at": finished["finished_at"],
            "result": loads(finished["result"]),
        }
        if finished
        else None,
        "checking": active is not None,
    }


async def subscriptions_out(db: Database, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    ids = [row["id"] for row in rows]
    marks = ", ".join("?" for _ in ids)
    counts = {
        row.pop("subscription_id"): row
        for row in await db.fetch_all(
            f"{COUNTS_SELECT} WHERE e.subscription_id IN ({marks}) GROUP BY e.subscription_id", ids
        )
    }
    jobs: dict[int, dict] = {}
    for job in await db.fetch_all(
        f"""SELECT * FROM jobs WHERE id IN (
                SELECT max(id) FROM jobs WHERE kind = 'check' AND subscription_id IN ({marks})
                  AND status IN ('queued', 'paused', 'running') GROUP BY subscription_id
                UNION
                SELECT max(id) FROM jobs WHERE kind = 'check' AND subscription_id IN ({marks})
                  AND status IN ('completed', 'failed', 'cancelled') GROUP BY subscription_id)""",
        [*ids, *ids],
    ):
        slot = "active" if job["status"] in ("queued", "paused", "running") else "finished"
        jobs.setdefault(job["subscription_id"], {})[slot] = job
    return [subscription_out(row, counts.get(row["id"]), jobs.get(row["id"], {})) for row in rows]


async def load_subscription(db: Database, subscription_id: int) -> dict[str, Any]:
    row = await db.fetch_one(f"{SUBSCRIPTION_SELECT} WHERE sub.id = ?", (subscription_id,))
    if not row:
        raise not_found("Subscription")
    return row


async def subscription_response(db: Database, subscription_id: int) -> dict[str, Any]:
    return (await subscriptions_out(db, [await load_subscription(db, subscription_id)]))[0]


async def resolve(youtube: YouTube, url: str):
    try:
        kind, resolvable = parse_source_url(url)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        return await youtube.resolve_source(kind, resolvable)
    except (Unavailable, Inaccessible) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except YouTubeError as error:
        raise HTTPException(status_code=502, detail=f"YouTube: {error}") from error


@router.get("")
async def list_subscriptions(db: Database = Depends(get_db)):
    rows = await db.fetch_all(f"{SUBSCRIPTION_SELECT} ORDER BY sub.title COLLATE NOCASE")
    return {"items": await subscriptions_out(db, rows)}


@router.post("/resolve")
async def resolve_source(
    body: SourceUrl, db: Database = Depends(get_db), youtube: YouTube = Depends(get_youtube)
):
    source = await resolve(youtube, body.url)
    existing = await db.fetch_value(
        "SELECT id FROM subscriptions WHERE kind = ? AND youtube_id = ?",
        (source.kind, source.youtube_id),
    )
    return {
        "kind": source.kind,
        "youtube_id": source.youtube_id,
        "title": source.title,
        "url": source.url,
        "channel_name": source.channel_name,
        "owner_name": source.owner_name,
        "existing_subscription_id": existing,
    }


@router.post("", status_code=201)
async def create_subscription(
    body: NewSubscription,
    db: Database = Depends(get_db),
    runner: JobRunner = Depends(get_runner),
    settings: Settings = Depends(get_settings),
    youtube: YouTube = Depends(get_youtube),
):
    source = await resolve(youtube, body.url)
    interval = body.check_interval_hours or await settings.get("check_interval_hours")
    enabled = body.enabled is not False
    async with db.transaction() as conn:
        if await fetch_one(
            conn,
            "SELECT 1 FROM subscriptions WHERE kind = ? AND youtube_id = ?",
            (source.kind, source.youtube_id),
        ):
            raise HTTPException(status_code=409, detail=f"Already subscribed to {source.title}")
        channel_id = None
        if source.kind == "channel":
            channel_id = await upsert_channel(
                conn,
                source.youtube_id,
                source.channel_name,
                handle=source.channel_handle,
                description=source.description,
                subscriber_count=source.subscriber_count,
            )
        cursor = await conn.execute(
            """INSERT INTO subscriptions (kind, youtube_id, title, channel_id, owner_name, enabled,
                   content_types, download_policy, recent_count, quality, subtitle_languages,
                   download_comments, check_interval_hours, next_check_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source.kind,
                source.youtube_id,
                source.title,
                channel_id,
                source.owner_name,
                enabled,
                dumps(body.content_types or ["video"]),
                body.download_policy or "new",
                body.recent_count or 10,
                body.quality,
                dumps(body.subtitle_languages),
                body.download_comments,
                interval,
                later(hours=interval),
            ),
        )
        subscription_id = cursor.lastrowid
        if enabled:
            await runner.enqueue(
                "check",
                subscription_id=subscription_id,
                options={"full": True},
                priority=5,
                conn=conn,
            )
    return await subscription_response(db, subscription_id)


@router.get("/{subscription_id}")
async def get_subscription(subscription_id: int, db: Database = Depends(get_db)):
    return await subscription_response(db, subscription_id)


@router.patch("/{subscription_id}")
async def update_subscription(
    subscription_id: int,
    body: SubscriptionFields,
    db: Database = Depends(get_db),
    runner: JobRunner = Depends(get_runner),
):
    current = await load_subscription(db, subscription_id)
    fields = body.model_dump(include=body.model_fields_set)
    for key, value in fields.items():
        if value is None and key not in OVERRIDES:
            raise HTTPException(status_code=422, detail=f"{key} cannot be empty")
    if not fields:
        return await subscription_response(db, subscription_id)
    values = {
        key: dumps(value) if key in ("content_types", "subtitle_languages") else value
        for key, value in fields.items()
    }
    if "check_interval_hours" in fields:
        values["next_check_at"] = later(hours=fields["check_interval_hours"])
    values["updated_at"] = now()
    selection_changed = any(
        key in fields and values[key] != current[key]
        for key in ("content_types", "download_policy", "recent_count")
    )
    async with db.transaction() as conn:
        assignments = ", ".join(f"{key} = ?" for key in values)
        await conn.execute(
            f"UPDATE subscriptions SET {assignments} WHERE id = ?",
            (*values.values(), subscription_id),
        )
        if selection_changed:
            await apply_policy(runner, conn, subscription_id)
            enabled = fields.get("enabled", current["enabled"])
            types_added = "content_types" in fields and set(fields["content_types"]) - set(
                loads(current["content_types"])
            )
            if enabled and types_added:
                await runner.enqueue(
                    "check", subscription_id=subscription_id, priority=5, conn=conn
                )
    return await subscription_response(db, subscription_id)


@router.delete("/{subscription_id}")
async def delete_subscription(subscription_id: int, db: Database = Depends(get_db)):
    await load_subscription(db, subscription_id)
    async with db.transaction() as conn:
        if await fetch_one(
            conn,
            "SELECT 1 FROM jobs WHERE subscription_id = ? AND status = 'running'",
            (subscription_id,),
        ):
            raise HTTPException(status_code=409, detail="Wait for the running check to finish")
        await conn.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))
    return {"ok": True}


@router.post("/{subscription_id}/check", status_code=202)
async def check_subscription(
    subscription_id: int,
    body: CheckRequest | None = None,
    db: Database = Depends(get_db),
    runner: JobRunner = Depends(get_runner),
):
    await load_subscription(db, subscription_id)
    job_id = await runner.enqueue(
        "check",
        subscription_id=subscription_id,
        options={"full": bool(body and body.full)},
        priority=5,
    )
    return {"job_id": job_id}


ENTRY_SELECT = """
SELECT e.*, v.id AS video_id, coalesce(s.status, 'not_selected') AS status
FROM source_entries e
LEFT JOIN videos v ON v.youtube_id = e.youtube_id
LEFT JOIN video_status s ON s.video_id = v.id
"""


@router.get("/{subscription_id}/entries")
async def list_entries(
    subscription_id: int,
    status: str | None = None,
    video_type: VideoType | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Database = Depends(get_db),
):
    await load_subscription(db, subscription_id)
    clauses, params = ["e.subscription_id = ?"], [subscription_id]
    if status:
        clauses.append("coalesce(s.status, 'not_selected') = ?")
        params.append(status)
    if video_type:
        clauses.append("e.video_type = ?")
        params.append(video_type)
    if q:
        clauses.append("e.title LIKE ?")
        params.append(f"%{q.strip()}%")
    where = " AND ".join(clauses)
    total = await db.fetch_value(f"SELECT count(*) FROM ({ENTRY_SELECT} WHERE {where})", params)
    rows = await db.fetch_all(
        f"{ENTRY_SELECT} WHERE {where} "
        "ORDER BY e.removed_at IS NOT NULL, e.video_type, e.position LIMIT ? OFFSET ?",
        [*params, per_page, (page - 1) * per_page],
    )
    items = [
        {
            key: row[key]
            for key in (
                "youtube_id",
                "title",
                "video_type",
                "duration",
                "position",
                "live_status",
                "first_seen_at",
                "removed_at",
                "video_id",
                "status",
            )
        }
        for row in rows
    ]
    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.post("/{subscription_id}/entries/{youtube_id}/download")
async def download_entry(
    subscription_id: int,
    youtube_id: str,
    db: Database = Depends(get_db),
    runner: JobRunner = Depends(get_runner),
):
    sub = await load_subscription(db, subscription_id)
    async with db.transaction() as conn:
        entry = await fetch_one(
            conn,
            f"{ENTRY_SELECT} WHERE e.subscription_id = ? AND e.youtube_id = ?",
            (subscription_id, youtube_id),
        )
        if not entry:
            raise not_found("Entry")
        if entry["status"] == "archived":
            raise HTTPException(status_code=409, detail="This video is already archived")
        video_id, job_id = await queue_entry_download(runner, conn, sub, entry)
    return {"job_id": job_id, "video_id": video_id}
