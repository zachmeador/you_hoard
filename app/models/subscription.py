"""
Subscription models and schemas
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator


class SubscriptionBase(BaseModel):
    """Base subscription schema"""
    channel_id: int
    subscription_type: str = Field(..., pattern="^(channel|playlist)$")
    source_url: str
    enabled: bool = True
    quality_preference: str = "1080p"
    download_comments: bool = False
    subtitle_languages: Optional[List[str]] = None
    audio_tracks: Optional[List[str]] = None
    check_frequency: str = "0 * * * *"  # Cron expression
    
    @validator('check_frequency')
    def validate_cron(cls, v):
        # Basic cron validation (could be more sophisticated)
        parts = v.split()
        if len(parts) != 5:
            raise ValueError('Invalid cron expression')
        return v


class SubscriptionCreate(SubscriptionBase):
    """Schema for creating a subscription"""
    extra_metadata: Optional[Dict[str, Any]] = None


class SubscriptionUpdate(BaseModel):
    """Schema for updating a subscription"""
    enabled: Optional[bool] = None
    quality_preference: Optional[str] = None
    download_comments: Optional[bool] = None
    subtitle_languages: Optional[List[str]] = None
    audio_tracks: Optional[List[str]] = None
    check_frequency: Optional[str] = None
    extra_metadata: Optional[Dict[str, Any]] = None


class SubscriptionInDB(SubscriptionBase):
    """Subscription schema as stored in database"""
    id: int
    last_check: Optional[datetime] = None
    extra_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class SubscriptionResponse(SubscriptionInDB):
    """Subscription response schema"""
    channel_name: str
    channel_youtube_id: str
    next_check: Optional[datetime] = None
    new_videos_count: int = 0


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