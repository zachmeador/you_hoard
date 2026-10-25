"""Subtitles are fetched after the video, from uploaded tracks first, and labelled by source."""

import json

from tests.test_details import archived, sidecar_of
from tests.test_library import OTHER, VIDEO


def tracks(video):
    return [(t["lang"], t["source"]) for t in video["subtitles"]]


def test_each_track_is_labelled_uploaded_auto_or_translated(archive):
    archive.youtube.add(
        VIDEO,
        subtitles={"en": "English", "de": "German"},
        automatic_captions={"en": "English", "en-orig": "English (Original)", "es": "Spanish"},
    )
    video = archived(archive, subtitle_languages=["en", "es", "de"])
    assert tracks(video) == [("en", "uploaded"), ("de", "uploaded"), ("es", "translated")]
    assert [t["name"] for t in video["subtitles"]] == ["English", "German", "Spanish"]

    for track in video["subtitles"]:
        assert archive.client.get(track["url"]).text.startswith("WEBVTT")


def test_the_original_language_caption_is_auto_when_nothing_was_uploaded(archive):
    archive.youtube.add(
        VIDEO,
        subtitles={},
        automatic_captions={"en": "English", "en-orig": "English (Original)", "fr": "French"},
    )
    video = archived(archive, subtitle_languages=["en", "fr"])
    assert tracks(video) == [("en", "auto"), ("fr", "translated")]


def test_uploaded_tracks_win_over_captions_in_the_same_language(archive):
    archive.youtube.add(
        VIDEO,
        subtitles={"en": "English"},
        automatic_captions={"en": "English", "en-orig": "English (Original)"},
    )
    assert tracks(archived(archive)) == [("en", "uploaded")]


def test_captions_can_be_switched_off_per_video(archive):
    archive.youtube.add(
        VIDEO, subtitles={"en": "English"}, automatic_captions={"es": "Spanish", "en": "English"}
    )
    video = archived(archive, subtitle_languages=["en", "es"], auto_captions=False)
    assert tracks(video) == [("en", "uploaded")]
    assert archive.youtube.calls[-1][1].auto_captions is False


def test_a_failing_language_never_fails_the_video(archive):
    archive.youtube.add(
        VIDEO,
        subtitles={"en": "English", "de": "German", "fr": "French"},
        failing_subtitles={"de"},
    )
    video = archived(archive, subtitle_languages=["en", "de", "fr"])
    assert video["status"] == "archived"
    assert tracks(video) == [("en", "uploaded"), ("fr", "uploaded")]
    assert [t["lang"] for t in sidecar_of(archive, video)["_youhoard"]["subtitles"]] == ["en", "fr"]
    assert archive.client.get(f"/api/videos/{video['id']}/subtitles/de").status_code == 404


def test_languages_nobody_provides_are_skipped(archive):
    archive.youtube.add(VIDEO, subtitles={"en": "English"})
    video = archived(archive, subtitle_languages=["en", "ja"])
    assert tracks(video) == [("en", "uploaded")]


def test_codes_match_whole_and_all_means_every_uploaded_track(archive):
    uploaded = {"en": "English", "en-GB": "English (UK)", "pt-BR": "Portuguese (Brazil)"}
    archive.youtube.add(VIDEO, subtitles=uploaded, automatic_captions={"fr": "French"})
    archive.youtube.add(OTHER, subtitles=uploaded, automatic_captions={"fr": "French"})

    exact = archived(archive, VIDEO, subtitle_languages=["en"])
    assert tracks(exact) == [("en", "uploaded")]

    everything = archived(archive, OTHER, subtitle_languages=["all"])
    assert tracks(everything) == [
        ("en", "uploaded"),
        ("en-GB", "uploaded"),
        ("pt-BR", "uploaded"),
    ]


def test_the_sidecar_keeps_the_labels_without_the_app(archive):
    archive.youtube.add(
        VIDEO,
        subtitles={"en": "English"},
        automatic_captions={"es": "Spanish"},
    )
    video = archived(archive, subtitle_languages=["en", "es"])
    sidecar = sidecar_of(archive, video)
    assert sidecar["_youhoard"]["subtitles"] == [
        {"lang": "en", "name": "English", "source": "uploaded"},
        {"lang": "es", "name": "Spanish", "source": "translated"},
    ]
    assert "subtitles" not in sidecar and "automatic_captions" not in sidecar
    json.dumps(sidecar)


def test_no_subtitle_languages_means_no_subtitle_requests(archive):
    archive.youtube.add(VIDEO, subtitles={"en": "English"})
    video = archived(archive, subtitle_languages=[])
    assert video["subtitles"] == []
    assert archive.youtube.calls[-1][1].subtitle_languages == []


def test_subtitle_files_without_a_record_are_unknown(archive):
    archive.youtube.add(VIDEO)
    video = archived(archive)
    media = archive.media / video["media_path"]
    media.with_suffix(".fr.vtt").write_text("WEBVTT\n")
    archive.sql("UPDATE videos SET subtitle_tracks = NULL")
    sidecar = media.with_suffix(".info.json")
    info = json.loads(sidecar.read_text())
    info["_youhoard"].pop("subtitles")
    sidecar.write_text(json.dumps(info))
    detail = archive.client.get(f"/api/videos/{video['id']}").json()
    assert [(t["lang"], t["name"], t["source"]) for t in detail["subtitles"]] == [
        ("en", "English", "unknown"),
        ("fr", "French", "unknown"),
    ]
