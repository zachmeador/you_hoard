"""
Scheduler event models and schemas
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, ConfigDict

EventType = Literal['check_started', 'check_completed', 'check_failed', 'check_cancelled']
EventStatus = Literal['success', 'partial_success', 'failed']


class SchedulerEventBase(BaseModel):
    """Base scheduler event schema"""
    subscription_id: int
    event_type: EventType
    status: EventStatus = "success"
    videos_found: int = 0
    videos_added: int = 0
    videos_queued: int = 0
    videos_filtered: int = 0
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    error_count: int = 0
    content_types_processed: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


class SchedulerEventCreate(SchedulerEventBase):
    """Schema for creating a scheduler event"""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class SchedulerEventUpdate(BaseModel):
    """Schema for updating a scheduler event"""
    status: Optional[EventStatus] = None
    videos_found: Optional[int] = None
    videos_added: Optional[int] = None
    videos_queued: Optional[int] = None
    videos_filtered: Optional[int] = None
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    error_count: Optional[int] = None
    content_types_processed: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    completed_at: Optional[datetime] = None


class SchedulerEventInDB(SchedulerEventBase):
    """Scheduler event schema as stored in database"""
    id: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class SchedulerEventResponse(SchedulerEventInDB):
    """Scheduler event response schema"""
    channel_name: Optional[str] = None
    subscription_source_url: Optional[str] = None


class SchedulerEventListResponse(BaseModel):
    """Response for scheduler events list endpoint"""
    events: List[SchedulerEventResponse]
    total: int
    page: int = 1
    per_page: int = 50


class SubscriptionCheckSummary(BaseModel):
    """Summary of recent checks for a subscription"""
    subscription_id: int
    total_checks: int
    successful_checks: int
    failed_checks: int
    last_check_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    total_videos_added: int
    total_videos_queued: int
    average_duration_ms: Optional[float] = None
    recent_errors: List[str] = [] 