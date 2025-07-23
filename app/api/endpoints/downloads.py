"""
Download queue management endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel

from app.core.database import Database
from app.core.downloader import Downloader, DownloadProgress
from app.core.security import SessionBearer, SecurityManager


router = APIRouter()


class DownloadQueueItem(BaseModel):
    """Download queue item response"""
    id: int
    video_id: int
    video_title: str
    channel_name: str
    priority: int
    status: str
    progress: float
    speed: Optional[float] = None
    eta: Optional[int] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime


class DownloadQueueResponse(BaseModel):
    """Response for download queue list"""
    downloads: List[DownloadQueueItem]
    total: int
    active_count: int
    queued_count: int
    failed_count: int


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


@router.get("", response_model=DownloadQueueResponse)
async def list_downloads(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth)
):
    """
    List download queue with filtering
    """
    # Build query
    where_clause = "1=1"
    params = []
    
    if status:
        where_clause += " AND dq.status = ?"
        params.append(status)
    
    # Get downloads
    query = f"""
        SELECT dq.*, v.title as video_title, c.name as channel_name
        FROM download_queue dq
        JOIN videos v ON dq.video_id = v.id
        JOIN channels c ON v.channel_id = c.id
        WHERE {where_clause}
        ORDER BY 
            CASE dq.status 
                WHEN 'downloading' THEN 1 
                WHEN 'queued' THEN 2 
                WHEN 'paused' THEN 3
                WHEN 'failed' THEN 4
                ELSE 5 
            END,
            dq.priority DESC,
            dq.created_at ASC
        LIMIT ?
    """
    params.append(limit)
    downloads = await db.execute(query, tuple(params))
    
    # Get active downloads info
    active_downloads = downloader.get_active_downloads()
    
    # Merge active download progress
    for download in downloads:
        if download['status'] == 'downloading' and download['video_id'] in active_downloads:
            active = active_downloads[download['video_id']]
            download['progress'] = active.progress
            download['speed'] = active.speed
            download['eta'] = active.eta
    
    # Get counts
    count_query = """
        SELECT 
            COUNT(*) as total,
            COUNT(CASE WHEN status = 'downloading' THEN 1 END) as active_count,
            COUNT(CASE WHEN status = 'queued' THEN 1 END) as queued_count,
            COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_count
        FROM download_queue
    """
    counts = await db.execute_one(count_query)
    
    return DownloadQueueResponse(
        downloads=[DownloadQueueItem(**d) for d in downloads],
        total=counts['total'],
        active_count=counts['active_count'],
        queued_count=counts['queued_count'],
        failed_count=counts['failed_count']
    )


@router.post("/{download_id}/pause")
async def pause_download(
    download_id: int,
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth)
):
    """
    Pause a download
    """
    # Check if download exists
    download = await db.execute_one(
        "SELECT * FROM download_queue WHERE id = ?",
        (download_id,)
    )
    
    if not download:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found"
        )
    
    if download['status'] not in ['queued', 'downloading']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot pause download with status: {download['status']}"
        )
    
    # Update status
    await db.update(
        "download_queue",
        {"status": "paused"},
        "id = ?",
        (download_id,)
    )
    
    # TODO: Actually pause the download if it's active
    
    return {"message": "Download paused"}


@router.post("/{download_id}/resume")
async def resume_download(
    download_id: int,
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth)
):
    """
    Resume a paused download
    """
    # Check if download exists
    download = await db.execute_one(
        "SELECT * FROM download_queue WHERE id = ?",
        (download_id,)
    )
    
    if not download:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found"
        )
    
    if download['status'] != 'paused':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot resume download with status: {download['status']}"
        )
    
    # Update status and re-queue
    await db.update(
        "download_queue",
        {"status": "queued"},
        "id = ?",
        (download_id,)
    )
    
    # Re-process download
    import asyncio
    asyncio.create_task(downloader._process_download(download['video_id']))
    
    return {"message": "Download resumed"}


@router.post("/{download_id}/retry")
async def retry_download(
    download_id: int,
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth)
):
    """
    Retry a failed download
    """
    # Check if download exists
    download = await db.execute_one(
        "SELECT * FROM download_queue WHERE id = ?",
        (download_id,)
    )
    
    if not download:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found"
        )
    
    if download['status'] != 'failed':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot retry download with status: {download['status']}"
        )
    
    # Reset download
    await db.update(
        "download_queue",
        {
            "status": "queued",
            "progress": 0.0,
            "error_message": None,
            "started_at": None,
            "completed_at": None
        },
        "id = ?",
        (download_id,)
    )
    
    # Reset video status
    await db.update(
        "videos",
        {"download_status": "pending"},
        "id = ?",
        (download['video_id'],)
    )
    
    # Re-process download
    import asyncio
    asyncio.create_task(downloader._process_download(download['video_id']))
    
    return {"message": "Download retry queued"}


@router.delete("/{download_id}")
async def cancel_download(
    download_id: int,
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth)
):
    """
    Cancel and remove a download from queue
    """
    # Check if download exists
    download = await db.execute_one(
        "SELECT * FROM download_queue WHERE id = ?",
        (download_id,)
    )
    
    if not download:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found"
        )
    
    # TODO: Stop download if active
    
    # Delete from queue
    await db.delete("download_queue", "id = ?", (download_id,))
    
    # Update video status if not completed
    if download['status'] != 'completed':
        await db.update(
            "videos",
            {"download_status": "pending"},
            "id = ?",
            (download['video_id'],)
        )
    
    return {"message": "Download cancelled"}


@router.post("/clear-completed")
async def clear_completed_downloads(
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth)
):
    """
    Remove all completed downloads from queue
    """
    deleted = await db.delete(
        "download_queue",
        "status = ?",
        ("completed",)
    )
    
    return {"message": f"Cleared {deleted} completed downloads"}


@router.post("/retry-all-failed")
async def retry_all_failed(
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth)
):
    """
    Retry all failed downloads
    """
    # Get failed downloads
    failed_downloads = await db.execute(
        "SELECT * FROM download_queue WHERE status = ?",
        ("failed",)
    )
    
    # Reset each failed download
    for download in failed_downloads:
        await db.update(
            "download_queue",
            {
                "status": "queued",
                "progress": 0.0,
                "error_message": None,
                "started_at": None,
                "completed_at": None
            },
            "id = ?",
            (download['id'],)
        )
        
        await db.update(
            "videos",
            {"download_status": "pending"},
            "id = ?",
            (download['video_id'],)
        )
        
        # Re-process download
        import asyncio
        asyncio.create_task(downloader._process_download(download['video_id']))
    
    return {"message": f"Retrying {len(failed_downloads)} failed downloads"} 