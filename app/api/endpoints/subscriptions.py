"""
Subscription management endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from typing import Optional
from datetime import datetime

from app.core.database import Database
from app.core.downloader import Downloader
from app.core.security import SessionBearer, SecurityManager
from app.models.subscription import (
    SubscriptionCreate, SubscriptionUpdate,
    SubscriptionResponse, SubscriptionListResponse,
    SubscriptionCheckResult
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


def get_scheduler(request: Request):
    """Get scheduler from app state"""
    return request.app.state.scheduler


@router.get("", response_model=SubscriptionListResponse)
async def list_subscriptions(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    enabled_only: bool = False,
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth)
):
    """
    List subscriptions with pagination
    """
    offset = (page - 1) * per_page
    
    # Build query
    where_clause = "1=1"
    params = []
    
    if enabled_only:
        where_clause += " AND s.enabled = 1"
    
    # Get total count
    count_query = f"SELECT COUNT(*) as total FROM subscriptions s WHERE {where_clause}"
    total_result = await db.execute_one(count_query, tuple(params))
    total = total_result['total'] if total_result else 0
    
    # Get subscriptions
    query = f"""
        SELECT s.*, c.name as channel_name, c.youtube_id as channel_youtube_id
        FROM subscriptions s
        JOIN channels c ON s.channel_id = c.id
        WHERE {where_clause}
        ORDER BY s.created_at DESC
        LIMIT ? OFFSET ?
    """
    params.extend([per_page, offset])
    subscriptions = await db.execute(query, tuple(params))
    
    # Calculate next check time for each subscription
    # TODO: Implement proper cron parsing
    for sub in subscriptions:
        sub['next_check'] = None  # Placeholder
        sub['new_videos_count'] = 0  # Placeholder
    
    return SubscriptionListResponse(
        subscriptions=[SubscriptionResponse(**s) for s in subscriptions],
        total=total,
        page=page,
        per_page=per_page
    )


@router.post("", response_model=SubscriptionResponse)
async def create_subscription(
    subscription_data: SubscriptionCreate,
    request: Request,
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    scheduler = Depends(get_scheduler),
    _: dict = Depends(get_auth)
):
    """
    Create new subscription
    """
    # Extract channel info from URL
    info = await downloader.extract_info(subscription_data.source_url)
    
    if subscription_data.subscription_type == "channel":
        channel_id_yt = info.get('channel_id') or info.get('uploader_id')
        channel_name = info.get('channel') or info.get('uploader')
    else:
        # For playlists
        channel_id_yt = info.get('uploader_id', 'playlist_' + info.get('id', 'unknown'))
        channel_name = info.get('uploader', info.get('title', 'Unknown Playlist'))
    
    # Check if channel exists
    channel = await db.execute_one(
        "SELECT id FROM channels WHERE youtube_id = ?",
        (channel_id_yt,)
    )
    
    if not channel:
        # Create channel
        channel_id = await db.insert("channels", {
            "youtube_id": channel_id_yt,
            "name": channel_name,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        })
    else:
        channel_id = channel['id']
    
    # Check if subscription already exists
    existing = await db.execute_one(
        "SELECT id FROM subscriptions WHERE channel_id = ? AND source_url = ?",
        (channel_id, subscription_data.source_url)
    )
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subscription already exists"
        )
    
    # Create subscription
    sub_data = subscription_data.dict()
    sub_data['channel_id'] = channel_id
    sub_data['created_at'] = datetime.utcnow().isoformat()
    
    if sub_data.get('subtitle_languages'):
        sub_data['subtitle_languages'] = Database.json_encode(sub_data['subtitle_languages'])
    if sub_data.get('audio_tracks'):
        sub_data['audio_tracks'] = Database.json_encode(sub_data['audio_tracks'])
    if sub_data.get('extra_metadata'):
        sub_data['extra_metadata'] = Database.json_encode(sub_data['extra_metadata'])
    
    subscription_id = await db.insert("subscriptions", sub_data)
    
    # Add to scheduler if enabled
    if sub_data.get('enabled', True):
        await scheduler.add_subscription(subscription_id, sub_data.get('check_frequency', '0 * * * *'))
    
    # Return created subscription
    return await get_subscription(subscription_id, db, _)


@router.get("/{subscription_id}", response_model=SubscriptionResponse)
async def get_subscription(
    subscription_id: int,
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth)
):
    """
    Get subscription details
    """
    subscription = await db.execute_one(
        """SELECT s.*, c.name as channel_name, c.youtube_id as channel_youtube_id
           FROM subscriptions s
           JOIN channels c ON s.channel_id = c.id
           WHERE s.id = ?""",
        (subscription_id,)
    )
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    
    # Decode JSON fields
    if subscription.get('subtitle_languages'):
        subscription['subtitle_languages'] = Database.json_decode(subscription['subtitle_languages'])
    if subscription.get('audio_tracks'):
        subscription['audio_tracks'] = Database.json_decode(subscription['audio_tracks'])
    if subscription.get('extra_metadata'):
        subscription['extra_metadata'] = Database.json_decode(subscription['extra_metadata'])
    
    # Add placeholders
    subscription['next_check'] = None  # TODO: Calculate from cron
    subscription['new_videos_count'] = 0  # TODO: Count new videos
    
    return SubscriptionResponse(**subscription)


@router.put("/{subscription_id}", response_model=SubscriptionResponse)
async def update_subscription(
    subscription_id: int,
    subscription_update: SubscriptionUpdate,
    db: Database = Depends(get_db),
    scheduler = Depends(get_scheduler),
    _: dict = Depends(get_auth)
):
    """
    Update subscription settings
    """
    # Check if subscription exists
    existing = await db.execute_one(
        "SELECT id FROM subscriptions WHERE id = ?",
        (subscription_id,)
    )
    
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    
    # Update subscription
    update_data = subscription_update.dict(exclude_unset=True)
    if update_data:
        if 'subtitle_languages' in update_data:
            update_data['subtitle_languages'] = Database.json_encode(update_data['subtitle_languages'])
        if 'audio_tracks' in update_data:
            update_data['audio_tracks'] = Database.json_encode(update_data['audio_tracks'])
        if 'extra_metadata' in update_data:
            update_data['extra_metadata'] = Database.json_encode(update_data['extra_metadata'])
        
        await db.update("subscriptions", update_data, "id = ?", (subscription_id,))
        
        # Update scheduler if enabled status or check frequency changed
        if 'enabled' in update_data or 'check_frequency' in update_data:
            # Get updated subscription
            updated_sub = await db.execute_one(
                "SELECT enabled, check_frequency FROM subscriptions WHERE id = ?",
                (subscription_id,)
            )
            
            if updated_sub:
                if updated_sub['enabled']:
                    await scheduler.update_subscription(subscription_id, updated_sub['check_frequency'])
                else:
                    await scheduler.remove_subscription(subscription_id)
    
    return await get_subscription(subscription_id, db, _)


@router.delete("/{subscription_id}")
async def delete_subscription(
    subscription_id: int,
    db: Database = Depends(get_db),
    scheduler = Depends(get_scheduler),
    _: dict = Depends(get_auth)
):
    """
    Delete subscription
    """
    # Check if subscription exists
    existing = await db.execute_one(
        "SELECT id FROM subscriptions WHERE id = ?",
        (subscription_id,)
    )
    
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    
    # Remove from scheduler
    await scheduler.remove_subscription(subscription_id)
    
    # Delete subscription
    await db.delete("subscriptions", "id = ?", (subscription_id,))
    
    return {"message": "Subscription deleted successfully"}


@router.post("/{subscription_id}/check")
async def check_subscription(
    subscription_id: int,
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth)
):
    """
    Manual check for new content in subscription
    """
    # Get subscription
    subscription = await db.execute_one(
        """SELECT s.*, c.youtube_id as channel_youtube_id, c.name as channel_name
           FROM subscriptions s
           JOIN channels c ON s.channel_id = c.id
           WHERE s.id = ?""",
        (subscription_id,)
    )
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    
    # Extract video list from channel/playlist
    info = await downloader.extract_info(subscription['source_url'])
    
    new_videos = []
    errors = []
    
    try:
        # Get list of videos
        entries = info.get('entries', [])
        
        for entry in entries[:20]:  # Check only recent 20 videos
            video_id = entry.get('id')
            if not video_id:
                continue
            
            # Check if video already exists
            existing = await db.execute_one(
                "SELECT id FROM videos WHERE youtube_id = ?",
                (video_id,)
            )
            
            if not existing:
                # Add new video
                try:
                    await db.insert("videos", {
                        "youtube_id": video_id,
                        "channel_id": subscription['channel_id'],
                        "title": entry.get('title', 'Unknown Title'),
                        "description": entry.get('description'),
                        "duration": entry.get('duration'),
                        "upload_date": entry.get('upload_date'),
                        "download_status": "pending",
                        "created_at": datetime.utcnow().isoformat(),
                        "updated_at": datetime.utcnow().isoformat()
                    })
                    new_videos.append({
                        "youtube_id": video_id,
                        "title": entry.get('title')
                    })
                except Exception as e:
                    errors.append(f"Failed to add video {video_id}: {str(e)}")
        
        # Update last check time
        await db.update(
            "subscriptions",
            {"last_check": datetime.utcnow().isoformat()},
            "id = ?",
            (subscription_id,)
        )
        
    except Exception as e:
        errors.append(f"Failed to check subscription: {str(e)}")
    
    return SubscriptionCheckResult(
        subscription_id=subscription_id,
        channel_name=subscription['channel_name'],
        new_videos=new_videos,
        errors=errors,
        checked_at=datetime.utcnow()
    )


@router.post("/{subscription_id}/pause")
async def pause_subscription(
    subscription_id: int,
    db: Database = Depends(get_db),
    scheduler = Depends(get_scheduler),
    _: dict = Depends(get_auth)
):
    """
    Pause subscription (set enabled to false)
    """
    # Check if subscription exists
    existing = await db.execute_one(
        "SELECT id FROM subscriptions WHERE id = ?",
        (subscription_id,)
    )
    
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    
    # Remove from scheduler
    await scheduler.remove_subscription(subscription_id)
    
    # Pause subscription
    await db.update(
        "subscriptions",
        {"enabled": False},
        "id = ?",
        (subscription_id,)
    )
    
    return {"message": "Subscription paused"}


@router.post("/{subscription_id}/resume")
async def resume_subscription(
    subscription_id: int,
    db: Database = Depends(get_db),
    scheduler = Depends(get_scheduler),
    _: dict = Depends(get_auth)
):
    """
    Resume subscription (set enabled to true)
    """
    # Check if subscription exists
    existing = await db.execute_one(
        "SELECT id FROM subscriptions WHERE id = ?",
        (subscription_id,)
    )
    
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    
    # Resume subscription
    await db.update(
        "subscriptions",
        {"enabled": True},
        "id = ?",
        (subscription_id,)
    )
    
    # Get subscription details and add to scheduler
    subscription = await db.execute_one(
        "SELECT check_frequency FROM subscriptions WHERE id = ?",
        (subscription_id,)
    )
    
    if subscription:
        await scheduler.add_subscription(subscription_id, subscription['check_frequency'])
    
    return {"message": "Subscription resumed"}


@router.get("/scheduler/status")
async def get_scheduler_status(
    scheduler = Depends(get_scheduler),
    _: dict = Depends(get_auth)
):
    """
    Get scheduler status and list of scheduled subscriptions
    """
    scheduled_jobs = scheduler.get_scheduled_subscriptions()
    
    return {
        "scheduler_running": scheduler._is_running,
        "scheduled_subscriptions": scheduled_jobs,
        "total_jobs": len(scheduled_jobs)
    } 