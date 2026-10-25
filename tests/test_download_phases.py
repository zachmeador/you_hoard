"""How the adapter sequences a download, with yt-dlp replaced by a stand-in that records its use.

The fake YouTube skips the adapter, so this is the only check that the phases are wired as
intended: media first, then best-effort subtitles, chat and SponsorBlock.
"""

import asyncio
import copy
import re
import threading
from pathlib import Path
from typing import Any

import pytest

from app import youtube
from app.youtube import DownloadRequest, YouTube
from tests.test_adapter import DUBBED, fmt

SUBTITLES = {
    "en": [{"ext": "vtt", "name": "English"}],
    "de": [{"ext": "vtt", "name": "German"}],
    "live_chat": [{"ext": "json", "protocol": "youtube_live_chat_replay"}],
}
CAPTIONS = {
    "es": [{"ext": "vtt", "name": "Spanish"}],
    "fr": [{"ext": "vtt", "name": "French"}],
    "fr-orig": [{"ext": "vtt", "name": "French (Original)"}],
}
RAW = {
    **DUBBED,
    "duration": 600,
    "live_status": "not_live",
    "comment_count": 9400,
    "subtitles": SUBTITLES,
    "automatic_captions": CAPTIONS,
    "__post_extractor": lambda: {"comments": []},
}
PICKED = [
    fmt("134", "mp4", vcodec="avc1.4D401E", height=360, fps=30),
    fmt("140-0", "m4a", vcodec="none", acodec="mp4a.40.2", language="en-US"),
    fmt("140-1", "m4a", vcodec="none", acodec="mp4a.40.2", language="es"),
]


class Stub:
    """Stands in for yt_dlp.YoutubeDL and keeps every instance for inspection."""

    instances: list["Stub"] = []
    failing: set[str] = set()
    crash_on_extras = False

    def __init__(self, params: dict[str, Any]) -> None:
        self.params = params
        self.processed: list[dict[str, Any]] = []
        Stub.instances.append(self)

    def __enter__(self) -> "Stub":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def extract_info(self, url: str, download: bool = False, process: bool = True):
        return copy.deepcopy(RAW)

    def sanitize_info(self, info: dict[str, Any]) -> dict[str, Any]:
        return info

    def process_ie_result(self, raw: dict[str, Any], download: bool = True) -> dict[str, Any]:
        self.processed.append(raw)
        workdir = Path(self.params["paths"]["home"]) if "paths" in self.params else None
        if self.params.get("skip_download") and self.params.get("writesubtitles"):
            self.fetch_extras(workdir)
            return raw
        if self.params.get("skip_download"):
            return {"requested_formats": PICKED}
        assert workdir is not None
        (workdir / "media.mp4").write_bytes(b"video")
        for hook in self.params["progress_hooks"]:
            hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 2})
        return {**raw, "requested_formats": PICKED, "ext": "mp4", "comment_count": 1000}

    def fetch_extras(self, workdir: Path) -> None:
        if Stub.crash_on_extras:
            raise RuntimeError("YouTube said no")
        for hook in self.params["progress_hooks"]:
            hook({"status": "downloading"})
        for pattern in self.params["subtitleslangs"]:
            lang = re.sub(r"\\(.)", r"\1", pattern)
            if lang in Stub.failing:
                continue
            suffix = "json" if lang == "live_chat" else "vtt"
            (workdir / f"media.{lang}.{suffix}").write_text("saved")


class SponsorStub:
    failing = False

    def __init__(self, downloader: Any, categories: list[str]) -> None:
        self.categories = categories

    def run(self, info: dict[str, Any]):
        if SponsorStub.failing:
            raise RuntimeError("SponsorBlock is down")
        assert info["extractor_key"] == "Youtube" and info["id"] == "dQw4w9WgXcQ"
        segment = {"start_time": 5, "end_time": 9, "category": "sponsor", "title": "Sponsor"}
        return [], {"sponsorblock_chapters": [{**segment, "type": "skip", "_categories": [1]}]}


@pytest.fixture
def stubbed(monkeypatch):
    Stub.instances, Stub.failing, Stub.crash_on_extras = [], set(), False
    SponsorStub.failing = False
    monkeypatch.setattr(youtube.yt_dlp, "YoutubeDL", Stub)
    monkeypatch.setattr(youtube, "SponsorBlockPP", SponsorStub)
    monkeypatch.setattr(youtube, "SUBTITLE_SLEEP", 0)


def download(tmp_path: Path, cancelled: threading.Event | None = None, **fields: Any):
    request = DownloadRequest(
        youtube_id="dQw4w9WgXcQ",
        workdir=tmp_path / "work",
        quality="360p",
        subtitle_languages=["en", "es", "de"],
        comments=True,
        audio_languages=["es", "en"],
        live_chat=True,
        sponsorblock=True,
        **fields,
    )
    seen: list[dict[str, Any]] = []
    info = asyncio.run(
        YouTube(request_interval=0).download(request, seen.append, cancelled or threading.Event())
    )
    return info, seen


def test_media_comes_first_and_everything_else_is_best_effort(stubbed, tmp_path):
    info, progress = download(tmp_path)
    extractor, selection, media, extras, sponsorblock = Stub.instances

    assert extractor.params["getcomments"] is True
    assert extractor.params["extractor_args"]["youtube"]["max_comments"][0] == "1000"

    selector = "bv[height<=360]+ba+ba[language=es]/bv*[height<=360]+ba/b[height<=360]/bv*+ba/b"
    assert selection.params["format"] == selector
    assert selection.params["skip_download"] is True

    assert media.params["format"] == selector
    assert media.params["allow_multiple_audio_streams"] is True
    assert media.params["merge_output_format"] == "mp4"
    assert media.params["writethumbnail"] is True
    assert "writesubtitles" not in media.params and "getcomments" not in media.params
    assert media.processed[0]["comment_count"] == 9400
    assert "__post_extractor" in media.processed[0]

    assert extras.params["skip_download"] is True and extras.params["ignoreerrors"] is True
    assert extras.params["writesubtitles"] is True and extras.params["writeautomaticsub"] is True
    assert extras.params["subtitleslangs"] == ["en", "de", "es", "live_chat"]
    assert extras.params["subtitlesformat"] == "vtt/best"
    assert extras.params["sleep_interval_subtitles"] == 0
    assert extras.processed[0] is not media.processed[0]
    assert "__post_extractor" not in extras.processed[0]

    assert info["comment_count"] == 9400  # YouTube's count, not the 1000 comments saved
    assert [track["lang"] for track in info["_youhoard"]["subtitles"]] == ["en", "de", "es"]
    assert [track["source"] for track in info["_youhoard"]["subtitles"]] == [
        "uploaded",
        "uploaded",
        "translated",
    ]
    assert (tmp_path / "work" / "media.live_chat.json").exists()
    assert info["sponsorblock_chapters"] == [
        {"start_time": 5, "end_time": 9, "category": "sponsor", "title": "Sponsor", "type": "skip"}
    ]
    assert not sponsorblock.processed  # the lookup only reads segments; nothing is processed
    assert {"status": "processing"} in progress


def test_a_failed_language_is_left_out_not_fatal(stubbed, tmp_path):
    Stub.failing = {"de", "es"}
    info, _ = download(tmp_path)
    assert [track["lang"] for track in info["_youhoard"]["subtitles"]] == ["en"]
    assert info["comment_count"] == 9400


def test_a_crashing_extras_pass_still_returns_the_video(stubbed, tmp_path):
    Stub.crash_on_extras = True
    info, _ = download(tmp_path)
    assert info["_youhoard"]["subtitles"] == []
    assert (tmp_path / "work" / "media.mp4").exists()


def test_a_failed_sponsorblock_lookup_leaves_the_segments_out(stubbed, tmp_path):
    SponsorStub.failing = True
    info, _ = download(tmp_path)
    assert "sponsorblock_chapters" not in info
    assert len(info["_youhoard"]["subtitles"]) == 3


def test_nothing_extra_is_requested_unless_asked_for(stubbed, tmp_path):
    request = DownloadRequest("dQw4w9WgXcQ", tmp_path / "work", "best", [], False)
    info = asyncio.run(
        YouTube(request_interval=0).download(request, lambda _: None, threading.Event())
    )
    extractor, media, *rest = Stub.instances
    assert not rest  # no format preview, no subtitle pass
    assert extractor.params["getcomments"] is False
    assert media.params["format"] == "bv*+ba/b/bv*+ba/b"
    assert media.params["merge_output_format"] == "mp4/mkv"
    assert media.params["allow_multiple_audio_streams"] is False
    assert info["_youhoard"] == {"subtitles": []} and "sponsorblock_chapters" not in info


def test_cancelling_during_the_extras_pass_stops_the_download(stubbed, tmp_path, monkeypatch):
    cancelled = threading.Event()
    original = Stub.fetch_extras

    def cancel_then_fetch(self, workdir):
        cancelled.set()
        original(self, workdir)

    monkeypatch.setattr(Stub, "fetch_extras", cancel_then_fetch)
    with pytest.raises(youtube.Cancelled):
        download(tmp_path, cancelled)


def test_a_cancel_before_extraction_finishes_stops_early(stubbed, tmp_path):
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(youtube.Cancelled):
        download(tmp_path, cancelled)
    assert len(Stub.instances) == 1
