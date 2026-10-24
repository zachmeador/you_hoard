"""Subscription inputs and stored responses."""

from datetime import datetime
from typing import Any, Literal, Optional

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.youtube import subscription_url
from app.models.video import Quality, VideoType


def valid_cron(value):
    if value is not None:
        CronTrigger.from_crontab(value)
    return value


def valid_types(value):
    if value is not None and not value:
        raise ValueError("Select at least one content type")
    return value


class SubscriptionCreate(BaseModel):
    subscription_type: Literal["channel", "playlist"]
    source_url: str
    enabled: bool = True
    auto_download: bool = False
    quality_preference: Quality = "1080p"
    download_comments: bool = False
    subtitle_languages: Optional[list[str]] = None
    audio_tracks: Optional[list[str]] = None
    check_frequency: str = "0 * * * *"
    latest_n_videos: int = Field(20, ge=1, le=200)
    content_types: list[VideoType] = Field(default_factory=lambda: ["video"])
    extra_metadata: Optional[dict[str, Any]] = None

    _cron = field_validator("check_frequency")(valid_cron)
    _types = field_validator("content_types")(valid_types)

    @model_validator(mode="after")
    def canonical_source(self):
        self.source_url = subscription_url(self.source_url, self.subscription_type)
        return self


class SubscriptionUpdate(BaseModel):
    enabled: Optional[bool] = None
    auto_download: Optional[bool] = None
    quality_preference: Optional[Quality] = None
    download_comments: Optional[bool] = None
    subtitle_languages: Optional[list[str]] = None
    audio_tracks: Optional[list[str]] = None
    check_frequency: Optional[str] = None
    latest_n_videos: Optional[int] = Field(None, ge=1, le=200)
    content_types: Optional[list[VideoType]] = None
    extra_metadata: Optional[dict[str, Any]] = None

    _cron = field_validator("check_frequency")(valid_cron)
    _types = field_validator("content_types")(valid_types)

    @model_validator(mode="after")
    def non_nullable_preferences(self):
        for key in self.model_fields_set - {"subtitle_languages", "audio_tracks", "extra_metadata"}:
            if getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        return self


class SubscriptionResponse(BaseModel):
    id: int
    channel_id: int
    subscription_type: str
    source_url: str
    enabled: bool
    auto_download: bool
    quality_preference: str
    download_comments: bool
    subtitle_languages: Optional[list[str]] = None
    audio_tracks: Optional[list[str]] = None
    check_frequency: str
    latest_n_videos: int
    content_types: list[VideoType]
    extra_metadata: Optional[dict[str, Any]] = None
    last_check: Optional[datetime] = None
    new_videos_count: int = 0
    created_at: datetime
    channel_name: str
    channel_youtube_id: str
    next_check: Optional[datetime] = None
    last_job: Optional[dict] = None


class SubscriptionListResponse(BaseModel):
    subscriptions: list[SubscriptionResponse]
    total: int
    page: int
    per_page: int
