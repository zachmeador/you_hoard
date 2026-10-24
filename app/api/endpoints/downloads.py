"""Inspect and control durable jobs without pretending to stop active transfers."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.dependencies import get_db, get_downloader
from app.core.database import Database
from app.core.downloader import Downloader
from app.core.security import get_auth

router = APIRouter()


class DownloadQueueItem(BaseModel):
    id: int
    job_type: str
    video_id: Optional[int] = None
    subscription_id: Optional[int] = None
    video_title: Optional[str] = None
    channel_name: Optional[str] = None
    quality: Optional[str] = None
    priority: int
    status: str
    progress: float
    speed: Optional[float] = None
    eta: Optional[int] = None
    error_message: Optional[str] = None
    videos_found: int = 0
    videos_processed: int = 0
    result_data: Optional[dict] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime


class DownloadQueueResponse(BaseModel):
    downloads: list[DownloadQueueItem]
    total: int
    active_count: int
    queued_count: int
    failed_count: int


@router.get("", response_model=DownloadQueueResponse)
async def list_downloads(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth),
):
    params = [status] if status else []
    where = "WHERE dq.status = ?" if status else ""
    jobs = await db.execute(
        f"""
        SELECT dq.*, v.title AS video_title, COALESCE(c.name, sc.name) AS channel_name
        FROM job_queue dq
        LEFT JOIN videos v ON v.id = dq.video_id
        LEFT JOIN channels c ON c.id = v.channel_id
        LEFT JOIN subscriptions s ON s.id = dq.subscription_id
        LEFT JOIN channels sc ON sc.id = s.channel_id
        {where}
        ORDER BY CASE dq.status WHEN 'downloading' THEN 0 WHEN 'processing' THEN 0
                 WHEN 'queued' THEN 1 WHEN 'failed' THEN 2 WHEN 'paused' THEN 3 ELSE 4 END,
                 dq.priority DESC, dq.id DESC LIMIT ? OFFSET ?""",
        tuple(params + [limit, offset]),
    )
    active = downloader.get_active_downloads()
    for job in jobs:
        if job["status"] == "downloading" and job["video_id"] in active:
            progress = active[job["video_id"]]
            job.update(progress=progress.progress, speed=progress.speed, eta=progress.eta)
        job["result_data"] = Database.json_decode(job.get("result_data"))
    counts = await db.execute_one("""SELECT COUNT(*) AS total,
        COUNT(CASE WHEN status IN ('downloading', 'processing') THEN 1 END) AS active_count,
        COUNT(CASE WHEN status = 'queued' THEN 1 END) AS queued_count,
        COUNT(CASE WHEN status = 'failed' THEN 1 END) AS failed_count FROM job_queue""")
    return DownloadQueueResponse(downloads=[DownloadQueueItem(**j) for j in jobs], **counts)


async def transition(
    download_id: int, expected: str, state: str, db: Database, downloader: Downloader
):
    async with db.get_db() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cursor = await conn.execute("SELECT * FROM job_queue WHERE id = ?", (download_id,))
        job = await cursor.fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["status"] != expected:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot change a {job['status']} job. Active work must finish first.",
            )
        if state == "queued":
            key = "video_id" if job["job_type"] == "download" else "subscription_id"
            if job[key] is not None:
                cursor = await conn.execute(
                    f"SELECT id FROM job_queue WHERE {key} = ? AND job_type = ? AND id != ? "
                    "AND status IN ('queued', 'downloading', 'processing', 'paused')",
                    (job[key], job["job_type"], download_id),
                )
                if await cursor.fetchone():
                    raise HTTPException(
                        status_code=409, detail="There is already a job for this source"
                    )
            if job["video_id"]:
                cursor = await conn.execute(
                    "SELECT download_status FROM videos WHERE id = ?", (job["video_id"],)
                )
                video = await cursor.fetchone()
                if video["download_status"] == "completed":
                    raise HTTPException(status_code=409, detail="Video is already downloaded")
                await conn.execute(
                    "UPDATE videos SET download_status = 'pending' WHERE id = ?", (job["video_id"],)
                )
        await conn.execute(
            "UPDATE job_queue SET status = ?, progress = 0, error_message = NULL, started_at = NULL, completed_at = NULL WHERE id = ?",
            (state, download_id),
        )
        await conn.commit()
    downloader.notify_queue_changed()
    return {"message": f"Job {state}"}


@router.post("/{download_id}/pause")
async def pause_download(
    download_id: int,
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth),
):
    return await transition(download_id, "queued", "paused", db, downloader)


@router.post("/{download_id}/resume")
async def resume_download(
    download_id: int,
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth),
):
    return await transition(download_id, "paused", "queued", db, downloader)


@router.post("/{download_id}/retry")
async def retry_download(
    download_id: int,
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth),
):
    return await transition(download_id, "failed", "queued", db, downloader)


@router.delete("/{download_id}")
async def cancel_download(
    download_id: int, db: Database = Depends(get_db), _: dict = Depends(get_auth)
):
    async with db.get_db() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cursor = await conn.execute("SELECT * FROM job_queue WHERE id = ?", (download_id,))
        job = await cursor.fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["status"] in ("downloading", "processing"):
            raise HTTPException(
                status_code=409, detail="Active work must finish before it can be removed"
            )
        await conn.execute("DELETE FROM job_queue WHERE id = ?", (download_id,))
        await conn.commit()
    return {"message": "Job removed; library files are unchanged"}


@router.post("/clear-completed")
async def clear_completed_downloads(db: Database = Depends(get_db), _: dict = Depends(get_auth)):
    deleted = await db.delete("job_queue", "status = ?", ("completed",))
    return {"message": f"Cleared {deleted} completed jobs"}


@router.post("/retry-all-failed")
async def retry_all_failed(
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth),
):
    jobs = await db.execute("SELECT id FROM job_queue WHERE status = 'failed'")
    retried = 0
    for job in jobs:
        try:
            await transition(job["id"], "failed", "queued", db, downloader)
            retried += 1
        except HTTPException as error:
            if error.status_code != 409:
                raise
    return {"message": f"Retrying {retried} failed jobs", "retried": retried}
