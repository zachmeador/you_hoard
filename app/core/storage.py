"""Stable archive paths and confined access to stored media."""

import re
from pathlib import Path

from app.core.config import settings

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}


def safe_name(value: str) -> str:
    return re.sub(r"[^\w-]+", "_", value, flags=re.UNICODE).strip("_")[:100] or "untitled"


def stored_path(relative_path: str) -> Path:
    root = settings.get_storage_path().resolve()
    path = (root / relative_path).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("Path is outside the archive")
    return path


def video_directory(channel_id: str, channel_name: str, youtube_id: str, title: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", channel_id) or not re.fullmatch(
        r"[A-Za-z0-9_-]{11}", youtube_id
    ):
        raise ValueError("Invalid source identifier")
    stored_path("channels")
    channels = settings.get_storage_path() / "channels"
    channels.mkdir(parents=True, exist_ok=True)
    # Reuse directories when an uploader or video changes its title.
    channel = next((p for p in channels.glob(f"{channel_id}_*") if p.is_dir()), None)
    channel = channel or channels / f"{channel_id}_{safe_name(channel_name)}"
    stored_path(str(channel.relative_to(settings.get_storage_path())))
    channel.mkdir(exist_ok=True)
    directory = next((p for p in channel.glob(f"{youtube_id}_*") if p.is_dir()), None)
    directory = directory or channel / f"{youtube_id}_{safe_name(title)}"
    stored_path(str(directory.relative_to(settings.get_storage_path())))
    directory.mkdir(exist_ok=True)
    return directory


def media_file(relative_path: str) -> Path:
    path = stored_path(relative_path)
    # Early versions stored a directory instead of the media filename.
    if path.is_dir():
        path = next(
            (p for p in sorted(path.iterdir()) if p.suffix.lower() in VIDEO_EXTENSIONS), path
        )
    if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise FileNotFoundError("Local video file not found")
    stored_path(str(path.relative_to(settings.get_storage_path().resolve())))
    return path


def removable_directory(relative_path: str, youtube_id: str) -> Path:
    path = stored_path(relative_path)
    directory = path if path.is_dir() else path.parent
    channels = (settings.get_storage_path() / "channels").resolve()
    # Never recursively remove a channel, a storage root, or an unrelated directory.
    if (
        not directory.is_relative_to(channels)
        or len(directory.relative_to(channels).parts) != 2
        or not directory.name.startswith(f"{youtube_id}_")
    ):
        raise ValueError("Video is not in a managed video directory; remove its files manually")
    return directory
