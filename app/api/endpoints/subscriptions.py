"""
Subscription management endpoints
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from typing import Optional
from datetime import datetime
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

from app.core.database import Database
from app.core.downloader import Downloader
from app.core.security import SessionBearer, SecurityManager
from app.core.metadata import classify_video_type
from app.core.ytdlp_service import get_ytdlp_service
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
    return getattr(request.app.state, 'scheduler', None)


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
    
    # Process subscription data and calculate next check time for each subscription
    for sub in subscriptions:
        # Decode JSON fields
        if sub.get('subtitle_languages'):
            sub['subtitle_languages'] = Database.json_decode(sub['subtitle_languages'])
        if sub.get('audio_tracks'):
            sub['audio_tracks'] = Database.json_decode(sub['audio_tracks'])
        if sub.get('content_types'):
            sub['content_types'] = Database.json_decode(sub['content_types'])
        if sub.get('extra_metadata'):
            sub['extra_metadata'] = Database.json_decode(sub['extra_metadata'])
        
        try:
            if sub.get('enabled') and sub.get('check_frequency'):
                trigger = CronTrigger.from_crontab(sub['check_frequency'])
                sub['next_check'] = trigger.get_next_fire_time(None, datetime.now())
            else:
                sub['next_check'] = None
        except Exception:
            # Invalid cron expression
            sub['next_check'] = None
    
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
    # Extract channel info from URL with comprehensive error handling
    try:
        logger.info(f"Extracting channel info from URL: {subscription_data.source_url}")
        info = await downloader.extract_info(subscription_data.source_url)
        logger.info(f"Successfully extracted channel info: {info.get('title', 'Unknown')}")
    except Exception as e:
        logger.error(f"Failed to extract channel info from {subscription_data.source_url}: {e}")
        error_str = str(e).lower()
        
        # Provide specific error messages based on the type of failure
        if any(keyword in error_str for keyword in ['403', 'forbidden', 'blocked']):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "YouTube Blocking Detected",
                    "message": "YouTube is currently blocking requests. This might be due to rate limiting or anti-bot detection.",
                    "suggestions": [
                        "Try again in a few minutes",
                        "Check if the URL is accessible in your browser",
                        "The content might be private or geo-restricted"
                    ],
                    "technical_details": str(e)
                }
            )
        elif any(keyword in error_str for keyword in ['timeout', 'timed out']):
            raise HTTPException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                detail={
                    "error": "Request Timeout", 
                    "message": "The request took too long to complete. YouTube might be slow or experiencing issues.",
                    "suggestions": [
                        "Try again later",
                        "Check your internet connection",
                        "The playlist might be very large - try a smaller playlist first"
                    ],
                    "technical_details": str(e)
                }
            )
        elif any(keyword in error_str for keyword in ['unavailable', 'private', 'deleted', 'not found']):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "Content Not Available",
                    "message": "The requested content could not be found or is not accessible.",
                    "suggestions": [
                        "Check if the URL is correct",
                        "The content might be private, deleted, or geo-restricted",
                        "Try accessing the URL in your browser to verify it exists"
                    ],
                    "technical_details": str(e)
                }
            )
        elif any(keyword in error_str for keyword in ['rate limit', '429', 'too many requests']):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate Limited",
                    "message": "Too many requests have been made. YouTube is temporarily blocking further requests.",
                    "suggestions": [
                        "Wait a few minutes before trying again",
                        "The system will automatically retry with longer delays",
                        "Consider using the YouTube Data API if you have a key"
                    ],
                    "technical_details": str(e)
                }
            )
        elif any(keyword in error_str for keyword in ['network', 'connection', 'resolve']):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "Network Issue",
                    "message": "Unable to connect to YouTube. This might be a temporary network issue.",
                    "suggestions": [
                        "Check your internet connection",
                        "Try again in a few minutes",
                        "YouTube might be experiencing technical difficulties"
                    ],
                    "technical_details": str(e)
                }
            )
        else:
            # Generic error fallback
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "Extraction Failed",
                    "message": "Failed to extract information from the provided URL.",
                    "suggestions": [
                        "Verify the URL is a valid YouTube channel or playlist",
                        "Try the URL in your browser to confirm it works",
                        "Contact support if the issue persists"
                    ],
                    "technical_details": str(e)
                }
            )
    
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
    if sub_data.get('content_types'):
        sub_data['content_types'] = Database.json_encode(sub_data['content_types'])
    if sub_data.get('extra_metadata'):
        sub_data['extra_metadata'] = Database.json_encode(sub_data['extra_metadata'])
    
    subscription_id = await db.insert("subscriptions", sub_data)
    
    # Add to scheduler if enabled
    if sub_data.get('enabled', True):
        await scheduler.add_subscription(subscription_id, sub_data.get('check_frequency', '0 * * * *'))
        
        # Queue initial video discovery for this subscription only if enabled
        try:
            logger.info(f"Queueing initial video discovery for subscription {subscription_id}")
            await downloader.queue_subscription_discovery(subscription_id, priority=2)
            logger.info(f"Successfully queued video discovery for subscription {subscription_id}")
        except Exception as e:
            # Log the error but don't fail the subscription creation
            logger.warning(f"Failed to queue initial video discovery for subscription {subscription_id}: {e}")
    
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
    if subscription.get('content_types'):
        subscription['content_types'] = Database.json_decode(subscription['content_types'])
    if subscription.get('extra_metadata'):
        subscription['extra_metadata'] = Database.json_decode(subscription['extra_metadata'])
    
    # Calculate next check time
    try:
        if subscription.get('enabled') and subscription.get('check_frequency'):
            trigger = CronTrigger.from_crontab(subscription['check_frequency'])
            subscription['next_check'] = trigger.get_next_fire_time(None, datetime.now())
        else:
            subscription['next_check'] = None
    except Exception:
        # Invalid cron expression
        subscription['next_check'] = None
    
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
        if 'content_types' in update_data:
            update_data['content_types'] = Database.json_encode(update_data['content_types'])
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
    Manual check for new content in subscription (queued for background processing)
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
    
    # Queue subscription discovery job with high priority (manual request)
    job_id = await downloader.queue_subscription_discovery(subscription_id, priority=3)
    
    return {
        "message": "Subscription check queued for processing",
        "subscription_id": subscription_id,
        "channel_name": subscription['channel_name'],
        "job_id": job_id,
        "queued_at": datetime.utcnow().isoformat()
    }


@router.get("/{subscription_id}/jobs")
async def get_subscription_jobs(
    subscription_id: int,
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth)
):
    """
    Get processing jobs for a subscription
    """
    # Get recent jobs for this subscription
    jobs = await db.execute(
        """SELECT * FROM job_queue 
           WHERE job_type = 'subscription_discovery' 
           AND subscription_id = ? 
           ORDER BY created_at DESC 
           LIMIT 10""",
        (subscription_id,)
    )
    
    job_list = []
    for job in jobs:
        job_data = dict(job)
        
        # Parse result data if available
        if job_data.get('result_data'):
            try:
                job_data['result_data'] = Database.json_decode(job_data['result_data'])
            except:
                pass
                
        job_list.append(job_data)
    
    return {"jobs": job_list}


@router.get("/jobs/{job_id}")
async def get_job_status(
    job_id: int,
    db: Database = Depends(get_db),
    downloader: Downloader = Depends(get_downloader),
    _: dict = Depends(get_auth)
):
    """
    Get status of a specific processing job
    """
    job = await db.execute_one(
        "SELECT * FROM job_queue WHERE id = ?",
        (job_id,)
    )
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    
    job_data = dict(job)
    
    # Add live progress if job is active
    active_jobs = downloader.get_active_downloads()
    if job_id in active_jobs:
        progress = active_jobs[job_id]
        job_data.update({
            'live_progress': progress.progress,
            'live_status': progress.status
        })
    
    # Parse result data if available
    if job_data.get('result_data'):
        try:
            job_data['result_data'] = Database.json_decode(job_data['result_data'])
        except:
            pass
            
    return job_data


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
    
    # Get subscription details and add to scheduler (if available)
    if scheduler:
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
    if scheduler is None:
        # Scheduler not initialized - return default state
        return {
            "scheduler_running": False,
            "scheduled_subscriptions": [],
            "total_jobs": 0
        }
    
    scheduled_jobs = scheduler.get_scheduled_subscriptions()
    
    return {
        "scheduler_running": scheduler._is_running,
        "scheduled_subscriptions": scheduled_jobs,
        "total_jobs": len(scheduled_jobs)
    }


@router.get("/ytdlp/status")
async def get_ytdlp_status(_: dict = Depends(get_auth)):
    """
    Get YT-DLP service status for monitoring
    """
    ytdlp_service = get_ytdlp_service()
    status = ytdlp_service.get_status()
    
    # Add human-readable status
    status['status_message'] = "Ready"
    if status['is_backing_off']:
        status['status_message'] = f"Backing off (retry in {status['next_available_in']:.1f}s)"
    elif status['failure_count'] > 0:
        status['status_message'] = f"Recently failed ({status['failure_count']} failures)"
    
    return status 