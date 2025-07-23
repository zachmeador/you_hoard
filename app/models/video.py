"""
Video models and schemas
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator


class VideoBase(BaseModel):
    """Base video schema"""
    youtube_id: str
    channel_id: int
    title: str
    description: Optional[str] = None
    duration: Optional[int] = None  # seconds
    upload_date: Optional[datetime] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    quality: Optional[str] = None
    
    @validator('youtube_id')
    def validate_youtube_id(cls, v):
        if not v or len(v) != 11:
            raise ValueError('Invalid YouTube video ID')
        return v


class VideoCreate(VideoBase):
    """Schema for creating a video"""
    url: Optional[str] = None  # Alternative to youtube_id
    
    @validator('url')
    def extract_video_id(cls, v, values):
        if v and 'youtube_id' not in values:
            # Extract video ID from URL
            import re
            patterns = [
                r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})',
                r'youtube\.com\/embed\/([a-zA-Z0-9_-]{11})',
            ]
            for pattern in patterns:
                match = re.search(pattern, v)
                if match:
                    return match.group(1)
            raise ValueError('Invalid YouTube URL')
        return v


class VideoUpdate(BaseModel):
    """Schema for updating a video"""
    title: Optional[str] = None
    description: Optional[str] = None
    quality: Optional[str] = None
    extra_metadata: Optional[Dict[str, Any]] = None


class VideoInDB(VideoBase):
    """Video schema as stored in database"""
    id: int
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    download_status: str = "pending"
    extra_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class VideoResponse(VideoInDB):
    """Video response schema"""
    channel_name: Optional[str] = None
    tags: List[Dict[str, Any]] = []


class VideoListResponse(BaseModel):
    """Response for video list endpoint"""
    videos: List[VideoResponse]
    total: int
    page: int = 1
    per_page: int = 50


class VideoDownloadRequest(BaseModel):
    """Request to download a video"""
    priority: int = Field(0, ge=0, le=10)
    quality_override: Optional[str] = None


class VideoWithChannel(VideoInDB):
    """Video with channel information"""
    channel_youtube_id: str
    channel_name: str


class VideoBulkOperation(BaseModel):
    """Bulk operation on videos"""
    video_ids: List[int]
    operation: str = Field(..., pattern="^(delete|tag|download|update_status)$")
    params: Optional[Dict[str, Any]] = None 