"""What an archive records about each video and file, and how the detail view reports it."""

import json

from tests.fake_youtube import CHANNEL_ID
from tests.test_library import OTHER, VIDEO, add

CHAPTERS = [
    {"start_time": 0, "end_time": 30, "title": "Intro"},
    {"start_time": 30, "end_time": 120, "title": "The main part"},
]
HEATMAP = [
    {"start_time": 0, "end_time": 60, "value": 1.0},
    {"start_time": 60, "end_time": 120, "value": 0.25},
]


def archived(archive, youtube_id=VIDEO, **options):
    video = add(archive, youtube_id, **options)
    archive.wait_job(video["job_id"])
    return archive.client.get(f"/api/videos/{video['id']}").json()


def sidecar_of(archive, video):
    media = archive.media / video["media_path"]
    return json.loads(media.with_suffix(".info.json").read_text())


def test_download_records_what_the_file_and_the_video_are_like(archive):
    archive.youtube.add(
        VIDEO,
        "Detailed",
        timestamp=1735732800,
        availability="unlisted",
        age_limit=18,
        comment_count=4321,
        vcodec="av01.0.08M.08",
        acodec="opus",
        fps=60,
        dynamic_range="HDR10",
        tags=["physics", "waves"],
        categories=["Education"],
        chapters=CHAPTERS,
        heatmap=HEATMAP,
    )
    video = archived(archive)

    assert video["published_at"] == "2025-01-01T12:00:00Z"
    assert video["media_path"].endswith(f"/2025-01-01 Detailed [{VIDEO}].mp4")
    assert video["availability"] == "unlisted" and video["age_limit"] == 18
    assert video["fps"] == 60 and video["dynamic_range"] == "HDR10"
    assert (video["vcodec"], video["acodec"]) == ("av01", "opus")
    assert video["audio_languages"] == ["en"]
    assert video["comment_count"] == 4321
    assert video["unavailable"] is False and video["unavailable_at"] is None

    assert video["tags"] == ["physics", "waves"] and video["categories"] == ["Education"]
    assert video["chapters"] == [
        {"start": 0, "end": 30, "title": "Intro"},
        {"start": 30, "end": 120, "title": "The main part"},
    ]
    assert video["heatmap"] == [
        {"start": 0, "end": 60, "value": 1.0},
        {"start": 60, "end": 120, "value": 0.25},
    ]
    assert video["sponsor_segments"] == []
    assert video["comments"] is None and video["chat_url"] is None

    listed = archive.client.get("/api/videos").json()["items"][0]
    assert listed["vcodec"] == "av01" and listed["comment_count"] == 4321
    assert "chapters" not in listed and "files" not in listed


def test_published_at_is_a_date_when_youtube_gives_no_exact_time(archive):
    archive.youtube.add(VIDEO, upload_date="20240229")
    assert archived(archive)["published_at"] == "2024-02-29"


def test_files_lists_the_media_and_every_sidecar(archive):
    archive.youtube.add(VIDEO, "Files", subtitles={"en": "English", "de": "German"})
    video = archived(archive, subtitle_languages=["en", "de"])
    folder = video["media_path"].rsplit("/", 1)[0]
    stem = f"{folder}/2025-01-01 Files [{VIDEO}]"
    kinds = {entry["path"]: entry["kind"] for entry in video["files"]}
    assert kinds == {
        f"{stem}.mp4": "media",
        f"{stem}.info.json": "info",
        f"{stem}.jpg": "thumbnail",
        f"{stem}.en.vtt": "subtitles",
        f"{stem}.de.vtt": "subtitles",
    }
    sizes = {entry["path"]: entry["size"] for entry in video["files"]}
    assert all(size == (archive.media / path).stat().st_size for path, size in sizes.items())
    assert video["files"][0]["kind"] == "media"


def test_removing_a_video_forgets_facts_about_the_file_but_not_the_video(archive):
    archive.youtube.add(VIDEO, availability="unlisted", comment_count=7, fps=60)
    video = archived(archive)
    assert archive.client.delete(f"/api/videos/{video['id']}").status_code == 200
    removed = archive.client.get(f"/api/videos/{video['id']}").json()
    assert removed["fps"] is None and removed["vcodec"] is None and removed["audio_languages"] == []
    assert removed["subtitles"] == [] and removed["files"] == []
    assert removed["availability"] == "unlisted" and removed["comment_count"] == 7


def test_gone_videos_say_since_when(archive):
    from app.youtube import Unavailable

    archive.youtube.add(VIDEO)
    archive.youtube.download_failures[VIDEO] = Unavailable("Private video")
    video = add(archive)
    archive.wait_job(video["job_id"], "failed")
    saved = archive.client.get(f"/api/videos/{video['id']}").json()
    assert saved["unavailable"] is True and saved["unavailable_at"].endswith("Z")


def test_rescan_restores_facts_and_subtitle_labels_from_the_sidecar(archive):
    archive.youtube.add(
        VIDEO,
        "Rebuilt",
        timestamp=1735732800,
        availability="unlisted",
        age_limit=13,
        comment_count=99,
        acodec="opus",
        fps=24,
        subtitles={"en": "English"},
        automatic_captions={"es": "Spanish"},
        audio={"en-US": 10, "es": -1},
    )
    before = archived(archive, subtitle_languages=["en", "es"], audio_languages=["es"])
    assert before["audio_languages"] == ["en-US", "es"]

    archive.sql("DELETE FROM videos")
    assert archive.client.get("/api/videos").json()["total"] == 0
    response = archive.client.post("/api/library/rescan")
    archive.wait_job(response.json()["job_id"])

    after = archive.client.get("/api/videos").json()["items"][0]
    for key in (
        "published_at",
        "availability",
        "age_limit",
        "comment_count",
        "fps",
        "vcodec",
        "acodec",
        "audio_languages",
    ):
        assert after[key] == before[key], key
    detail = archive.client.get(f"/api/videos/{after['id']}").json()
    assert [(t["lang"], t["name"], t["source"]) for t in detail["subtitles"]] == [
        ("en", "English", "uploaded"),
        ("es", "Spanish", "translated"),
    ]
    assert detail["subtitles"] == [
        {**track, "url": track["url"].replace(str(before["id"]), str(after["id"]), 1)}
        for track in before["subtitles"]
    ]


def test_other_videos_keep_their_own_facts(archive):
    archive.youtube.add(VIDEO, fps=24, age_limit=0)
    archive.youtube.add(OTHER, fps=60, age_limit=18, channel_id=CHANNEL_ID)
    first, second = archived(archive, VIDEO), archived(archive, OTHER)
    assert (first["fps"], first["age_limit"]) == (24, 0)
    assert (second["fps"], second["age_limit"]) == (60, 18)
