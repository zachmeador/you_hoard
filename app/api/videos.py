"""The library: list, add, download, remove and play videos."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from app import layout
from app.api.deps import get_db, get_runner, get_youtube, load_video, not_found, video_out
from app.db import Database, now
from app.jobs import JobRunner
from app.library import VIDEO_SELECT, save_video_info
from app.youtube import (
    QUALITIES,
    Inaccessible,
    NotReady,
    Unavailable,
    YouTube,
    YouTubeError,
    parse_video_url,
)

router = APIRouter()
Quality = Literal[tuple(QUALITIES)]
SORTS = {
    "published": "v.published_at",
    "archived": "v.archived_at",
    "added": "v.created_at",
    "title": "v.title COLLATE NOCASE",
    "duration": "v.duration",
}
STATUSES = ("archived", "downloading", "queued", "failed", "deleted", "missing")


class AddVideo(BaseModel):
    url: str
    quality: Quality | None = None

    @field_validator("url")
    @classmethod
    def video_id(cls, value: str) -> str:
        return parse_video_url(value)


class DownloadRequest(BaseModel):
    quality: Quality | None = None


class Watched(BaseModel):
    watched: bool


@router.get("")
async def list_videos(
    q: str | None = None,
    status: Literal[STATUSES] | None = None,
    video_type: Literal["video", "short", "live"] | None = None,
    channel_id: int | None = None,
    watched: bool | None = None,
    sort: Literal[tuple(SORTS)] = "published",
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    per_page: int = Query(48, ge=1, le=200),
    db: Database = Depends(get_db),
):
    clauses, params = [], []
    if status:
        clauses.append("s.status = ?")
        params.append(status)
    else:
        clauses.append("s.status != 'deleted'")
    if q:
        clauses.append("(v.title LIKE ? OR v.description LIKE ? OR c.name LIKE ?)")
        params += [f"%{q.strip()}%"] * 3
    if video_type:
        clauses.append("v.video_type = ?")
        params.append(video_type)
    if channel_id is not None:
        clauses.append("v.channel_id = ?")
        params.append(channel_id)
    if watched is not None:
        clauses.append(f"v.watched_at IS {'NOT ' if watched else ''}NULL")
    where = " AND ".join(clauses)
    total = await db.fetch_value(
        "SELECT count(*) FROM videos v JOIN video_status s ON s.video_id = v.id "
        f"LEFT JOIN channels c ON c.id = v.channel_id WHERE {where}",
        params,
    )
    direction = order.upper()
    rows = await db.fetch_all(
        f"{VIDEO_SELECT} WHERE {where} "
        f"ORDER BY {SORTS[sort]} {direction} NULLS LAST, v.id {direction} LIMIT ? OFFSET ?",
        [*params, per_page, (page - 1) * per_page],
    )
    return {
        "items": [video_out(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/{video_id}")
async def get_video(video_id: int, db: Database = Depends(get_db)):
    row = await load_video(db, video_id)
    video = video_out(row)
    video["subtitles"] = []
    if row["media_path"]:
        try:
            media = layout.media_file(row["media_path"], row["youtube_id"])
        except layout.PathError:
            media = None
        if media is not None:
            video["subtitles"] = [
                {"lang": lang, "url": f"/api/videos/{video_id}/subtitles/{lang}"}
                for lang in layout.subtitles_for(media)
            ]
    return video


@router.post("", status_code=201)
async def add_video(
    body: AddVideo,
    db: Database = Depends(get_db),
    runner: JobRunner = Depends(get_runner),
    youtube: YouTube = Depends(get_youtube),
):
    youtube_id = body.url
    existing = await db.fetch_one(f"{VIDEO_SELECT} WHERE v.youtube_id = ?", (youtube_id,))
    if existing and existing["status"] in ("archived", "queued", "downloading"):
        state = "archived" if existing["status"] == "archived" else "queued"
        raise HTTPException(
            status_code=409, detail=f"Already {state} in your library: {existing['title']}"
        )
    info = None
    if not existing:
        try:
            info = await youtube.fetch_video(youtube_id)
        except NotReady:
            info = None
        except (Unavailable, Inaccessible) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except YouTubeError as error:
            raise HTTPException(status_code=502, detail=f"YouTube: {error}") from error
    options = {"quality": body.quality} if body.quality else {}
    async with db.transaction() as conn:
        if existing:
            video_id = existing["id"]
        elif info and info.get("id") == youtube_id:
            video_id, _ = await save_video_info(conn, info)
        else:
            cursor = await conn.execute(
                "INSERT INTO videos (youtube_id, title) VALUES (?, ?)", (youtube_id, youtube_id)
            )
            video_id = cursor.lastrowid
        await conn.execute("UPDATE videos SET deleted_at = NULL WHERE id = ?", (video_id,))
        await runner.enqueue("download", video_id=video_id, options=options, priority=10, conn=conn)
    return video_out(await load_video(db, video_id))


@router.post("/{video_id}/download")
async def download_video(
    video_id: int,
    body: DownloadRequest | None = None,
    db: Database = Depends(get_db),
    runner: JobRunner = Depends(get_runner),
):
    video = await load_video(db, video_id)
    if video["status"] == "archived":
        raise HTTPException(status_code=409, detail="This video is already archived")
    options = {"quality": body.quality} if body and body.quality else {}
    async with db.transaction() as conn:
        await conn.execute("UPDATE videos SET deleted_at = NULL WHERE id = ?", (video_id,))
        job_id = await runner.enqueue(
            "download", video_id=video_id, options=options, priority=10, conn=conn
        )
    return {"job_id": job_id}


@router.delete("/{video_id}")
async def delete_video(video_id: int, db: Database = Depends(get_db)):
    video = await load_video(db, video_id)
    if video["status"] in ("queued", "downloading"):
        raise HTTPException(status_code=409, detail="Cancel the download in the queue first")
    if video["media_path"]:
        try:
            await asyncio.to_thread(layout.remove_media, video["media_path"], video["youtube_id"])
        except layout.PathError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
    await db.execute(
        "UPDATE videos SET media_path = NULL, media_size = NULL, width = NULL, height = NULL, "
        "deleted_at = ?, updated_at = ? WHERE id = ?",
        (now(), now(), video_id),
    )
    return {"ok": True}


@router.post("/{video_id}/watched")
async def set_watched(video_id: int, body: Watched, db: Database = Depends(get_db)):
    await load_video(db, video_id)
    await db.execute(
        "UPDATE videos SET watched_at = ? WHERE id = ?", (now() if body.watched else None, video_id)
    )
    return video_out(await load_video(db, video_id))


async def archived_media(db: Database, video_id: int):
    video = await db.fetch_one(
        "SELECT youtube_id, media_path FROM videos WHERE id = ?", (video_id,)
    )
    if not video or not video["media_path"]:
        raise not_found("Local video")
    try:
        media = layout.media_file(video["media_path"], video["youtube_id"])
    except layout.PathError as error:
        raise not_found("Local video") from error
    if not media.is_file():
        raise not_found("Local video file")
    return media


@router.api_route("/{video_id}/media", methods=["GET", "HEAD"])
async def media(video_id: int, db: Database = Depends(get_db)):
    path = await archived_media(db, video_id)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{video_id}/thumbnail")
async def thumbnail(video_id: int, db: Database = Depends(get_db)):
    path = layout.thumbnail_for(await archived_media(db, video_id))
    if path is None:
        raise not_found("Thumbnail")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


@router.get("/{video_id}/subtitles/{lang}")
async def subtitles(video_id: int, lang: str, db: Database = Depends(get_db)):
    path = layout.subtitles_for(await archived_media(db, video_id)).get(lang)
    if path is None:
        raise not_found("Subtitles")
    return FileResponse(path, media_type="text/vtt", headers={"Cache-Control": "private"})
