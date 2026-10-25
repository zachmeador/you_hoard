"""A YouTube stand-in with the adapter's async interface, driven by test data."""

import asyncio
import json
import threading
from dataclasses import dataclass, field
from typing import Any

from app.tracks import (
    audio_tracks,
    extra_audio,
    original_language,
    plan_subtitles,
    wants_chat,
)
from app.youtube import (
    Cancelled,
    DownloadRequest,
    Entry,
    Listing,
    NotReady,
    Source,
    YouTubeError,
)

CHANNEL_ID = "UCuAXFkgsw1L7xaCfnd5JJOw"
OTHER_CHANNEL_ID = "UCdifferentUploader12345"
PLAYLIST_ID = "PLfixture0000000000000000000000001"
MEDIA = b"\x00\x00\x00\x18ftypmp42" + b"local-video-fixture" * 64
AVATAR_URL = "https://yt3.invalid/avatar=s0-rj"
AVATAR_SIZED_URL = "https://yt3.invalid/avatar=s900-c-k-c0x00ffffff-no-rj"
BANNER_URL = "https://yt3.invalid/banner=s0-rj"
AVATAR = b"\xff\xd8\xff\xe0avatar-fixture"
BANNER = b"\xff\xd8\xff\xe0banner-fixture"


def chat_line(offset_ms: int, author: str, text: str, amount: str | None = None) -> str:
    """One line of yt-dlp's live chat replay file."""
    renderer = {
        "message": {"runs": [{"text": text}]},
        "authorName": {"simpleText": author},
    }
    name = "liveChatTextMessageRenderer"
    if amount:
        renderer["purchaseAmountText"] = {"simpleText": amount}
        name = "liveChatPaidMessageRenderer"
    action = {
        "replayChatItemAction": {
            "actions": [{"addChatItemAction": {"item": {name: renderer}}}],
            "videoOffsetTimeMsec": str(offset_ms),
        }
    }
    return json.dumps(action)


@dataclass
class FakeVideo:
    youtube_id: str
    title: str
    channel_id: str = CHANNEL_ID
    channel: str = "Fixture Channel"
    upload_date: str = "20250101"
    timestamp: int | None = None
    duration: int = 120
    width: int = 1920
    height: int = 1080
    live_status: str | None = "not_live"
    view_count: int = 1000
    availability: str = "public"
    age_limit: int = 0
    comment_count: int | None = None
    vcodec: str = "avc1.640028"
    acodec: str = "mp4a.40.2"
    fps: int = 30
    dynamic_range: str = "SDR"
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    chapters: list[dict[str, Any]] = field(default_factory=list)
    heatmap: list[dict[str, Any]] = field(default_factory=list)
    # Uploaded subtitle tracks and automatic captions as language -> name.
    subtitles: dict[str, str] = field(default_factory=lambda: {"en": "English"})
    automatic_captions: dict[str, str] = field(default_factory=dict)
    # Languages whose caption download fails, as YouTube's rate limit does.
    failing_subtitles: set[str] = field(default_factory=set)
    # Audio tracks as language -> language preference; the original ranks highest.
    audio: dict[str, int] = field(default_factory=lambda: {"en": -1})
    comments: list[dict[str, Any]] | None = None
    chat: list[str] | None = None
    # What SponsorBlock knows as (start, end, category); None when its lookup fails.
    sponsor_segments: list[tuple[float, float, str]] | None = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def formats(self) -> list[dict[str, Any]]:
        signed = "https://signed.invalid/expires"
        video = {
            "format_id": "137",
            "url": signed,
            "vcodec": self.vcodec,
            "acodec": "none",
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "dynamic_range": self.dynamic_range,
            "ext": "mp4",
        }
        audio = [
            {
                "format_id": f"140-{index}",
                "url": signed,
                "vcodec": "none",
                "acodec": self.acodec,
                "language": language,
                "language_preference": preference,
                "ext": "m4a",
            }
            for index, (language, preference) in enumerate(self.audio.items())
        ]
        return [video, *audio]

    def info(self) -> dict[str, Any]:
        def captions(names: dict[str, str]) -> dict[str, Any]:
            return {
                lang: [{"ext": "vtt", "url": f"https://captions.invalid/{lang}", "name": name}]
                for lang, name in names.items()
            }

        subtitles = captions(self.subtitles)
        if self.chat is not None:
            subtitles["live_chat"] = [
                {
                    "ext": "json",
                    "protocol": "youtube_live_chat_replay",
                    "url": "https://chat.invalid",
                }
            ]
        info = {
            "id": self.youtube_id,
            "title": self.title,
            "description": f"About {self.title}",
            "channel_id": self.channel_id,
            "channel": self.channel,
            "uploader_id": "@fixture",
            "upload_date": self.upload_date,
            "duration": self.duration,
            "view_count": self.view_count,
            "like_count": 10,
            "width": self.width,
            "height": self.height,
            "live_status": self.live_status,
            "availability": self.availability,
            "age_limit": self.age_limit,
            "webpage_url": f"https://www.youtube.com/watch?v={self.youtube_id}",
            "formats": self.formats(),
            "subtitles": subtitles,
            "automatic_captions": captions(self.automatic_captions),
            **self.extra,
        }
        optional = {
            "timestamp": self.timestamp,
            "comment_count": self.comment_count,
            "tags": self.tags,
            "categories": self.categories,
            "chapters": self.chapters,
            "heatmap": self.heatmap,
        }
        info.update({key: value for key, value in optional.items() if value not in (None, [])})
        return info


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
        self.verified = True
        self.avatars = [AVATAR_URL, AVATAR_SIZED_URL]
        self.banners = [BANNER_URL]
        self.images: dict[str, bytes] = {AVATAR_URL: AVATAR, BANNER_URL: BANNER}

    def add(self, youtube_id: str, title: str | None = None, **fields: Any) -> FakeVideo:
        video = FakeVideo(youtube_id, title or f"Video {youtube_id}", **fields)
        self.videos[youtube_id] = video
        return video

    def channel_source(self) -> Source:
        return Source(
            "channel",
            CHANNEL_ID,
            "Fixture Channel",
            channel_youtube_id=CHANNEL_ID,
            channel_name="Fixture Channel",
            channel_handle="@fixture",
            subscriber_count=1234,
            verified=self.verified,
            avatars=list(self.avatars),
            banners=list(self.banners),
        )

    async def resolve_source(self, kind: str, url: str) -> Source:
        self.calls.append(("resolve", kind, url))
        if self.source_failure:
            raise self.source_failure
        if kind == "playlist":
            return Source("playlist", PLAYLIST_ID, "Fixture Playlist", owner_name="Playlist Owner")
        return self.channel_source()

    async def list_entries(
        self,
        kind: str,
        youtube_id: str,
        video_type: str | None,
        known: set[str] | None = None,
        stop_after_known: int = 10,
        cancelled: threading.Event | None = None,
    ) -> Listing:
        self.calls.append(("list", kind, video_type, known is None))
        await asyncio.sleep(0)
        if self.source_failure:
            raise self.source_failure
        ids = self.playlist if kind == "playlist" else self.tabs[video_type or "video"]
        entries, streak = [], 0
        for youtube_id in ids:
            video = self.videos[youtube_id]
            entry_type = video_type or ("live" if video.live_status == "was_live" else "video")
            uploader = (video.channel_id, video.channel) if kind == "playlist" else (None, None)
            entries.append(
                Entry(
                    youtube_id,
                    entry_type,
                    video.title,
                    video.duration,
                    video.live_status,
                    *uploader,
                    view_count=video.view_count,
                )
            )
            if known is not None:
                streak = streak + 1 if youtube_id in known else 0
                if streak >= stop_after_known:
                    break
        return Listing(entries, self.channel_source() if kind == "channel" else None)

    async def fetch_video(self, youtube_id: str) -> dict[str, Any]:
        self.calls.append(("fetch", youtube_id))
        if youtube_id in self.failures:
            raise self.failures[youtube_id]
        return self.videos[youtube_id].info()

    async def fetch_image(self, url: str) -> bytes:
        self.calls.append(("image", url))
        if url not in self.images:
            raise YouTubeError("HTTP Error 404: Not Found")
        return self.images[url]

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
        progress({"status": "processing"})

        info = video.info()
        formats = info["formats"]
        languages = audio_tracks(info)
        original = original_language(languages) or next(iter(languages), None)
        extras = extra_audio(info, request.audio_languages)
        audio = [
            f for f in formats if f["vcodec"] == "none" and f["language"] in (original, *extras)
        ]
        audio.sort(key=lambda f: [original, *extras].index(f["language"]))
        picked = [formats[0], *audio]
        info["requested_formats"] = picked
        info["vcodec"], info["fps"] = picked[0]["vcodec"], picked[0]["fps"]
        info["dynamic_range"] = picked[0]["dynamic_range"]
        if len(audio) == 1:
            info["acodec"] = audio[0]["acodec"]

        saved = []
        for track in plan_subtitles(info, request.subtitle_languages, request.auto_captions):
            if track.lang in video.failing_subtitles:
                continue
            (workdir / f"media.{track.lang}.vtt").write_text(
                f"WEBVTT\n\n00:00.000 --> 00:01.000\nHi {track.lang}\n"
            )
            saved.append(track.as_dict())
        if wants_chat(info, request.live_chat):
            (workdir / "media.live_chat.json").write_text("\n".join(video.chat or []) + "\n")
        if request.comments:
            info["comments"] = video.comments or [{"id": "c1", "text": "First", "author": "Viewer"}]
        if request.sponsorblock and video.sponsor_segments is not None:
            info["sponsorblock_chapters"] = [
                {"start_time": start, "end_time": end, "category": category, "type": "skip"}
                for start, end, category in video.sponsor_segments
            ]
        info["_youhoard"] = {"subtitles": saved}
        return json.loads(json.dumps(info))

    def versions(self) -> dict[str, str | None]:
        return {"yt_dlp": "fake", "js_runtime": "deno 0.0"}
