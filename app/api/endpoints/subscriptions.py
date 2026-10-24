"""Subscriptions schedule discovery; the shared queue records the real result."""

from datetime import datetime
from typing import Optional

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_db, get_downloader
from app.core.database import Database
from app.core.downloader import Downloader
from app.core.security import get_auth
from app.core.ytdlp_service import get_ytdlp_service
from app.models.subscription import (
    SubscriptionCreate,
    SubscriptionListResponse,
    SubscriptionResponse,
    SubscriptionUpdate,
)

router = APIRouter()
JSON_FIELDS = ("subtitle_languages", "audio_tracks", "content_types", "extra_metadata")


def get_scheduler(request: Request):
    return request.app.state.scheduler


async def subscription_response(sub: dict, db: Database) -> SubscriptionResponse:
    for key in JSON_FIELDS:
        sub[key] = Database.json_decode(sub.get(key))
    try:
        sub["next_check"] = (
            CronTrigger.from_crontab(sub["check_frequency"]).get_next_fire_time(
                None, datetime.now()
            )
            if sub["enabled"]
            else None
        )
    except ValueError:
        sub["next_check"] = None
    job = await db.execute_one(
        "SELECT * FROM job_queue WHERE subscription_id = ? AND job_type = 'subscription_discovery' ORDER BY id DESC LIMIT 1",
        (sub["id"],),
    )
    if job:
        job["result_data"] = Database.json_decode(job.get("result_data"))
    sub["last_job"] = job
    return SubscriptionResponse(**sub)


@router.get("", response_model=SubscriptionListResponse)
async def list_subscriptions(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    enabled_only: bool = False,
    search: Optional[str] = None,
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth),
):
    clauses, params = ["1=1"], []
    if enabled_only:
        clauses.append("s.enabled = 1")
    if search:
        clauses.append("(c.name LIKE ? OR s.source_url LIKE ?)")
        params.extend([f"%{search}%"] * 2)
    where = " AND ".join(clauses)
    joined = "FROM subscriptions s JOIN channels c ON c.id = s.channel_id"
    total = await db.execute_one(f"SELECT COUNT(*) AS total {joined} WHERE {where}", tuple(params))
    subs = await db.execute(
        f"SELECT s.*, c.name AS channel_name, c.youtube_id AS channel_youtube_id {joined} WHERE {where} "
        "ORDER BY s.id DESC LIMIT ? OFFSET ?",
        tuple(params + [per_page, (page - 1) * per_page]),
    )
    return SubscriptionListResponse(
        subscriptions=[await subscription_response(s, db) for s in subs],
        total=total["total"],
        page=page,
        per_page=per_page,
    )


@router.post("", response_model=SubscriptionResponse, status_code=201)
async def create_subscription(
    subscription_data: SubscriptionCreate,
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    scheduler=Depends(get_scheduler),
    _: dict = Depends(get_auth),
):
    existing = await db.execute_one(
        "SELECT id FROM subscriptions WHERE source_url = ?", (subscription_data.source_url,)
    )
    if existing:
        raise HTTPException(status_code=409, detail="This source is already subscribed")
    try:
        info = await get_ytdlp_service().extract_info(
            subscription_data.source_url,
            {
                "extract_flat": True,
                "playlistend": 1,
                "noplaylist": False,
            },
        )
    except Exception as error:
        raise HTTPException(
            status_code=502, detail=f"Could not read this source: {error}"
        ) from error
    channel_yt = info.get("channel_id") or info.get("uploader_id")
    if subscription_data.subscription_type == "channel":
        channel_yt = info.get("channel_id") or info.get("id")
    channel_yt = channel_yt or f"playlist_{info.get('id', 'unknown')}"
    channel_name = (
        info.get("channel") or info.get("uploader") or info.get("title") or "Unknown source"
    )
    async with db.get_db() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cursor = await conn.execute(
            "SELECT id FROM subscriptions WHERE source_url = ?", (subscription_data.source_url,)
        )
        if await cursor.fetchone():
            raise HTTPException(status_code=409, detail="This source is already subscribed")
        await conn.execute(
            "INSERT INTO channels (youtube_id, name) VALUES (?, ?) ON CONFLICT(youtube_id) DO NOTHING",
            (channel_yt, channel_name),
        )
        cursor = await conn.execute("SELECT id FROM channels WHERE youtube_id = ?", (channel_yt,))
        channel = await cursor.fetchone()
        data = subscription_data.model_dump()
        data["channel_id"] = channel["id"]
        data["extra_metadata"] = {
            **(data["extra_metadata"] or {}),
            "source_title": info.get("title"),
        }
        for key in JSON_FIELDS:
            data[key] = Database.json_encode(data[key])
        columns = ", ".join(data)
        cursor = await conn.execute(
            f"INSERT INTO subscriptions ({columns}) VALUES ({', '.join('?' for _ in data)})",
            tuple(data.values()),
        )
        subscription_id = cursor.lastrowid
        await conn.commit()
    if subscription_data.enabled:
        await scheduler.add_subscription(subscription_id, subscription_data.check_frequency)
        await downloader.queue_subscription_discovery(subscription_id, priority=2)
    return await get_subscription(subscription_id, db, _)


@router.get("/{subscription_id}", response_model=SubscriptionResponse)
async def get_subscription(
    subscription_id: int, db: Database = Depends(get_db), _: dict = Depends(get_auth)
):
    sub = await db.execute_one(
        "SELECT s.*, c.name AS channel_name, c.youtube_id AS channel_youtube_id "
        "FROM subscriptions s JOIN channels c ON c.id = s.channel_id WHERE s.id = ?",
        (subscription_id,),
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return await subscription_response(sub, db)


@router.put("/{subscription_id}", response_model=SubscriptionResponse)
async def update_subscription(
    subscription_id: int,
    subscription_update: SubscriptionUpdate,
    db: Database = Depends(get_db),
    scheduler=Depends(get_scheduler),
    _: dict = Depends(get_auth),
):
    await get_subscription(subscription_id, db, _)
    data = subscription_update.model_dump(exclude_unset=True)
    for key in JSON_FIELDS:
        if key in data:
            data[key] = Database.json_encode(data[key])
    if data:
        await db.update("subscriptions", data, "id = ?", (subscription_id,))
    sub = await get_subscription(subscription_id, db, _)
    if sub.enabled:
        await scheduler.update_subscription(subscription_id, sub.check_frequency)
    else:
        await scheduler.remove_subscription(subscription_id)
    return sub


@router.delete("/{subscription_id}")
async def delete_subscription(
    subscription_id: int,
    db: Database = Depends(get_db),
    scheduler=Depends(get_scheduler),
    _: dict = Depends(get_auth),
):
    await get_subscription(subscription_id, db, _)
    async with db.get_db() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cursor = await conn.execute(
            "SELECT id FROM job_queue WHERE subscription_id = ? AND status IN ('downloading', 'processing')",
            (subscription_id,),
        )
        if await cursor.fetchone():
            raise HTTPException(
                status_code=409,
                detail="Wait for the running check before deleting this subscription",
            )
        await conn.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))
        await conn.commit()
    await scheduler.remove_subscription(subscription_id)
    return {"message": "Subscription removed. Saved videos are unchanged."}


@router.post("/{subscription_id}/check", status_code=202)
async def check_subscription(
    subscription_id: int,
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth),
):
    sub = await get_subscription(subscription_id, db, _)
    job_id = await downloader.queue_subscription_discovery(subscription_id, priority=3)
    return {
        "message": "Check queued; follow its progress in Downloads",
        "job_id": job_id,
        "subscription_id": subscription_id,
        "channel_name": sub.channel_name,
    }


@router.get("/{subscription_id}/jobs")
async def get_subscription_jobs(
    subscription_id: int, db: Database = Depends(get_db), _: dict = Depends(get_auth)
):
    await get_subscription(subscription_id, db, _)
    jobs = await db.execute(
        "SELECT * FROM job_queue WHERE subscription_id = ? ORDER BY id DESC LIMIT 10",
        (subscription_id,),
    )
    for job in jobs:
        job["result_data"] = Database.json_decode(job.get("result_data"))
    return {"jobs": jobs}


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: int, db: Database = Depends(get_db), _: dict = Depends(get_auth)):
    job = await db.execute_one("SELECT * FROM job_queue WHERE id = ?", (job_id,))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job["result_data"] = Database.json_decode(job.get("result_data"))
    return job


@router.post("/{subscription_id}/pause")
async def pause_subscription(
    subscription_id: int,
    db: Database = Depends(get_db),
    scheduler=Depends(get_scheduler),
    _: dict = Depends(get_auth),
):
    await update_subscription(subscription_id, SubscriptionUpdate(enabled=False), db, scheduler, _)
    return {"message": "Future checks paused. Already queued work is unchanged."}


@router.post("/{subscription_id}/resume")
async def resume_subscription(
    subscription_id: int,
    db: Database = Depends(get_db),
    scheduler=Depends(get_scheduler),
    _: dict = Depends(get_auth),
):
    await update_subscription(subscription_id, SubscriptionUpdate(enabled=True), db, scheduler, _)
    return {"message": "Scheduled checks resumed"}


@router.get("/scheduler/status")
async def get_scheduler_status(scheduler=Depends(get_scheduler), _: dict = Depends(get_auth)):
    jobs = scheduler.get_scheduled_subscriptions()
    return {
        "scheduler_running": scheduler.is_running,
        "scheduled_subscriptions": jobs,
        "total_jobs": len(jobs),
    }


@router.get("/ytdlp/status")
async def get_ytdlp_status(_: dict = Depends(get_auth)):
    return get_ytdlp_service().get_status()
