"""The parts of the yt-dlp adapter the fake bypasses, run offline against yt-dlp's own selector."""

import asyncio
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
from yt_dlp.utils import DownloadError

from app import pace, youtube
from app.tracks import AUTO, TRANSLATED, UPLOADED, Track, extra_audio, fits_mp4
from app.youtube import (
    DownloadRequest,
    Paused,
    YouTube,
    _channel_source,
    _entry,
    channel_art,
    cookie_state,
    format_selector,
)


def fmt(format_id: str, ext: str, **fields: Any) -> dict[str, Any]:
    audio_only = fields.get("vcodec") == "none"
    return {
        "format_id": format_id,
        "url": f"https://media.invalid/{format_id}",
        "ext": ext,
        "protocol": "https",
        "vcodec": "none",
        "acodec": "none",
        "abr": 129.5 if audio_only else None,
        **fields,
    }


def raw_info(formats: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "dQw4w9WgXcQ",
        "title": "Fixture",
        "extractor": "youtube",
        "extractor_key": "Youtube",
        "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "formats": formats,
    }


def audio(format_id: str, ext: str, language: str, preference: int, codec: str) -> dict[str, Any]:
    return fmt(
        format_id,
        ext,
        vcodec="none",
        acodec=codec,
        language=language,
        language_preference=preference,
    )


DUBBED = raw_info(
    [
        fmt("18", "mp4", vcodec="avc1.42001E", acodec="mp4a.40.2", height=360, width=640),
        fmt("134", "mp4", vcodec="avc1.4D401E", height=360, width=640, fps=30),
        fmt("243", "webm", vcodec="vp9", height=360, width=640, fps=30),
        fmt("299", "mp4", vcodec="avc1.64002A", height=1080, width=1920, fps=60),
        audio("140-0", "m4a", "en-US", 10, "mp4a.40.2"),
        audio("251-0", "webm", "en-US", 10, "opus"),
        audio("140-1", "m4a", "es", -1, "mp4a.40.2"),
        audio("251-1", "webm", "es", -1, "opus"),
        audio("140-2", "m4a", "de", -1, "mp4a.40.2"),
        audio("140-3", "m4a", "pt-BR", -1, "mp4a.40.2"),
        audio("140-4", "m4a", "en-US-desc", -10, "mp4a.40.2"),
    ]
)


def picked(raw: dict[str, Any], cap: str, languages: list[str]) -> list[str]:
    selector = format_selector(cap, extra_audio(raw, languages))
    return [fmt["format_id"] for fmt in YouTube()._selected(raw, selector)]


def test_the_selector_without_extras_is_the_plain_resolution_first_one():
    assert format_selector("[height<=360]", []) == "bv*[height<=360]+ba/b[height<=360]/bv*+ba/b"
    assert format_selector("", []) == "bv*+ba/b/bv*+ba/b"


def test_extra_tracks_are_added_after_the_original_audio():
    assert extra_audio(DUBBED, ["es", "de", "en", "ja"]) == ["es", "de"]
    assert picked(DUBBED, "[height<=360]", ["es", "de"]) == ["134", "140-0", "140-1", "140-2"]
    assert picked(DUBBED, "[height<=1080]", ["pt"]) == ["299", "140-0", "140-3"]


def test_the_original_is_not_selected_twice_and_a_premerged_format_stays_out():
    # A request for the original's own language adds nothing, so the plain selector applies.
    assert extra_audio(DUBBED, ["en", "en-US"]) == []
    # With extras the video is chosen on its own: the progressive format 18 would bring a
    # second copy of the original audio.
    assert "18" not in picked(DUBBED, "[height<=360]", ["es"])


def test_extras_fit_mp4_when_every_stream_does():
    formats = YouTube()._selected(
        DUBBED, format_selector("[height<=360]", extra_audio(DUBBED, ["es"]))
    )
    assert fits_mp4(formats)
    vp9_only = raw_info(
        [
            fmt("313", "webm", vcodec="vp9", height=2160, width=3840),
            audio("140-0", "m4a", "en-US", 10, "mp4a.40.2"),
            audio("140-1", "m4a", "es", -1, "mp4a.40.2"),
        ]
    )
    chosen = YouTube()._selected(vp9_only, format_selector("", extra_audio(vp9_only, ["es"])))
    assert [fmt["format_id"] for fmt in chosen] == ["313", "140-0", "140-1"]
    assert not fits_mp4(chosen)


def test_videos_without_a_marked_original_get_no_extras():
    unmarked = raw_info(
        [
            audio("140-0", "m4a", "en", -1, "mp4a.40.2"),
            audio("140-1", "m4a", "es", -1, "mp4a.40.2"),
        ]
    )
    assert extra_audio(unmarked, ["es"]) == []
    assert extra_audio(raw_info([audio("140-0", "m4a", "en", -1, "mp4a.40.2")]), ["es"]) == []


def test_channel_art_prefers_the_uncropped_originals_as_jpeg():
    cdn = "https://yt3.googleusercontent.com"
    thumbnails = [
        {"url": f"{cdn}/avatar=s900-c-k-c0x00ffffff-no-rj", "height": 900, "width": 900},
        {"url": f"{cdn}/avatar=s0", "id": "avatar_uncropped", "preference": 1},
        {
            "url": f"{cdn}/banner=w1060-fcrop64=1,00005a57ffffa5a8-k-c0xffffffff-no-nd-rj",
            "width": 1060,
            "height": 175,
        },
        {
            "url": f"{cdn}/banner=w2560-fcrop64=1,00005a57ffffa5a8-k-c0xffffffff-no-nd-rj",
            "width": 2560,
            "height": 424,
        },
        {"url": f"{cdn}/banner=s0", "id": "banner_uncropped", "preference": -5},
    ]
    avatars, banners = channel_art(thumbnails)
    assert avatars == [f"{cdn}/avatar=s0-rj", f"{cdn}/avatar=s900-c-k-c0x00ffffff-no-rj"]
    assert banners == [
        f"{cdn}/banner=s0-rj",
        f"{cdn}/banner=w2560-fcrop64=1,00005a57ffffa5a8-k-c0xffffffff-no-nd-rj",
    ]
    assert channel_art(thumbnails[:1]) == ([thumbnails[0]["url"]], [])
    assert channel_art(None) == ([], [])


def test_a_tab_listing_describes_its_channel():
    listing = {
        "id": "UCHnyfMqiRRG1u-2MsSQLbXA",
        "channel_id": "UCHnyfMqiRRG1u-2MsSQLbXA",
        "channel": "Veritasium",
        "title": "Veritasium - Videos",
        "uploader_id": "@veritasium",
        "channel_follower_count": 21400000,
        "channel_is_verified": True,
        "thumbnails": [{"url": "https://yt3.invalid/a=s0", "id": "avatar_uncropped"}],
    }
    source = _channel_source(listing)
    assert (source.youtube_id, source.title, source.channel_handle) == (
        "UCHnyfMqiRRG1u-2MsSQLbXA",
        "Veritasium",
        "@veritasium",
    )
    assert source.verified is True and source.subscriber_count == 21400000
    assert source.avatars == ["https://yt3.invalid/a=s0-rj"] and source.banners == []
    assert _channel_source({**listing, "channel_is_verified": None}).verified is False
    assert _channel_source({"id": "PLsomething"}) is None


def test_playlist_entries_know_their_uploader_and_views():
    raw = {
        "id": "dQw4w9WgXcQ",
        "title": "A song",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "duration": 213.0,
        "view_count": 1700000000,
        "channel": "Rick Astley",
        "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw",
    }
    entry = _entry(raw, "playlist", None)
    assert (entry.channel_name, entry.channel_youtube_id) == ("Rick Astley", raw["channel_id"])
    assert entry.view_count == 1700000000 and entry.duration == 213
    odd = _entry({**raw, "channel_id": "not-a-channel", "view_count": None}, "playlist", None)
    assert odd.channel_youtube_id is None and odd.view_count is None


def test_images_come_over_https_within_limits(monkeypatch):
    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/moved":
            return httpx.Response(302, headers={"location": "https://yt3.invalid/avatar"})
        if request.url.path == "/avatar":
            return httpx.Response(200, content=b"\xff\xd8\xffjpeg")
        if request.url.path == "/huge":
            return httpx.Response(200, content=b"x" * 5000)
        return httpx.Response(404)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        youtube.httpx,
        "AsyncClient",
        lambda **options: real(transport=httpx.MockTransport(serve), **options),
    )
    monkeypatch.setattr(youtube, "MAX_IMAGE_BYTES", 1000)

    def fetch(url: str) -> bytes:
        return asyncio.run(YouTube().fetch_image(url))

    assert fetch("https://yt3.invalid/avatar") == b"\xff\xd8\xffjpeg"
    assert fetch("https://yt3.invalid/moved") == b"\xff\xd8\xffjpeg"
    with pytest.raises(youtube.YouTubeError, match="too large"):
        fetch("https://yt3.invalid/huge")
    with pytest.raises(httpx.HTTPStatusError):
        fetch("https://yt3.invalid/missing")
    with pytest.raises(youtube.YouTubeError, match="https"):
        fetch("http://yt3.invalid/avatar")


@pytest.fixture
def captions(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A local stand-in for YouTube's captions: "/ok" serves one and "/limited" answers 429."""
    monkeypatch.setattr(pace, "SUBTITLE_SLEEP", 0)
    body = b"WEBVTT\n\n00:00.000 --> 00:01.000\nHi\n"

    class Captions(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response({"/ok": 200, "/limited": 429}.get(self.path, 404))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Captions)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def fetch_extras(
    workdir: Path, captions: str, *wanted: tuple[str, str, str]
) -> tuple[list[str], str | None]:
    """Run the real extras step over (language, source, path); returns saved tracks, refusal."""
    raw = raw_info([fmt("18", "mp4", vcodec="avc1.42001E", acodec="mp4a.40.2")])
    raw["subtitles"], raw["automatic_captions"] = {}, {}
    for lang, source, path in wanted:
        group = "subtitles" if source == UPLOADED else "automatic_captions"
        raw[group][lang] = [{"ext": "vtt", "url": f"{captions}{path}"}]
    tracks = [Track(lang, lang, source) for lang, source, _ in wanted]
    request = DownloadRequest("dQw4w9WgXcQ", workdir, None, [], False)
    saved, refused = YouTube()._extras(raw, request, tracks, False, lambda: None)
    return [track.lang for track in saved], refused


@pytest.mark.parametrize("source", [UPLOADED, AUTO])
def test_a_refused_subtitle_keeps_the_rest_and_says_what_youtube_answered(
    tmp_path, captions, source
):
    saved, refused = fetch_extras(
        tmp_path, captions, ("en", UPLOADED, "/ok"), ("de", source, "/limited")
    )
    assert saved == ["en"]
    assert refused and "HTTP Error 429" in refused


def test_a_refused_translation_is_only_a_lost_track(tmp_path, captions):
    saved, refused = fetch_extras(
        tmp_path, captions, ("en", UPLOADED, "/ok"), ("de", TRANSLATED, "/limited")
    )
    assert (saved, refused) == (["en"], None)


def test_a_track_that_fails_for_another_reason_is_not_a_refusal(tmp_path, captions):
    assert fetch_extras(tmp_path, captions, ("de", UPLOADED, "/missing")) == ([], None)


def cookie_file(path: Path, *lines: str) -> Path:
    path.write_text("# Netscape HTTP Cookie File\n" + "".join(lines))
    return path


def cookie(name: str, domain: str = ".youtube.com", expires: int = 4102444800) -> str:
    return f"{domain}\tTRUE\t/\tTRUE\t{expires}\t{name}\tvalue\n"


@pytest.mark.parametrize(
    ("lines", "state"),
    [
        ([cookie("LOGIN_INFO"), cookie("SAPISID")], "signed_in"),
        ([cookie("LOGIN_INFO"), cookie("__Secure-3PAPISID")], "signed_in"),
        (["#HttpOnly_" + cookie("LOGIN_INFO"), cookie("__Secure-1PAPISID")], "signed_in"),
        ([cookie("VISITOR_INFO1_LIVE")], "anonymous"),
        ([cookie("LOGIN_INFO")], "anonymous"),
        ([cookie("SAPISID")], "anonymous"),
        ([cookie("LOGIN_INFO", expires=1000), cookie("SAPISID")], "anonymous"),
        ([cookie("LOGIN_INFO", ".example.com"), cookie("SAPISID", ".example.com")], "anonymous"),
    ],
    ids=[
        "session",
        "secure",
        "http only",
        "visitor",
        "rotated",
        "no login",
        "expired",
        "elsewhere",
    ],
)
def test_a_cookie_file_is_signed_in_by_the_same_test_yt_dlp_uses(tmp_path, lines, state):
    assert cookie_state(cookie_file(tmp_path / "cookies.txt", *lines)) == state


def test_a_cookie_file_that_is_not_netscape_format_is_unreadable(tmp_path):
    exported = tmp_path / "cookies.json"
    exported.write_text('[{"name": "LOGIN_INFO", "value": "value"}]')
    assert cookie_state(exported) == "unreadable"


def test_no_cookie_file_is_no_cookies(tmp_path):
    assert cookie_state(None) == "none"
    assert cookie_state(tmp_path / "missing.txt") == "none"


class Scripted:
    """Stands in for yt_dlp.YoutubeDL; what extract_info answers is set by each test."""

    calls: list[str] = []
    answer: Callable[[str], Any]

    def __init__(self, params: dict[str, Any]) -> None:
        self.params = params

    def __enter__(self) -> "Scripted":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def extract_info(self, url: str, download: bool = False, process: bool = True) -> Any:
        Scripted.calls.append(url)
        return Scripted.answer(url)

    def sanitize_info(self, info: dict[str, Any]) -> dict[str, Any]:
        return info


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> type[Scripted]:
    Scripted.calls = []
    monkeypatch.setattr(youtube.yt_dlp, "YoutubeDL", Scripted)
    return Scripted


def refuse_while(paused: threading.Event) -> Callable[[], None]:
    """A before_call that raises Paused once the flag is set, as the gate's does."""

    def before_call() -> None:
        if paused.is_set():
            raise Paused("2999-01-01T00:00:00Z")

    return before_call


def test_a_pause_stops_a_metadata_call_before_its_retry(scripted, monkeypatch):
    paused = threading.Event()

    def fail(url: str) -> dict[str, Any]:
        raise DownloadError("ERROR: HTTP Error 503: Service Unavailable")

    async def pause_while_waiting_to_retry(seconds: float) -> None:
        paused.set()

    scripted.answer = fail
    monkeypatch.setattr(youtube.asyncio, "sleep", pause_while_waiting_to_retry)
    adapter = YouTube(request_interval=0)
    adapter.before_call = refuse_while(paused)
    with pytest.raises(Paused):
        asyncio.run(adapter.fetch_video("dQw4w9WgXcQ"))
    assert len(scripted.calls) == 1  # the retry never reached YouTube


def test_a_pause_stops_calls_that_were_waiting_for_their_turn(scripted):
    paused = threading.Event()
    scripted.answer = lambda url: {"id": url}
    adapter = YouTube(request_interval=0.3)
    adapter.before_call = refuse_while(paused)

    async def three_calls() -> list[Any]:
        first = asyncio.create_task(adapter.fetch_video("first"))
        await asyncio.sleep(0.05)
        waiting = [asyncio.create_task(adapter.fetch_video(name)) for name in ("second", "third")]
        await asyncio.sleep(0.05)
        paused.set()
        return await asyncio.gather(first, *waiting, return_exceptions=True)

    first, *waiting = asyncio.run(three_calls())
    assert first["id"].endswith("first")
    assert all(isinstance(result, Paused) for result in waiting)
    assert len(scripted.calls) == 1


def test_a_pause_stops_a_listing_partway(scripted):
    paused = threading.Event()
    pulled: list[int] = []

    def entries():
        for n in range(10):
            if n == 3:
                paused.set()
            pulled.append(n)
            yield {"id": f"vid{n:08d}", "title": f"Video {n}"}

    scripted.answer = lambda url: {"entries": entries()}
    adapter = YouTube(request_interval=0)
    adapter.before_call = refuse_while(paused)
    with pytest.raises(Paused):
        asyncio.run(adapter.list_entries("playlist", "PLfixture0000000000000000000000001", None))
    assert pulled == [0, 1, 2, 3]  # the rest of the listing was never asked for
