"""
Video models and schemas
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict

# Video type enumeration
VideoType = Literal['video', 'short', 'live']

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
    video_type: VideoType = 'video'
    thumbnail_path: Optional[str] = None
    thumbnail_generated: bool = False
    thumbnail_timestamp: Optional[float] = None
    
    @field_validator('youtube_id')
    @classmethod
    def validate_youtube_id(cls, v):
        if not v or len(v) != 11:
            raise ValueError('Invalid YouTube video ID')
        return v


class VideoCreate(BaseModel):
    """Schema for creating a video"""
    # Either provide URL OR provide youtube_id + channel_id + title
    url: Optional[str] = None
    youtube_id: Optional[str] = None
    channel_id: Optional[int] = None
    title: Optional[str] = None
    
    # Optional fields
    description: Optional[str] = None
    duration: Optional[int] = None
    upload_date: Optional[datetime] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    quality: Optional[str] = None
    video_type: VideoType = 'video'
    thumbnail_path: Optional[str] = None
    thumbnail_generated: bool = False
    thumbnail_timestamp: Optional[float] = None
    
    @model_validator(mode='before')
    @classmethod
    def validate_input(cls, data):
        if isinstance(data, dict):
            url = data.get('url')
            youtube_id = data.get('youtube_id')
            if not url and not youtube_id:
                raise ValueError('Either url or youtube_id must be provided')
            if url and youtube_id:
                raise ValueError('Provide either url or youtube_id, not both')
        return data


class VideoUpdate(BaseModel):
    """Schema for updating a video"""
    title: Optional[str] = None
    description: Optional[str] = None
    quality: Optional[str] = None
    video_type: Optional[VideoType] = None
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
    
    model_config = ConfigDict(from_attributes=True)


class VideoResponse(VideoInDB):
    """Video response schema"""
    channel_name: Optional[str] = None
    tags: List[Dict[str, Any]] = []
    thumbnail_url: Optional[str] = None
    
    @model_validator(mode='after')
    def set_thumbnail_url(self):
        """Set thumbnail_url from thumbnail_path"""
        if self.thumbnail_path:
            self.thumbnail_url = f"/storage/{self.thumbnail_path}"
        return self


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