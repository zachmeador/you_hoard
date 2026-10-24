"""Video library, downloads and authenticated local playback."""

import asyncio
import shutil
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.api.dependencies import get_db, get_downloader
from app.core.database import Database
from app.core.downloader import Downloader
from app.core.library import save_video
from app.core.security import get_auth
from app.core.storage import media_file, removable_directory, stored_path
from app.core.youtube import video_id_from_url
from app.models.video import (
    VideoBulkOperation,
    VideoCreate,
    VideoDownloadRequest,
    VideoListResponse,
    VideoResponse,
    VideoUpdate,
)

router = APIRouter()


def response_video(video):
    video["extra_metadata"] = Database.json_decode(video.get("extra_metadata"))
    return VideoResponse(**video)


@router.get("", response_model=VideoListResponse)
async def list_videos(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    channel_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth),
):
    clauses, params = [], []
    if channel_id:
        clauses.append("v.channel_id = ?")
        params.append(channel_id)
    if status:
        clauses.append("v.download_status = ?")
        params.append(status)
    else:
        clauses.append("v.download_status != 'deleted'")
    if search:
        clauses.append("(v.title LIKE ? OR v.description LIKE ? OR c.name LIKE ?)")
        params.extend([f"%{search}%"] * 3)
    where = " AND ".join(clauses)
    joined = "FROM videos v JOIN channels c ON c.id = v.channel_id"
    count = await db.execute_one(f"SELECT COUNT(*) AS total {joined} WHERE {where}", tuple(params))
    videos = await db.execute(
        f"SELECT v.*, c.name AS channel_name {joined} WHERE {where} "
        "ORDER BY v.created_at DESC, v.id DESC LIMIT ? OFFSET ?",
        tuple(params + [per_page, (page - 1) * per_page]),
    )
    tags_by_video = {video["id"]: [] for video in videos}
    if videos:
        placeholders = ", ".join("?" for _ in videos)
        tags = await db.execute(
            "SELECT vt.video_id, t.id, t.name, t.color "
            "FROM tags t JOIN video_tags vt ON vt.tag_id = t.id "
            f"WHERE vt.video_id IN ({placeholders})",
            tuple(tags_by_video),
        )
        for tag in tags:
            tags_by_video[tag.pop("video_id")].append(tag)
    for video in videos:
        video["tags"] = tags_by_video[video["id"]]
    return VideoListResponse(
        videos=[response_video(v) for v in videos],
        total=count["total"],
        page=page,
        per_page=per_page,
    )


@router.get("/{video_id}", response_model=VideoResponse)
async def get_video(video_id: int, db: Database = Depends(get_db), _: dict = Depends(get_auth)):
    video = await db.execute_one(
        "SELECT v.*, c.name AS channel_name FROM videos v JOIN channels c ON c.id = v.channel_id WHERE v.id = ?",
        (video_id,),
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    video["tags"] = await db.execute(
        "SELECT t.id, t.name, t.color FROM tags t JOIN video_tags vt ON vt.tag_id = t.id WHERE vt.video_id = ?",
        (video_id,),
    )
    return response_video(video)


@router.post("", response_model=VideoResponse, status_code=201)
async def create_video(
    video_data: VideoCreate,
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth),
):
    youtube_id = video_id_from_url(video_data.url) if video_data.url else video_data.youtube_id
    existing = await db.execute_one("SELECT id FROM videos WHERE youtube_id = ?", (youtube_id,))
    if existing:
        raise HTTPException(
            status_code=409, detail=f"This video is already in your library (#{existing['id']})."
        )
    try:
        info = await downloader.extract_info(f"https://www.youtube.com/watch?v={youtube_id}")
        if info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
            raise ValueError("Only finished videos and completed livestreams can be archived")
        if info.get("id") != youtube_id:
            raise ValueError("YouTube returned metadata for a different video")
        video_id, created = await save_video(db, info)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502, detail=f"Could not read YouTube metadata: {error}"
        ) from error
    if not created:
        raise HTTPException(
            status_code=409, detail=f"This video is already in your library (#{video_id})."
        )
    await downloader.queue_download(video_id, priority=5, quality=video_data.quality)
    return await get_video(video_id, db, _)


@router.put("/{video_id}", response_model=VideoResponse)
async def update_video(
    video_id: int,
    video_update: VideoUpdate,
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth),
):
    await get_video(video_id, db, _)
    data = video_update.model_dump(exclude_unset=True)
    if "extra_metadata" in data:
        data["extra_metadata"] = Database.json_encode(data["extra_metadata"])
    if data:
        await db.update("videos", data, "id = ?", (video_id,))
    return await get_video(video_id, db, _)


@router.delete("/{video_id}")
async def delete_video(video_id: int, db: Database = Depends(get_db), _: dict = Depends(get_auth)):
    async with db.get_db() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cursor = await conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
        video = await cursor.fetchone()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        cursor = await conn.execute(
            "SELECT id FROM job_queue WHERE video_id = ? AND status IN ('queued', 'downloading', 'processing')",
            (video_id,),
        )
        if await cursor.fetchone():
            raise HTTPException(
                status_code=409,
                detail="Remove queued work or wait for the active download before deleting.",
            )
        if video["file_path"]:
            try:
                directory = removable_directory(video["file_path"], video["youtube_id"])
                if directory.exists():
                    await asyncio.to_thread(shutil.rmtree, directory)
            except ValueError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
        await conn.execute("DELETE FROM job_queue WHERE video_id = ?", (video_id,))
        # Keep a tombstone so subscriptions cannot silently rediscover/re-download it.
        await conn.execute(
            "UPDATE videos SET download_status = 'deleted', file_path = NULL, file_size = NULL, "
            "thumbnail_path = NULL WHERE id = ?",
            (video_id,),
        )
        await conn.commit()
    return {
        "message": "Local files removed. The video remains remembered and will not be downloaded automatically."
    }


@router.post("/{video_id}/download")
async def queue_video_download(
    video_id: int,
    download_request: VideoDownloadRequest,
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth),
):
    await get_video(video_id, db, _)
    try:
        queue_id = await downloader.queue_download(
            video_id, download_request.priority, download_request.quality_override
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"message": "Video queued for download", "queue_id": queue_id}


@router.post("/bulk")
async def bulk_operation(
    bulk_op: VideoBulkOperation,
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth),
):
    result = {"success": 0, "failed": 0, "errors": []}
    for video_id in bulk_op.video_ids:
        try:
            if bulk_op.operation == "delete":
                await delete_video(video_id, db, _)
            elif bulk_op.operation == "download":
                await queue_video_download(
                    video_id, VideoDownloadRequest(**(bulk_op.params or {})), db, downloader, _
                )
            else:
                raise ValueError("Only bulk download and delete are supported")
            result["success"] += 1
        except Exception as error:
            result["failed"] += 1
            result["errors"].append({"video_id": video_id, "error": str(error)})
    return result


@router.api_route("/{video_id}/file", methods=["GET", "HEAD"])
async def get_video_file(
    video_id: int, db: Database = Depends(get_db), _: dict = Depends(get_auth)
):
    video = await db.execute_one(
        "SELECT file_path, download_status FROM videos WHERE id = ?", (video_id,)
    )
    if not video or video["download_status"] != "completed" or not video["file_path"]:
        raise HTTPException(status_code=404, detail="No local video available")
    try:
        path = media_file(video["file_path"])
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Local video file is missing")
    return FileResponse(
        path, content_disposition_type="inline", headers={"Cache-Control": "private"}
    )


@router.get("/{video_id}/thumbnail")
async def get_video_thumbnail(
    video_id: int, db: Database = Depends(get_db), _: dict = Depends(get_auth)
):
    video = await db.execute_one("SELECT thumbnail_path FROM videos WHERE id = ?", (video_id,))
    if not video or not video["thumbnail_path"]:
        raise HTTPException(status_code=404, detail="Thumbnail not available")
    try:
        path = stored_path(video["thumbnail_path"])
    except ValueError:
        raise HTTPException(status_code=404, detail="Thumbnail not available")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail file not found")
    return FileResponse(path, headers={"Cache-Control": "private"})
