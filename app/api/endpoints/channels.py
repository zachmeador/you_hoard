"""
Channel management endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from typing import Optional
from datetime import datetime

from app.core.database import Database
from app.core.security import SessionBearer, SecurityManager
from app.models.channel import (
    ChannelUpdate, ChannelResponse,
    ChannelListResponse, ChannelWithStats
)


router = APIRouter()


def get_db(request: Request) -> Database:
    """Get database from app state"""
    return request.app.state.db


def get_auth(request: Request) -> SessionBearer:
    """Get auth dependency"""
    security_manager = SecurityManager(request.app.state.db)
    return SessionBearer(security_manager)


@router.get("", response_model=ChannelListResponse)
async def list_channels(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth)
):
    """
    List channels with pagination
    """
    offset = (page - 1) * per_page
    
    # Build query
    where_clause = "1=1"
    params = []
    
    if search:
        where_clause += " AND c.name LIKE ?"
        params.append(f"%{search}%")
    
    # Get total count
    count_query = f"SELECT COUNT(*) as total FROM channels c WHERE {where_clause}"
    total_result = await db.execute_one(count_query, tuple(params))
    total = total_result['total'] if total_result else 0
    
    # Get channels with video count
    query = f"""
        SELECT c.*, 
               COUNT(v.id) as video_count,
               COUNT(CASE WHEN v.download_status = 'completed' THEN 1 END) as downloaded_count
        FROM channels c
        LEFT JOIN videos v ON c.id = v.channel_id
        WHERE {where_clause}
        GROUP BY c.id
        ORDER BY c.name
        LIMIT ? OFFSET ?
    """
    params.extend([per_page, offset])
    channels = await db.execute(query, tuple(params))
    
    # Get subscription status for channels
    channel_ids = [c['id'] for c in channels]
    if channel_ids:
        sub_query = """
            SELECT channel_id, enabled
            FROM subscriptions
            WHERE channel_id IN ({})
        """.format(','.join('?' * len(channel_ids)))
        subs = await db.execute(sub_query, tuple(channel_ids))
        
        sub_status = {s['channel_id']: 'active' if s['enabled'] else 'paused' for s in subs}
        
        for channel in channels:
            channel['subscription_status'] = sub_status.get(channel['id'])
    
    # Get tags for channels
    if channel_ids:
        tags_query = """
            SELECT ct.channel_id, t.id, t.name, t.color
            FROM channel_tags ct
            JOIN tags t ON ct.tag_id = t.id
            WHERE ct.channel_id IN ({})
        """.format(','.join('?' * len(channel_ids)))
        tags_result = await db.execute(tags_query, tuple(channel_ids))
        
        # Group tags by channel
        channel_tags = {}
        for tag in tags_result:
            if tag['channel_id'] not in channel_tags:
                channel_tags[tag['channel_id']] = []
            channel_tags[tag['channel_id']].append({
                'id': tag['id'],
                'name': tag['name'],
                'color': tag['color']
            })
        
        # Add tags to channels
        for channel in channels:
            channel['tags'] = channel_tags.get(channel['id'], [])
    
    return ChannelListResponse(
        channels=[ChannelResponse(**c) for c in channels],
        total=total,
        page=page,
        per_page=per_page
    )


@router.get("/{channel_id}", response_model=ChannelWithStats)
async def get_channel(
    channel_id: int,
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth)
):
    """
    Get channel details with statistics
    """
    channel = await db.execute_one(
        """SELECT c.*,
                  COUNT(v.id) as total_videos,
                  COUNT(CASE WHEN v.download_status = 'completed' THEN 1 END) as downloaded_videos,
                  SUM(CASE WHEN v.file_size IS NOT NULL THEN v.file_size ELSE 0 END) as total_size,
                  MAX(v.upload_date) as last_video_date
           FROM channels c
           LEFT JOIN videos v ON c.id = v.channel_id
           WHERE c.id = ?
           GROUP BY c.id""",
        (channel_id,)
    )
    
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )
    
    return ChannelWithStats(**channel)


@router.get("/{channel_id}/videos")
async def get_channel_videos(
    channel_id: int,
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    status: Optional[str] = None,
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth)
):
    """
    Get videos for a specific channel
    """
    # Check if channel exists
    channel = await db.execute_one(
        "SELECT id FROM channels WHERE id = ?",
        (channel_id,)
    )
    
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )
    
    # Use videos endpoint logic but filter by channel
    from app.api.endpoints.videos import list_videos
    return await list_videos(request, page, per_page, channel_id, status, None, db, _)


@router.put("/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: int,
    channel_update: ChannelUpdate,
    db: Database = Depends(get_db),
    _: dict = Depends(get_auth)
):
    """
    Update channel metadata
    """
    # Check if channel exists
    existing = await db.execute_one(
        "SELECT id FROM channels WHERE id = ?",
        (channel_id,)
    )
    
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found"
        )
    
    # Update channel
    update_data = channel_update.dict(exclude_unset=True)
    if update_data:
        update_data['updated_at'] = datetime.utcnow().isoformat()
        
        if 'extra_metadata' in update_data:
            update_data['extra_metadata'] = Database.json_encode(update_data['extra_metadata'])
        
        await db.update("channels", update_data, "id = ?", (channel_id,))
    
    # Return updated channel
    return await get_channel(channel_id, db, _) 