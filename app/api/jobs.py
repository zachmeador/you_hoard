"""The queue: downloads, subscription checks and library scans."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import get_runner, get_youtube
from app.db import loads
from app.gate import YouTubeGate
from app.jobs import STATES, JobRunner, max_attempts

router = APIRouter()
# "waiting" is a queued job held back by its own wait or by a pause on YouTube; "queued" is one
# that can run now.
Status = Literal[STATES]
Kind = Literal["download", "check", "scan"]
MAX_PAUSE_HOURS = 24 * 30


def job_out(row: dict[str, Any], runner: JobRunner) -> dict[str, Any]:
    progress = runner.progress.get(row["id"]) if row["status"] == "running" else None
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "state": row["state"],
        "reason": row["reason"],
        "origin": row["origin"],
        "waiting_on": row["waiting_on"],
        "waits_until": row["wait_ends"],
        "priority": row["priority"],
        "refusals": row["refusals"],
        "attempts": row["attempts"],
        "max_attempts": max_attempts(row["kind"]),
        "error": row["error"],
        "result": loads(row["result"]),
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
        "via_subscription": {
            "id": row["via_subscription_id"],
            "title": row["via_subscription_title"],
        }
        if row["via_subscription_id"]
        else None,
        "progress": progress.as_dict() if progress else None,
    }


@router.get("")
async def list_jobs(
    status: list[Status] | None = Query(None),
    kind: Kind | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    runner: JobRunner = Depends(get_runner),
    youtube: YouTubeGate = Depends(get_youtube),
):
    rows, total = await runner.list_jobs(status, kind, limit, offset)
    return {
        "items": [job_out(row, runner) for row in rows],
        "total": total,
        "counts": await runner.counts(kind),
        **youtube.status,
    }


@router.get("/ids")
async def list_job_ids(
    status: list[Status] | None = Query(None),
    kind: Kind | None = None,
    runner: JobRunner = Depends(get_runner),
):
    """Every id the same filters would list, in the same order."""
    return {"ids": await runner.job_ids(status, kind)}


class YouTubePause(BaseModel):
    hours: float = Field(gt=0, le=MAX_PAUSE_HOURS)


@router.post("/pause-youtube")
async def pause_youtube(body: YouTubePause, youtube: YouTubeGate = Depends(get_youtube)):
    """Hold all YouTube work for a while, e.g. to give the connection a rest."""
    await youtube.hold(body.hours * 3600)
    return {"ok": True}


@router.post("/resume-youtube")
async def resume_youtube(runner: JobRunner = Depends(get_runner)):
    """End a pause early, e.g. after loading cookies."""
    await runner.resume_youtube(actor="owner")
    return {"ok": True}


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: int, runner: JobRunner = Depends(get_runner)):
    await runner.cancel(job_id, actor="owner")
    return {"ok": True}


@router.post("/{job_id}/retry")
async def retry_job(job_id: int, runner: JobRunner = Depends(get_runner)):
    await runner.retry(job_id, actor="owner")
    return {"ok": True}


@router.post("/{job_id}/pause")
async def pause_job(job_id: int, runner: JobRunner = Depends(get_runner)):
    await runner.pause(job_id, actor="owner")
    return {"ok": True}


@router.post("/{job_id}/resume")
async def resume_job(job_id: int, runner: JobRunner = Depends(get_runner)):
    await runner.resume(job_id, actor="owner")
    return {"ok": True}


@router.post("/{job_id}/run-now")
async def run_job_now(job_id: int, runner: JobRunner = Depends(get_runner)):
    """Make a queued job the next to run, skipping its own wait."""
    await runner.run_now(job_id, actor="owner")
    return {"ok": True}


class JobIds(BaseModel):
    ids: list[int] = Field(min_length=1)


@router.post("/pause")
async def pause_jobs(body: JobIds, runner: JobRunner = Depends(get_runner)):
    """Pause the listed jobs that are still queued, ready or waiting; skip the rest."""
    return {"paused": await runner.pause_many(body.ids, actor="owner")}


@router.post("/resume")
async def resume_jobs(body: JobIds, runner: JobRunner = Depends(get_runner)):
    """Queue the listed jobs that are still paused, except downloads of archived videos."""
    return {"resumed": await runner.resume_many(body.ids, actor="owner")}


@router.delete("/{job_id}")
async def delete_job(job_id: int, runner: JobRunner = Depends(get_runner)):
    await runner.remove(job_id, actor="owner")
    return {"ok": True}


@router.post("/clear")
async def clear_finished(runner: JobRunner = Depends(get_runner)):
    return {"cleared": await runner.clear_finished(actor="owner")}


@router.post("/retry-failed")
async def retry_failed(runner: JobRunner = Depends(get_runner)):
    """Retry every failed job except those whose video is gone."""
    return {"retried": await runner.retry_failed(actor="owner")}
