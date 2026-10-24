"""The queue: downloads, subscription checks and library scans."""

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_db, get_runner, not_found
from app.db import Database, fetch_one, loads
from app.jobs import JobRunner

router = APIRouter()
Status = Literal["queued", "paused", "running", "completed", "failed", "cancelled"]

JOB_SELECT = """
SELECT j.*, v.title AS video_title, v.youtube_id AS video_youtube_id,
       sub.title AS subscription_title
FROM jobs j
LEFT JOIN videos v ON v.id = j.video_id
LEFT JOIN subscriptions sub ON sub.id = j.subscription_id
"""
ORDER = """
ORDER BY CASE j.status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 WHEN 'paused' THEN 2
                       WHEN 'failed' THEN 3 ELSE 4 END,
         CASE WHEN j.status IN ('running', 'queued', 'paused') THEN -j.priority END,
         CASE WHEN j.status IN ('running', 'queued', 'paused') THEN j.id END,
         coalesce(j.finished_at, j.created_at) DESC, j.id DESC
"""


def job_out(row: dict[str, Any], runner: JobRunner) -> dict[str, Any]:
    progress = runner.progress.get(row["id"]) if row["status"] == "running" else None
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "priority": row["priority"],
        "attempts": row["attempts"],
        "error": row["error"],
        "result": loads(row["result"]),
        "run_after": row["run_after"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "video": {
            "id": row["video_id"],
            "title": row["video_title"],
            "youtube_id": row["video_youtube_id"],
        }
        if row["video_id"]
        else None,
        "subscription": {"id": row["subscription_id"], "title": row["subscription_title"]}
        if row["subscription_id"]
        else None,
        "progress": progress.as_dict() if progress else None,
    }


@router.get("")
async def list_jobs(
    status: Status | None = None,
    kind: Literal["download", "check", "scan"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Database = Depends(get_db),
    runner: JobRunner = Depends(get_runner),
):
    clauses, params = [], []
    if status:
        clauses.append("j.status = ?")
        params.append(status)
    if kind:
        clauses.append("j.kind = ?")
        params.append(kind)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = await db.fetch_value(f"SELECT count(*) FROM jobs j {where}", params)
    rows = await db.fetch_all(
        f"{JOB_SELECT} {where} {ORDER} LIMIT ? OFFSET ?", [*params, limit, offset]
    )
    counts = dict.fromkeys(("queued", "paused", "running", "completed", "failed", "cancelled"), 0)
    for row in await db.fetch_all("SELECT status, count(*) AS n FROM jobs GROUP BY status"):
        counts[row["status"]] = row["n"]
    return {"items": [job_out(row, runner) for row in rows], "total": total, "counts": counts}


async def transition(
    db: Database, runner: JobRunner, job_id: int, allowed: tuple[str, ...], status: str
) -> None:
    try:
        async with db.transaction() as conn:
            job = await fetch_one(conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))
            if not job:
                raise not_found("Job")
            if job["status"] not in allowed:
                raise HTTPException(
                    status_code=409, detail=f"Cannot do that to a {job['status']} job"
                )
            if status == "queued" and job["kind"] == "download":
                video = await fetch_one(
                    conn, "SELECT media_path FROM videos WHERE id = ?", (job["video_id"],)
                )
                if video["media_path"]:
                    raise HTTPException(status_code=409, detail="This video is already archived")
            extra = (
                ", attempts = 0, error = NULL, run_after = NULL, started_at = NULL, finished_at = NULL"
                if job["status"] in ("failed", "cancelled")
                else ""
            )
            await conn.execute(f"UPDATE jobs SET status = ?{extra} WHERE id = ?", (status, job_id))
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409, detail="Another job for this is already queued"
        ) from error
    runner.wake()


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: int, runner: JobRunner = Depends(get_runner)):
    if not await runner.cancel(job_id):
        raise HTTPException(
            status_code=409, detail="Only queued, paused or running jobs can be cancelled"
        )
    return {"ok": True}


@router.post("/{job_id}/retry")
async def retry_job(
    job_id: int, db: Database = Depends(get_db), runner: JobRunner = Depends(get_runner)
):
    await transition(db, runner, job_id, ("failed", "cancelled"), "queued")
    return {"ok": True}


@router.post("/{job_id}/pause")
async def pause_job(
    job_id: int, db: Database = Depends(get_db), runner: JobRunner = Depends(get_runner)
):
    await transition(db, runner, job_id, ("queued",), "paused")
    return {"ok": True}


@router.post("/{job_id}/resume")
async def resume_job(
    job_id: int, db: Database = Depends(get_db), runner: JobRunner = Depends(get_runner)
):
    await transition(db, runner, job_id, ("paused",), "queued")
    return {"ok": True}


@router.delete("/{job_id}")
async def delete_job(job_id: int, db: Database = Depends(get_db)):
    deleted = await db.execute(
        "DELETE FROM jobs WHERE id = ? AND status IN ('completed', 'failed', 'cancelled')",
        (job_id,),
    )
    if not deleted:
        raise HTTPException(status_code=409, detail="Only finished jobs can be removed")
    return {"ok": True}


@router.post("/clear")
async def clear_finished(db: Database = Depends(get_db)):
    cleared = await db.execute("DELETE FROM jobs WHERE status IN ('completed', 'cancelled')")
    return {"cleared": cleared}


@router.post("/retry-failed")
async def retry_failed(db: Database = Depends(get_db), runner: JobRunner = Depends(get_runner)):
    retried = 0
    for job in await db.fetch_all("SELECT id FROM jobs WHERE status = 'failed' ORDER BY id"):
        try:
            await transition(db, runner, job["id"], ("failed",), "queued")
            retried += 1
        except HTTPException as error:
            if error.status_code != 409:
                raise
    return {"retried": retried}
