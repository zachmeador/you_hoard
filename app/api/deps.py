"""Shared request dependencies and response helpers."""

from typing import Any

from fastapi import HTTPException, Request

from app.db import Database, loads
from app.jobs import JobRunner
from app.library import VIDEO_SELECT, quality_label
from app.settings import Settings
from app.youtube import YouTube, video_url


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_runner(request: Request) -> JobRunner:
    return request.app.state.runner


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_youtube(request: Request) -> YouTube:
    return request.app.state.youtube


def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


def page_params(page: int, per_page: int) -> tuple[int, int]:
    return per_page, (page - 1) * per_page


def clean_languages(value: list[str] | None) -> list[str] | None:
    return [lang.strip() for lang in value if lang.strip()] if value is not None else None


def art_url(channel_id: int, path: str | None, kind: str) -> str | None:
    return f"/api/channels/{channel_id}/{kind}" if path else None


def channel_ref(row: dict[str, Any], prefix: str = "channel_") -> dict[str, Any] | None:
    if row.get("channel_id") is None:
        return None
    return {
        "id": row["channel_id"],
        "youtube_id": row[f"{prefix}youtube_id"],
        "name": row[f"{prefix}name"],
    }


def active_job(row: dict[str, Any]) -> dict[str, Any] | None:
    """The latest download job while it is queued, paused or running."""
    if row["job_status"] not in ("queued", "paused", "running"):
        return None
    return {
        "status": row["job_status"],
        "run_after": row["job_run_after"],
        "attempts": row["job_attempts"],
        "error": row["job_error"],
    }


def video_out(row: dict[str, Any]) -> dict[str, Any]:
    video_id = row["id"]
    fps = row["fps"]
    return {
        "id": video_id,
        "youtube_id": row["youtube_id"],
        "title": row["title"],
        "description": row["description"],
        "channel": channel_ref(row),
        "duration": row["duration"],
        "published_at": row["published_at"],
        "view_count": row["view_count"],
        "like_count": row["like_count"],
        "comment_count": row["comment_count"],
        "video_type": row["video_type"],
        "status": row["status"],
        "job_id": row["job_id"],
        "job": active_job(row),
        "error": row["job_error"] if row["status"] == "failed" else None,
        "unavailable": row["unavailable_at"] is not None,
        "unavailable_at": row["unavailable_at"],
        "availability": row["availability"],
        "age_limit": row["age_limit"],
        "fps": int(fps) if fps is not None and fps == int(fps) else fps,
        "vcodec": row["vcodec"],
        "acodec": row["acodec"],
        "dynamic_range": row["dynamic_range"],
        "audio_languages": loads(row["audio_languages"]) or [],
        "media_size": row["media_size"],
        "width": row["width"],
        "height": row["height"],
        "quality": quality_label(row["width"], row["height"]),
        "media_path": row["media_path"],
        "archived_at": row["archived_at"],
        "watched_at": row["watched_at"],
        "deleted_at": row["deleted_at"],
        "created_at": row["created_at"],
        "youtube_url": video_url(row["youtube_id"]),
        "thumbnail_url": f"/api/videos/{video_id}/thumbnail?v={row['archived_at']}"
        if row["media_path"]
        else None,
        "media_url": f"/api/videos/{video_id}/media",
    }


async def load_video(db: Database, video_id: int) -> dict[str, Any]:
    row = await db.fetch_one(f"{VIDEO_SELECT} WHERE v.id = ?", (video_id,))
    if not row:
        raise not_found("Video")
    return row
