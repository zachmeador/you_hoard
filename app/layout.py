"""Library paths: readable names keyed by YouTube IDs, always resolved inside MEDIA_DIR.

    <Channel name> [<channel id>]/<YYYY-MM-DD> <Title> [<video id>].<ext>

Sidecars (.info.json, .jpg, .<lang>.vtt) share the media file's basename, so a video's
media path is the only path the database stores. TubeArchivist's in-place layout
(<channel id>/<video id>.mp4 with <video id>.<lang>.vtt) follows the same rule.
"""

import glob
import os
import re
import shutil
from pathlib import Path

from yt_dlp.utils import sanitize_filename

from app.config import config

VIDEO_EXTENSIONS = (".mp4", ".mkv", ".webm", ".m4v", ".mov")
THUMBNAIL_EXTENSIONS = (".jpg", ".jpeg", ".webp", ".png")
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
CHANNEL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
SUBTITLE_LANGUAGE = re.compile(r"[A-Za-z0-9_-]{1,32}")
BRACKETED_ID = re.compile(r"\[([A-Za-z0-9_-]{11})\]$")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
APP_DIR = ".youhoard"


class PathError(ValueError):
    pass


def resolve(relative: str | Path) -> Path:
    root = config.media_root
    path = (root / relative).resolve()
    if path == root or not path.is_relative_to(root):
        raise PathError("Path is outside the media folder")
    return path


def relative(path: Path) -> str:
    return path.resolve().relative_to(config.media_root).as_posix()


def clean(text: str | None, max_bytes: int) -> str:
    name = sanitize_filename(text or "", restricted=False).strip().strip(".")
    name = name.encode()[:max_bytes].decode(errors="ignore").strip()
    return name or "untitled"


def video_id_from_media(path: Path) -> str | None:
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return None
    if match := BRACKETED_ID.search(path.stem):
        return match.group(1)
    return path.stem if VIDEO_ID.fullmatch(path.stem) else None


def incomplete_dir(youtube_id: str) -> Path:
    if not VIDEO_ID.fullmatch(youtube_id):
        raise PathError("Invalid video ID")
    return config.media_root / APP_DIR / "incomplete" / youtube_id


def channel_dir(channel_youtube_id: str, channel_name: str | None) -> Path:
    if not CHANNEL_ID.fullmatch(channel_youtube_id):
        raise PathError("Invalid channel ID")
    root = config.media_root
    suffix = f"[{channel_youtube_id}]"
    if root.is_dir():
        for path in root.iterdir():
            if path.is_dir() and path.name.endswith(suffix):
                return path
    return root / f"{clean(channel_name, 120)} {suffix}"


def video_basename(youtube_id: str, title: str | None, published_at: str | None) -> str:
    date = (published_at or "")[:10]
    parts = [date if DATE.fullmatch(date) else "", clean(title, 150), f"[{youtube_id}]"]
    return " ".join(part for part in parts if part)


def existing_media(directory: Path, youtube_id: str) -> Path | None:
    if not directory.is_dir():
        return None
    pattern = "*" + glob.escape(f"[{youtube_id}]") + ".*"
    for path in sorted(directory.glob(pattern)):
        if path.is_file() and video_id_from_media(path) == youtube_id:
            return path
    return None


def sidecars(media: Path) -> list[Path]:
    prefix = media.stem + "."
    return sorted(
        path
        for path in media.parent.glob(glob.escape(prefix) + "*")
        if path != media and path.is_file()
    )


def thumbnail_for(media: Path) -> Path | None:
    for extension in THUMBNAIL_EXTENSIONS:
        path = media.with_name(media.stem + extension)
        if path.is_file():
            return path
    return None


def info_for(media: Path) -> Path | None:
    path = media.with_name(media.stem + ".info.json")
    return path if path.is_file() else None


def subtitles_for(media: Path) -> dict[str, Path]:
    prefix = media.stem + "."
    found = {}
    for path in sorted(media.parent.glob(glob.escape(prefix) + "*.vtt")):
        language = path.name[len(prefix) : -len(".vtt")]
        if SUBTITLE_LANGUAGE.fullmatch(language):
            found[language] = path
    return found


def media_file(media_path: str, youtube_id: str) -> Path:
    """The archived file for a video, refusing anything that is not that video's media."""
    path = resolve(media_path)
    if video_id_from_media(path) != youtube_id:
        raise PathError("Stored path does not belong to this video")
    return path


def place_download(workdir: Path, directory: Path, basename: str) -> Path:
    """Move a finished download (media.<ext> plus sidecars) from its work directory into place."""
    directory.mkdir(parents=True, exist_ok=True)
    media = None
    for path in sorted(workdir.iterdir()):
        if not path.is_file() or not path.name.startswith("media."):
            continue
        rest = path.name.removeprefix("media.")
        if rest.endswith((".part", ".ytdl", ".temp")):
            continue
        target = directory / f"{basename}.{rest}"
        os.replace(path, target)
        if "." not in rest and target.suffix.lower() in VIDEO_EXTENSIONS:
            media = target
    if media is None:
        raise RuntimeError("yt-dlp finished without producing a video file")
    shutil.rmtree(workdir, ignore_errors=True)
    return media


def move_media(media: Path, directory: Path, basename: str) -> Path:
    """Rename a media file and its sidecars to a new basename (same filesystem)."""
    directory.mkdir(parents=True, exist_ok=True)
    for sidecar in sidecars(media):
        rest = sidecar.name[len(media.stem) + 1 :]
        os.replace(sidecar, directory / f"{basename}.{rest}")
    target = directory / f"{basename}{media.suffix}"
    os.replace(media, target)
    _remove_if_empty(media.parent)
    return target


def remove_media(media_path: str, youtube_id: str) -> None:
    """Delete a video's media file and sidecars; never anything else."""
    media = media_file(media_path, youtube_id)
    for path in sidecars(media):
        path.unlink(missing_ok=True)
    media.unlink(missing_ok=True)
    _remove_if_empty(media.parent)


def _remove_if_empty(directory: Path) -> None:
    if directory != config.media_root and directory.is_relative_to(config.media_root):
        try:
            directory.rmdir()
        except OSError:
            pass
