"""
Channel models and schemas
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ChannelBase(BaseModel):
    """Base channel schema"""
    youtube_id: str
    name: str
    description: Optional[str] = None
    subscriber_count: Optional[int] = None
    thumbnail_url: Optional[str] = None


class ChannelCreate(ChannelBase):
    """Schema for creating a channel"""
    extra_metadata: Optional[Dict[str, Any]] = None


class ChannelUpdate(BaseModel):
    """Schema for updating a channel"""
    name: Optional[str] = None
    description: Optional[str] = None
    subscriber_count: Optional[int] = None
    thumbnail_url: Optional[str] = None
    extra_metadata: Optional[Dict[str, Any]] = None


class ChannelInDB(ChannelBase):
    """Channel schema as stored in database"""
    id: int
    extra_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ChannelResponse(ChannelInDB):
    """Channel response schema"""
    video_count: int = 0
    tags: List[Dict[str, Any]] = []
    subscription_status: Optional[str] = None


class ChannelListResponse(BaseModel):
    """Response for channel list endpoint"""
    channels: List[ChannelResponse]
    total: int
    page: int = 1
    per_page: int = 50


class ChannelWithStats(ChannelInDB):
    """Channel with statistics"""
    total_videos: int = 0
    downloaded_videos: int = 0
    total_size: int = 0  # bytes
    last_video_date: Optional[datetime] = None 