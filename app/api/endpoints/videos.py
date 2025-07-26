"""
Video management endpoints
"""
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from datetime import datetime
import mimetypes

from app.core.config import settings
from app.core.database import Database
from app.core.downloader import Downloader
from app.core.metadata import classify_video_type
from app.core.quality import QualityService
from app.core.security import SessionBearer, SecurityManager
from app.models.video import (
    VideoCreate, VideoUpdate, VideoResponse, VideoListResponse, 
    VideoDownloadRequest, VideoBulkOperation
)

router = APIRouter()


def get_db(request: Request) -> Database:
    """Get database from app state"""
    return request.app.state.db


def get_downloader(request: Request) -> Downloader:
    """Get downloader from app state"""
    if not hasattr(request.app.state, 'downloader'):
        request.app.state.downloader = Downloader(request.app.state.db)
    return request.app.state.downloader


def get_auth(request: Request) -> SessionBearer:
    """Get auth dependency"""
    security_manager = SecurityManager(request.app.state.db)
    return SessionBearer(security_manager)


@router.get("", response_model=VideoListResponse)
async def list_videos(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    channel_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth)
):
    """
    List videos with filtering and pagination
    """
    offset = (page - 1) * per_page
    
    # Build query
    where_clauses = ["1=1"]
    params = []
    
    if channel_id:
        where_clauses.append("v.channel_id = ?")
        params.append(channel_id)
    
    if status:
        where_clauses.append("v.download_status = ?")
        params.append(status)
    
    if search:
        where_clauses.append("(v.title LIKE ? OR v.description LIKE ?)")
        search_param = f"%{search}%"
        params.extend([search_param, search_param])
    
    where_clause = " AND ".join(where_clauses)
    
    # Get total count
    count_query = f"SELECT COUNT(*) as total FROM videos v WHERE {where_clause}"
    total_result = await db.execute_one(count_query, tuple(params))
    total = total_result['total'] if total_result else 0
    
    # Get videos
    query = f"""
        SELECT v.*, c.name as channel_name
        FROM videos v
        JOIN channels c ON v.channel_id = c.id
        WHERE {where_clause}
        ORDER BY v.created_at DESC
        LIMIT ? OFFSET ?
    """
    params.extend([per_page, offset])
    videos = await db.execute(query, tuple(params))
    
    # Get tags for videos
    video_ids = [v['id'] for v in videos]
    if video_ids:
        tags_query = """
            SELECT vt.video_id, t.id, t.name, t.color
            FROM video_tags vt
            JOIN tags t ON vt.tag_id = t.id
            WHERE vt.video_id IN ({})
        """.format(','.join('?' * len(video_ids)))
        tags_result = await db.execute(tags_query, tuple(video_ids))
        
        # Group tags by video
        video_tags = {}
        for tag in tags_result:
            if tag['video_id'] not in video_tags:
                video_tags[tag['video_id']] = []
            video_tags[tag['video_id']].append({
                'id': tag['id'],
                'name': tag['name'],
                'color': tag['color']
            })
        
        # Add tags to videos
        for video in videos:
            video['tags'] = video_tags.get(video['id'], [])
    
    return VideoListResponse(
        videos=[VideoResponse(**v) for v in videos],
        total=total,
        page=page,
        per_page=per_page
    )


@router.get("/{video_id}", response_model=VideoResponse)
async def get_video(
    video_id: int,
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth)
):
    """
    Get video details
    """
    video = await db.execute_one(
        """SELECT v.*, c.name as channel_name
           FROM videos v
           JOIN channels c ON v.channel_id = c.id
           WHERE v.id = ?""",
        (video_id,)
    )
    
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found"
        )
    
    # Get tags
    tags = await db.execute(
        """SELECT t.id, t.name, t.color
           FROM video_tags vt
           JOIN tags t ON vt.tag_id = t.id
           WHERE vt.video_id = ?""",
        (video_id,)
    )
    
    video['tags'] = tags
    
    return VideoResponse(**video)


@router.post("", response_model=VideoResponse)
async def create_video(
    video_data: VideoCreate,
    request: Request,
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth)
):
    """
    Add video by URL or YouTube ID
    """
    # Extract video info
    if video_data.url:
        info = await downloader.extract_info(video_data.url)
        youtube_id = info.get('id')
        
        # Extract channel info
        channel_info = info.get('channel') or info.get('uploader')
        channel_id_yt = info.get('channel_id') or info.get('uploader_id')
        
    else:
        youtube_id = video_data.youtube_id
        # Need to extract info to get channel
        url = f"https://www.youtube.com/watch?v={youtube_id}"
        info = await downloader.extract_info(url)
        channel_info = info.get('channel') or info.get('uploader')
        channel_id_yt = info.get('channel_id') or info.get('uploader_id')
    
    # Check if video already exists
    existing = await db.execute_one(
        "SELECT id FROM videos WHERE youtube_id = ?",
        (youtube_id,)
    )
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Video already exists"
        )
    
    # Create or get channel
    channel = await db.execute_one(
        "SELECT id FROM channels WHERE youtube_id = ?",
        (channel_id_yt,)
    )
    
    if not channel:
        # Create channel
        channel_id = await db.insert("channels", {
            "youtube_id": channel_id_yt,
            "name": channel_info or "Unknown Channel",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        })
    else:
        channel_id = channel['id']
    
    # Create video
    video_id = await db.insert("videos", {
        "youtube_id": youtube_id,
        "channel_id": channel_id,
        "title": info.get('title', 'Unknown Title'),
        "description": info.get('description'),
        "duration": info.get('duration'),
        "upload_date": info.get('upload_date'),
        "view_count": info.get('view_count'),
        "like_count": info.get('like_count'),
        "video_type": classify_video_type(info),
        "download_status": "pending",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    })
    
    # Resolve quality preference and auto-queue download
    # TODO: Extract user_id from auth context when available
    user_id = None
    
    resolved_quality = await QualityService.resolve_quality_preference(
        db,
        video_quality=video_data.quality,
        user_id=user_id
    )
    
    # Queue download with resolved quality
    await downloader.queue_download(video_id, priority=5, quality=resolved_quality)
    
    return await get_video(video_id, db, _)


@router.put("/{video_id}", response_model=VideoResponse)
async def update_video(
    video_id: int,
    video_update: VideoUpdate,
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth)
):
    """
    Update video metadata
    """
    # Check if video exists
    existing = await db.execute_one(
        "SELECT id FROM videos WHERE id = ?",
        (video_id,)
    )
    
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found"
        )
    
    # Update video
    update_data = video_update.dict(exclude_unset=True)
    if update_data:
        update_data['updated_at'] = datetime.utcnow().isoformat()
        
        if 'extra_metadata' in update_data:
            update_data['extra_metadata'] = Database.json_encode(update_data['extra_metadata'])
        
        await db.update("videos", update_data, "id = ?", (video_id,))
    
    return await get_video(video_id, db, _)


@router.delete("/{video_id}")
async def delete_video(
    video_id: int,
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth)
):
    """
    Delete video and associated data
    """
    # Check if video exists
    video = await db.execute_one(
        "SELECT * FROM videos WHERE id = ?",
        (video_id,)
    )
    
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found"
        )
    
    # Delete from queue if present
    await db.delete("download_queue", "video_id = ?", (video_id,))
    
    # Delete tags
    await db.delete("video_tags", "video_id = ?", (video_id,))
    
    # Delete video
    await db.delete("videos", "id = ?", (video_id,))
    
    # TODO: Delete physical files
    
    return {"message": "Video deleted successfully"}


@router.post("/{video_id}/download")
async def queue_video_download(
    video_id: int,
    download_request: VideoDownloadRequest,
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth)
):
    """
    Queue video for download
    """
    # Check if video exists
    video = await db.execute_one(
        "SELECT * FROM videos WHERE id = ?",
        (video_id,)
    )
    
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found"
        )
    
    # Check if already in queue
    existing_queue = await db.execute_one(
        "SELECT id FROM download_queue WHERE video_id = ? AND status IN ('queued', 'downloading')",
        (video_id,)
    )
    
    if existing_queue:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Video already in download queue"
        )
    
    # Resolve quality preference and queue download
    # For manual downloads, try to get user from auth context
    user_id = None  # TODO: Extract from auth context when available
    
    resolved_quality = await QualityService.resolve_quality_preference(
        db,
        video_quality=download_request.quality_override,
        user_id=user_id
    )
    
    queue_id = await downloader.queue_download(video_id, download_request.priority, resolved_quality)
    
    return {"message": "Video queued for download", "queue_id": queue_id}


@router.post("/bulk", response_model=dict)
async def bulk_operation(
    bulk_op: VideoBulkOperation,
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth)
):
    """
    Perform bulk operations on videos
    """
    results = {"success": 0, "failed": 0, "errors": []}
    
    for video_id in bulk_op.video_ids:
        try:
            if bulk_op.operation == "delete":
                await delete_video(video_id, db, _)
                results["success"] += 1
                
            elif bulk_op.operation == "download":
                priority = bulk_op.params.get("priority", 0) if bulk_op.params else 0
                await downloader.queue_download(video_id, priority)
                results["success"] += 1
                
            elif bulk_op.operation == "tag":
                if not bulk_op.params or "tag_id" not in bulk_op.params:
                    raise ValueError("tag_id required in params")
                
                # Add tag
                try:
                    await db.insert("video_tags", {
                        "video_id": video_id,
                        "tag_id": bulk_op.params["tag_id"]
                    })
                    results["success"] += 1
                except:
                    # Tag might already exist
                    results["failed"] += 1
                    
            elif bulk_op.operation == "update_status":
                if not bulk_op.params or "status" not in bulk_op.params:
                    raise ValueError("status required in params")
                
                await db.update(
                    "videos",
                    {"download_status": bulk_op.params["status"]},
                    "id = ?",
                    (video_id,)
                )
                results["success"] += 1
                
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({"video_id": video_id, "error": str(e)})
    
    return results 


@router.get("/{video_id}/thumbnail")
async def get_video_thumbnail(
    video_id: int,
    db: Database = Depends(get_db)
):
    """Get video thumbnail"""
    video = await db.execute_one(
        "SELECT thumbnail_path, youtube_id FROM videos WHERE id = ?",
        (video_id,)
    )
    
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    if not video['thumbnail_path']:
        raise HTTPException(status_code=404, detail="Thumbnail not available")
    
    # Construct full path
    thumbnail_path = settings.get_storage_path() / video['thumbnail_path']
    
    if not thumbnail_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail file not found")
    
    # Determine content type
    content_type, _ = mimetypes.guess_type(str(thumbnail_path))
    if not content_type:
        content_type = "image/jpeg"
    
    return FileResponse(
        path=str(thumbnail_path),
        media_type=content_type,
        filename=f"{video['youtube_id']}_thumbnail.{thumbnail_path.suffix[1:]}"
    ) 