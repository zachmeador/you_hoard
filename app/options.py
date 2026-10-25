"""Download options resolve per video, then per subscription, then library settings."""

from typing import Any

from app.db import loads

# Each option with the library setting that backs it.
OPTIONS = {
    "quality": "default_quality",
    "subtitle_languages": "subtitle_languages",
    "auto_captions": "auto_captions",
    "download_comments": "download_comments",
    "audio_languages": "audio_languages",
    "live_chat": "live_chat",
    "sponsorblock": "sponsorblock",
}
LIST_OPTIONS = ("subtitle_languages", "audio_languages")
FLAG_OPTIONS = ("auto_captions", "download_comments", "live_chat", "sponsorblock")


def subscription_options(subscription: dict[str, Any] | None) -> dict[str, Any]:
    """What a subscription overrides; columns left NULL fall through to the library settings."""
    chosen: dict[str, Any] = {}
    for key in OPTIONS:
        value = subscription[key] if subscription else None
        if value is None:
            continue
        if key in LIST_OPTIONS:
            chosen[key] = loads(value)
        elif key in FLAG_OPTIONS:
            chosen[key] = bool(value)
        else:
            chosen[key] = value
    return chosen


def resolve_options(
    video: dict[str, Any], subscription: dict[str, Any] | None, library: dict[str, Any]
) -> dict[str, Any]:
    """Every download option: the video's own, else the subscription's, else the library's."""
    from_subscription = subscription_options(subscription)
    resolved = {}
    for key, setting in OPTIONS.items():
        value = video.get(key)
        if value is None:
            value = from_subscription.get(key)
        resolved[key] = library[setting] if value is None else value
    return resolved
