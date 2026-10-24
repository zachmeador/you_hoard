"""The YouTube boundary: URL validation and a yt-dlp adapter that never blocks the event loop.

Tests replace `YouTube` with a fake that has the same async methods.
"""

import asyncio
import functools
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yt_dlp
from yt_dlp.globals import supported_js_runtimes
from yt_dlp.utils import DownloadCancelled

from app.config import config
from app.layout import VIDEO_ID

logger = logging.getLogger(__name__)

HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
PLAYLIST_ID = re.compile(r"[A-Za-z0-9_-]{2,64}")
TABS = {"video": "videos", "short": "shorts", "live": "streams"}
NOT_READY = {"is_upcoming", "is_live", "post_live"}
QUALITIES = ["best", "2160p", "1440p", "1080p", "720p", "480p", "360p"]

# Ordered checks against yt-dlp's error text; first match wins.
WAITING = ("will begin", "premieres in", "premiere will begin")
BLOCKED = (
    "sign in to confirm you",
    "try again later",
    "http error 429",
    "too many requests",
    "rate-limit",
)
INACCESSIBLE = (
    "in your country",
    "members-only",
    "join this channel",
    "confirm your age",
    "age-restricted",
    "inappropriate for some users",
    "requires payment",
)
GONE = (
    "private video",
    "has been removed",
    "been terminated",
    "no longer available",
    "removed for violating",
    "copyright",
    "does not exist",
    "video unavailable",
)


class YtDlpLogger:
    """Route yt-dlp's messages to logging; a missing channel tab is expected, not an error."""

    def debug(self, message: str) -> None:
        logger.debug(message)

    def info(self, message: str) -> None:
        logger.info(message)

    def warning(self, message: str) -> None:
        logger.warning(message)

    def error(self, message: str) -> None:
        if "does not have a" in message:
            logger.info(message)
        else:
            logger.error(message)


class YouTubeError(Exception):
    """A temporary failure worth retrying later."""


class Blocked(YouTubeError):
    """YouTube is throttling or asking for a bot check."""


class Inaccessible(YouTubeError):
    """Needs a login, membership or a different region; retrying will not help."""


class Unavailable(YouTubeError):
    """The video or source is gone: private, removed or terminated."""


class NotReady(YouTubeError):
    """An upcoming premiere or a stream that has not finished."""

    def __init__(self, message: str, retry_at: float | None = None) -> None:
        super().__init__(message)
        self.retry_at = retry_at


class Cancelled(YouTubeError):
    pass


def classify(error: Exception) -> YouTubeError:
    if isinstance(error, YouTubeError):
        return error
    text = str(error).removeprefix("ERROR: ")
    lowered = text.lower()
    checks = (
        (WAITING, NotReady),
        (BLOCKED, Blocked),
        (INACCESSIBLE, Inaccessible),
        (GONE, Unavailable),
    )
    for words, kind in checks:
        if any(word in lowered for word in words):
            return kind(text)
    return YouTubeError(text)


def youtube_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value if "://" in value else f"https://{value}")
    if (
        parsed.scheme not in ("http", "https")
        or parsed.hostname not in HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 80, 443)
    ):
        raise ValueError("Use a youtube.com or youtu.be URL")
    return parsed.geturl()


def parse_video_url(value: str) -> str:
    value = value.strip()
    if VIDEO_ID.fullmatch(value):
        return value
    parsed = urlparse(youtube_url(value))
    if parsed.hostname == "youtu.be":
        video_id = parsed.path.strip("/")
    elif parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    elif parsed.path.startswith(("/shorts/", "/live/", "/embed/", "/v/")):
        video_id = parsed.path.split("/")[2]
    else:
        video_id = ""
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("Use a video URL, not a channel or playlist URL")
    return video_id


def parse_source_url(value: str) -> tuple[str, str]:
    """Return ("channel" | "playlist", URL to resolve)."""
    parsed = urlparse(youtube_url(value))
    query = parse_qs(parsed.query)
    playlist_id = query.get("list", [""])[0]
    if playlist_id and (parsed.path == "/playlist" or not query.get("v")):
        if not PLAYLIST_ID.fullmatch(playlist_id):
            raise ValueError("Invalid playlist ID")
        return "playlist", f"https://www.youtube.com/playlist?list={playlist_id}"
    path = parsed.path.rstrip("/")
    for tab in ("/videos", "/shorts", "/streams", "/featured", "/playlists", "/live"):
        path = path.removesuffix(tab)
    parts = path.split("/")
    if parsed.hostname != "youtu.be" and (
        (len(parts) == 2 and parts[1].startswith("@") and len(parts[1]) > 1)
        or (len(parts) == 3 and parts[1] in ("channel", "c", "user") and parts[2])
    ):
        return "channel", f"https://www.youtube.com{path}"
    raise ValueError("Use a channel URL (youtube.com/@name) or a playlist URL (…?list=…)")


def channel_url(channel_youtube_id: str) -> str:
    return f"https://www.youtube.com/channel/{channel_youtube_id}"


def video_url(youtube_id: str) -> str:
    return f"https://www.youtube.com/watch?v={youtube_id}"


def source_url(kind: str, youtube_id: str) -> str:
    if kind == "playlist":
        return f"https://www.youtube.com/playlist?list={youtube_id}"
    return channel_url(youtube_id)


def quality_height(quality: str | None) -> int | None:
    if not quality or quality == "best":
        return None
    if quality not in QUALITIES:
        raise ValueError(f"Unsupported quality: {quality}")
    return int(quality.removesuffix("p"))


@dataclass
class Source:
    kind: str
    youtube_id: str
    title: str
    channel_youtube_id: str | None = None
    channel_name: str | None = None
    channel_handle: str | None = None
    owner_name: str | None = None
    description: str | None = None
    subscriber_count: int | None = None

    @property
    def url(self) -> str:
        return source_url(self.kind, self.youtube_id)


@dataclass
class Entry:
    youtube_id: str
    video_type: str
    title: str | None = None
    duration: int | None = None
    live_status: str | None = None
    channel_youtube_id: str | None = None
    channel_name: str | None = None


@dataclass
class DownloadRequest:
    youtube_id: str
    workdir: Path
    quality: str | None
    subtitle_languages: list[str]
    comments: bool


ProgressCallback = Callable[[dict[str, Any]], None]


class YouTube:
    def __init__(self, request_interval: float | None = None) -> None:
        self.request_interval = (
            config.YTDLP_REQUEST_INTERVAL if request_interval is None else request_interval
        )
        self._lock = asyncio.Lock()
        self._last_start = 0.0

    def options(self, **extra: Any) -> dict[str, Any]:
        runtime = {"path": config.YTDLP_JS_RUNTIME_PATH} if config.YTDLP_JS_RUNTIME_PATH else {}
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": YtDlpLogger(),
            "socket_timeout": 30,
            "retries": 5,
            "fragment_retries": 10,
            "extractor_retries": 3,
            "noplaylist": True,
            "js_runtimes": {config.YTDLP_JS_RUNTIME: runtime},
        }
        if config.YTDLP_COOKIE_FILE:
            options["cookiefile"] = str(config.YTDLP_COOKIE_FILE)
        options.update(extra)
        return options

    async def _run(self, work: Callable[[], Any], retries: int = 2) -> Any:
        for attempt in range(retries + 1):
            async with self._lock:
                delay = self.request_interval - (time.monotonic() - self._last_start)
                if delay > 0:
                    await asyncio.sleep(delay)
                self._last_start = time.monotonic()
            try:
                return await asyncio.to_thread(work)
            except DownloadCancelled as error:
                raise Cancelled("Cancelled") from error
            except Exception as error:
                failure = classify(error)
                if type(failure) is not YouTubeError or attempt == retries:
                    raise failure from error
                logger.warning("yt-dlp failed, retrying: %s", failure)
                await asyncio.sleep(5 * 3**attempt)

    async def resolve_source(self, kind: str, url: str) -> Source:
        def work() -> Source:
            options = self.options(extract_flat="in_playlist", playlistend=1, noplaylist=False)
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False, process=False)
            if kind == "playlist":
                return Source(
                    kind="playlist",
                    youtube_id=info["id"],
                    title=info.get("title") or info["id"],
                    owner_name=info.get("channel") or info.get("uploader"),
                    description=info.get("description"),
                )
            channel_id = info.get("channel_id") or info.get("id")
            if not channel_id or not channel_id.startswith("UC"):
                raise Unavailable("That URL did not resolve to a YouTube channel")
            name = info.get("channel") or info.get("uploader") or info.get("title") or channel_id
            handle = info.get("uploader_id")
            return Source(
                kind="channel",
                youtube_id=channel_id,
                title=name,
                channel_youtube_id=channel_id,
                channel_name=name,
                channel_handle=handle if handle and handle.startswith("@") else None,
                description=info.get("description"),
                subscriber_count=info.get("channel_follower_count"),
            )

        return await self._run(work)

    async def list_entries(
        self,
        kind: str,
        youtube_id: str,
        video_type: str | None,
        known: set[str] | None = None,
        stop_after_known: int = 10,
        cancelled: threading.Event | None = None,
    ) -> list[Entry]:
        """List a channel tab or playlist, newest first for channels.

        With `known`, stop once `stop_after_known` consecutive entries are already known;
        otherwise list everything.
        """
        if kind == "playlist":
            url = source_url("playlist", youtube_id)
        else:
            url = f"{channel_url(youtube_id)}/{TABS[video_type or 'video']}"

        def work() -> list[Entry]:
            options = self.options(
                extract_flat="in_playlist", noplaylist=False, sleep_interval_requests=1
            )
            entries: list[Entry] = []
            seen: set[str] = set()
            streak = 0
            with yt_dlp.YoutubeDL(options) as ydl:
                try:
                    info = ydl.extract_info(url, download=False, process=False)
                except yt_dlp.utils.DownloadError as error:
                    if "does not have a" in str(error).lower():
                        return []  # e.g. a channel without a Shorts tab
                    raise
                for raw in info.get("entries") or ():
                    if cancelled is not None and cancelled.is_set():
                        raise DownloadCancelled("Cancelled")
                    entry = _entry(raw, kind, video_type)
                    if entry is None or entry.youtube_id in seen:
                        continue
                    seen.add(entry.youtube_id)
                    entries.append(entry)
                    if known is not None:
                        streak = streak + 1 if entry.youtube_id in known else 0
                        if streak >= stop_after_known:
                            break
            return entries

        return await self._run(work)

    async def fetch_video(self, youtube_id: str) -> dict[str, Any]:
        def work() -> dict[str, Any]:
            with yt_dlp.YoutubeDL(self.options()) as ydl:
                info = ydl.extract_info(video_url(youtube_id), download=False, process=False)
                return ydl.sanitize_info(info)

        return await self._run(work)

    async def download(
        self,
        request: DownloadRequest,
        progress: ProgressCallback,
        cancelled: threading.Event,
    ) -> dict[str, Any]:
        """Download into request.workdir as media.<ext> with sidecars; return the final info."""

        def hook(data: dict[str, Any]) -> None:
            if cancelled.is_set():
                raise DownloadCancelled("Cancelled")
            progress(data)

        def postprocessor_hook(data: dict[str, Any]) -> None:
            if data.get("status") == "started":
                progress({"status": "processing"})

        height = quality_height(request.quality)
        cap = f"[height<={height}]" if height else ""
        languages = request.subtitle_languages
        options = self.options(
            format=f"bv*{cap}+ba/b{cap}/bv*+ba/b",
            # Resolution first, then the most playable container and codec at that resolution.
            format_sort=["res", "ext:mp4:m4a", "vcodec:h264"],
            merge_output_format="mp4/mkv",
            paths={"home": str(request.workdir), "temp": str(request.workdir)},
            outtmpl={"default": "media.%(ext)s"},
            writethumbnail=True,
            writesubtitles=bool(languages),
            writeautomaticsub=bool(languages),
            subtitleslangs=languages,
            subtitlesformat="vtt/best",
            getcomments=request.comments,
            extractor_args={"youtube": {"max_comments": ["1000", "all", "100"]}},
            postprocessors=[
                {"key": "FFmpegSubtitlesConvertor", "format": "vtt", "when": "before_dl"},
                {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"},
                {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True},
            ],
            progress_hooks=[hook],
            postprocessor_hooks=[postprocessor_hook],
        )

        def work() -> dict[str, Any]:
            request.workdir.mkdir(parents=True, exist_ok=True)
            with yt_dlp.YoutubeDL(options) as ydl:
                raw = ydl.extract_info(video_url(request.youtube_id), download=False, process=False)
                status = raw.get("live_status")
                if status in NOT_READY:
                    raise NotReady(
                        f"Not available for download yet ({status.replace('_', ' ')})",
                        raw.get("release_timestamp"),
                    )
                if cancelled.is_set():
                    raise DownloadCancelled("Cancelled")
                return ydl.sanitize_info(ydl.process_ie_result(raw, download=True))

        return await self._run(work, retries=0)

    def versions(self) -> dict[str, str | None]:
        return runtime_versions()


@functools.cache
def runtime_versions() -> dict[str, str | None]:
    runtime = None
    runtime_class = supported_js_runtimes.value.get(config.YTDLP_JS_RUNTIME)
    if runtime_class:
        info = runtime_class(path=config.YTDLP_JS_RUNTIME_PATH).info
        if info and info.supported:
            runtime = f"{info.name} {info.version}"
    return {"yt_dlp": yt_dlp.version.__version__, "js_runtime": runtime}


def _entry(raw: dict[str, Any] | None, kind: str, video_type: str | None) -> Entry | None:
    if not raw or not VIDEO_ID.fullmatch(str(raw.get("id") or "")):
        return None
    if kind == "channel":
        entry_type = video_type or "video"
    elif "/shorts/" in str(raw.get("url") or ""):
        entry_type = "short"
    elif raw.get("live_status") in ("was_live", "post_live", "is_live", "is_upcoming"):
        entry_type = "live"
    else:
        entry_type = "video"
    duration = raw.get("duration")
    return Entry(
        youtube_id=raw["id"],
        video_type=entry_type,
        title=raw.get("title"),
        duration=int(duration) if isinstance(duration, int | float) else None,
        live_status=raw.get("live_status"),
        channel_youtube_id=raw.get("channel_id"),
        channel_name=raw.get("channel") or raw.get("uploader"),
    )
