"""A YouTube stand-in with the adapter's async interface, driven by test data."""

import asyncio
import json
import threading
from dataclasses import dataclass, field
from typing import Any

from app.youtube import Cancelled, DownloadRequest, Entry, NotReady, Source

CHANNEL_ID = "UCuAXFkgsw1L7xaCfnd5JJOw"
OTHER_CHANNEL_ID = "UCdifferentUploader12345"
PLAYLIST_ID = "PLfixture0000000000000000000000001"
MEDIA = b"\x00\x00\x00\x18ftypmp42" + b"local-video-fixture" * 64


@dataclass
class FakeVideo:
    youtube_id: str
    title: str
    channel_id: str = CHANNEL_ID
    channel: str = "Fixture Channel"
    upload_date: str = "20250101"
    duration: int = 120
    width: int = 1920
    height: int = 1080
    live_status: str | None = "not_live"
    extra: dict[str, Any] = field(default_factory=dict)

    def info(self) -> dict[str, Any]:
        return {
            "id": self.youtube_id,
            "title": self.title,
            "description": f"About {self.title}",
            "channel_id": self.channel_id,
            "channel": self.channel,
            "uploader_id": "@fixture",
            "upload_date": self.upload_date,
            "duration": self.duration,
            "view_count": 1000,
            "like_count": 10,
            "width": self.width,
            "height": self.height,
            "live_status": self.live_status,
            "webpage_url": f"https://www.youtube.com/watch?v={self.youtube_id}",
            "formats": [{"format_id": "137", "url": "https://signed.invalid/expires"}],
            **self.extra,
        }


class FakeYouTube:
    def __init__(self) -> None:
        self.videos: dict[str, FakeVideo] = {}
        self.tabs: dict[str, list[str]] = {"video": [], "short": [], "live": []}
        self.playlist: list[str] = []
        self.calls: list[tuple] = []
        self.failures: dict[str, Exception] = {}
        self.download_failures: dict[str, Exception] = {}
        self.source_failure: Exception | None = None
        self.hold = threading.Event()
        self.write_media = True

    def add(self, youtube_id: str, title: str | None = None, **fields: Any) -> FakeVideo:
        video = FakeVideo(youtube_id, title or f"Video {youtube_id}", **fields)
        self.videos[youtube_id] = video
        return video

    async def resolve_source(self, kind: str, url: str) -> Source:
        self.calls.append(("resolve", kind, url))
        if self.source_failure:
            raise self.source_failure
        if kind == "playlist":
            return Source("playlist", PLAYLIST_ID, "Fixture Playlist", owner_name="Playlist Owner")
        return Source(
            "channel",
            CHANNEL_ID,
            "Fixture Channel",
            channel_youtube_id=CHANNEL_ID,
            channel_name="Fixture Channel",
            channel_handle="@fixture",
        )

    async def list_entries(
        self,
        kind: str,
        youtube_id: str,
        video_type: str | None,
        known: set[str] | None = None,
        stop_after_known: int = 10,
        cancelled: threading.Event | None = None,
    ) -> list[Entry]:
        self.calls.append(("list", kind, video_type, known is None))
        await asyncio.sleep(0)
        if self.source_failure:
            raise self.source_failure
        ids = self.playlist if kind == "playlist" else self.tabs[video_type or "video"]
        entries, streak = [], 0
        for youtube_id in ids:
            video = self.videos[youtube_id]
            entry_type = video_type or ("live" if video.live_status == "was_live" else "video")
            entries.append(
                Entry(youtube_id, entry_type, video.title, video.duration, video.live_status)
            )
            if known is not None:
                streak = streak + 1 if youtube_id in known else 0
                if streak >= stop_after_known:
                    break
        return entries

    async def fetch_video(self, youtube_id: str) -> dict[str, Any]:
        self.calls.append(("fetch", youtube_id))
        if youtube_id in self.failures:
            raise self.failures[youtube_id]
        return self.videos[youtube_id].info()

    async def download(self, request: DownloadRequest, progress, cancelled: threading.Event):
        self.calls.append(("download", request))
        if request.youtube_id in self.download_failures:
            raise self.download_failures[request.youtube_id]
        video = self.videos[request.youtube_id]
        progress({"status": "downloading", "downloaded_bytes": 10, "total_bytes": 100})
        while self.hold.is_set():
            if cancelled.is_set():
                raise Cancelled("Cancelled")
            await asyncio.sleep(0.01)
        if video.live_status in ("is_upcoming", "is_live"):
            raise NotReady("Not available for download yet", None)
        workdir = request.workdir
        workdir.mkdir(parents=True, exist_ok=True)
        if self.write_media:
            (workdir / "media.mp4").write_bytes(MEDIA)
        (workdir / "media.jpg").write_bytes(b"jpeg-fixture")
        for language in request.subtitle_languages:
            (workdir / f"media.{language}.vtt").write_text(
                "WEBVTT\n\n00:00.000 --> 00:01.000\nHi\n"
            )
        progress({"status": "processing"})
        info = video.info()
        if request.comments:
            info["comments"] = [{"id": "c1", "text": "First", "author": "Viewer"}]
        return json.loads(json.dumps(info))

    def versions(self) -> dict[str, str | None]:
        return {"yt_dlp": "fake", "js_runtime": "deno 0.0"}
