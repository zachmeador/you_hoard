"""
Subscription models and schemas
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator, ConfigDict

# Import video types from video model
VideoType = Literal['video', 'short', 'live']

class SubscriptionBase(BaseModel):
    """Base subscription schema"""
    channel_id: int
    subscription_type: str = Field(..., pattern="^(channel|playlist)$")
    source_url: str
    enabled: bool = True
    auto_download: bool = True
    quality_preference: str = "1080p"
    download_comments: bool = False
    subtitle_languages: Optional[List[str]] = None
    audio_tracks: Optional[List[str]] = None
    check_frequency: str = "0 * * * *"  # Cron expression
    latest_n_videos: int = Field(default=20, ge=1, le=200)  # Max videos to check
    content_types: List[VideoType] = Field(default=["video"], description="Video types to include in subscription")
    
    @field_validator('check_frequency')
    @classmethod
    def validate_cron(cls, v):
        # Basic cron validation (could be more sophisticated)
        parts = v.split()
        if len(parts) != 5:
            raise ValueError('Invalid cron expression')
        return v
    
    @field_validator('content_types')
    @classmethod
    def validate_content_types(cls, v):
        if not v:
            raise ValueError('At least one content type must be specified')
        valid_types = {'video', 'short', 'live'}
        invalid_types = set(v) - valid_types
        if invalid_types:
            raise ValueError(f'Invalid content types: {invalid_types}')
        return v


class SubscriptionCreate(BaseModel):
    """Schema for creating a subscription"""
    subscription_type: str = Field(..., pattern="^(channel|playlist)$")
    source_url: str
    enabled: bool = True
    auto_download: bool = True
    quality_preference: str = "1080p"
    download_comments: bool = False
    subtitle_languages: Optional[List[str]] = None
    audio_tracks: Optional[List[str]] = None
    check_frequency: str = "0 * * * *"  # Cron expression
    latest_n_videos: int = Field(default=20, ge=1, le=200)  # Max videos to check
    content_types: List[VideoType] = Field(default=["video"], description="Video types to include in subscription")
    extra_metadata: Optional[Dict[str, Any]] = None
    
    @field_validator('check_frequency')
    @classmethod
    def validate_cron(cls, v):
        # Basic cron validation (could be more sophisticated)
        parts = v.split()
        if len(parts) != 5:
            raise ValueError('Invalid cron expression')
        return v
    
    @field_validator('content_types')
    @classmethod
    def validate_content_types(cls, v):
        if not v:
            raise ValueError('At least one content type must be specified')
        valid_types = {'video', 'short', 'live'}
        invalid_types = set(v) - valid_types
        if invalid_types:
            raise ValueError(f'Invalid content types: {invalid_types}')
        return v


class SubscriptionUpdate(BaseModel):
    """Schema for updating a subscription"""
    enabled: Optional[bool] = None
    auto_download: Optional[bool] = None
    quality_preference: Optional[str] = None
    download_comments: Optional[bool] = None
    subtitle_languages: Optional[List[str]] = None
    audio_tracks: Optional[List[str]] = None
    check_frequency: Optional[str] = None
    latest_n_videos: Optional[int] = Field(default=None, ge=1, le=200)
    content_types: Optional[List[VideoType]] = None
    extra_metadata: Optional[Dict[str, Any]] = None
    
    @field_validator('content_types')
    @classmethod
    def validate_content_types(cls, v):
        if v is not None:
            if not v:
                raise ValueError('At least one content type must be specified')
            valid_types = {'video', 'short', 'live'}
            invalid_types = set(v) - valid_types
            if invalid_types:
                raise ValueError(f'Invalid content types: {invalid_types}')
        return v


class SubscriptionInDB(SubscriptionBase):
    """Subscription schema as stored in database"""
    id: int
    last_check: Optional[datetime] = None
    new_videos_count: int = 0
    extra_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class SubscriptionResponse(SubscriptionInDB):
    """Subscription response schema"""
    channel_name: str
    channel_youtube_id: str
    next_check: Optional[datetime] = None


class SubscriptionListResponse(BaseModel):
    """Response for subscription list endpoint"""
    subscriptions: List[SubscriptionResponse]
    total: int
    page: int = 1
    per_page: int = 50


class SubscriptionCheckResult(BaseModel):
    """Result of subscription check"""
    subscription_id: int
    channel_name: str
    new_videos: List[Dict[str, Any]]
    errors: List[str] = []
    checked_at: datetime 