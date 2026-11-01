"""What happened: the record of job moves, YouTube pauses and other changes."""

from typing import Literal

from fastapi import APIRouter, Depends, Query

from app import events
from app.api.deps import get_db
from app.db import Database

router = APIRouter()


@router.get("")
async def list_events(
    job_id: int | None = None,
    video_id: int | None = None,
    subscription_id: int | None = None,
    group: Literal["jobs", "youtube", "app"] | None = None,
    before: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Database = Depends(get_db),
):
    """Newest first. Pass `next_before` as `before` to get the events older than a page."""
    rows, next_before = await events.list_events(
        db,
        job_id=job_id,
        video_id=video_id,
        subscription_id=subscription_id,
        group=group,
        before=before,
        limit=limit,
    )
    return {
        "items": [
            {
                "id": row["id"],
                "at": row["at"],
                "event": row["event"],
                "actor": row["actor"],
                "job_id": row["job_id"],
                "job_kind": row["job_kind"],
                "video": {"id": row["video_id"], "title": row["video_title"]}
                if row["video_id"]
                else None,
                "subscription": {"id": row["subscription_id"], "title": row["subscription_title"]}
                if row["subscription_id"]
                else None,
                "reason": row["reason"],
                "detail": row["detail"],
            }
            for row in rows
        ],
        "next_before": next_before,
    }
