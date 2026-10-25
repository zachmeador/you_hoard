"""The parts of the yt-dlp adapter the fake bypasses, run offline against yt-dlp's own selector."""

from typing import Any

from app.tracks import extra_audio, fits_mp4
from app.youtube import YouTube, _channel_source, _entry, channel_art, format_selector


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
