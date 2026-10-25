"""Adding, archiving, playing and removing individual videos."""

import json

import pytest

from tests.fake_youtube import CHANNEL_ID, MEDIA

VIDEO = "dQw4w9WgXcQ"
OTHER = "AK47SC6kr_A"


def add(archive, youtube_id=VIDEO, **body):
    response = archive.client.post(
        "/api/videos", json={"url": f"https://www.youtube.com/watch?v={youtube_id}", **body}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_add_archives_into_readable_layout_with_sidecars(archive):
    archive.youtube.add(VIDEO, "Never: Gonna/Give You Up", extra={"tags": ["music"]})
    video = add(archive, quality="2160p")
    assert video["status"] in ("queued", "downloading")
    assert video["channel"]["youtube_id"] == CHANNEL_ID
    archive.wait_job(video["job_id"])

    saved = archive.client.get(f"/api/videos/{video['id']}").json()
    assert saved["status"] == "archived"
    assert saved["quality"] == "1080p"  # the actual file, not the requested cap
    assert saved["media_path"] == (
        f"Fixture Channel [{CHANNEL_ID}]/2025-01-01 Never： Gonna⧸Give You Up [{VIDEO}].mp4"
    )
    media = archive.media / saved["media_path"]
    assert media.read_bytes() == MEDIA
    base = media.with_suffix("")
    assert base.with_name(base.name + ".jpg").exists()
    info = json.loads(base.with_name(base.name + ".info.json").read_text())
    assert info["title"] == "Never: Gonna/Give You Up" and info["tags"] == ["music"]
    assert "formats" not in info  # signed URLs that expire are not kept
    assert "subtitles" not in info and "automatic_captions" not in info
    assert saved["subtitles"] == [
        {
            "lang": "en",
            "name": "English",
            "source": "uploaded",
            "url": f"/api/videos/{video['id']}/subtitles/en",
        }
    ]
    assert not (archive.media / ".youhoard" / "incomplete" / VIDEO).exists()

    request = archive.youtube.calls[-1][1]
    assert request.quality == "2160p" and request.subtitle_languages == ["en"]

    client = archive.client
    assert client.get(saved["media_url"]).content == MEDIA
    partial = client.get(saved["media_url"], headers={"Range": "bytes=0-9"})
    assert partial.status_code == 206 and partial.content == MEDIA[:10]
    assert client.get(saved["thumbnail_url"]).content == b"jpeg-fixture"
    assert client.get(saved["subtitles"][0]["url"]).text.startswith("WEBVTT")


def test_duplicates_are_refused_before_asking_youtube(archive):
    archive.youtube.add(VIDEO)
    archive.wait_job(add(archive)["job_id"])
    calls = len(archive.youtube.calls)
    response = archive.client.post("/api/videos", json={"url": f"https://youtu.be/{VIDEO}?t=3"})
    assert response.status_code == 409
    assert "Already archived" in response.json()["detail"]
    assert len(archive.youtube.calls) == calls


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/playlist?list=PLabc",
        "https://www.youtube.com/@channel",
        "../../etc/passwd",
    ],
)
def test_non_video_urls_are_rejected(archive, url):
    assert archive.client.post("/api/videos", json={"url": url}).status_code == 422
    assert not archive.youtube.calls


def test_remove_keeps_a_tombstone_and_explicit_download_restores(archive):
    archive.youtube.add(VIDEO)
    video = add(archive)
    archive.wait_job(video["job_id"])
    saved = archive.client.get(f"/api/videos/{video['id']}").json()
    folder = (archive.media / saved["media_path"]).parent

    assert archive.client.delete(f"/api/videos/{video['id']}").status_code == 200
    assert not folder.exists()  # the emptied channel folder goes too
    removed = archive.client.get(f"/api/videos/{video['id']}").json()
    assert removed["status"] == "deleted" and removed["media_path"] is None
    assert archive.client.get("/api/videos").json()["total"] == 0
    assert archive.client.get("/api/videos", params={"status": "deleted"}).json()["total"] == 1
    assert archive.client.get(saved["media_url"]).status_code == 404

    job = archive.client.post(f"/api/videos/{video['id']}/download", json={}).json()
    archive.wait_job(job["job_id"])
    assert archive.client.get(f"/api/videos/{video['id']}").json()["status"] == "archived"


def test_active_downloads_cannot_be_removed(archive):
    archive.youtube.add(VIDEO)
    archive.youtube.hold.set()
    video = add(archive)
    archive.wait_job(video["job_id"], "running")
    assert archive.client.delete(f"/api/videos/{video['id']}").status_code == 409
    archive.youtube.hold.clear()
    archive.wait_job(video["job_id"])


def test_stored_paths_never_escape_the_media_folder(archive, tmp_path):
    archive.youtube.add(VIDEO)
    video = add(archive)
    archive.wait_job(video["job_id"])
    secret = tmp_path / "secret.mp4"
    secret.write_bytes(b"secret")
    for path in ("../secret.mp4", f"../{VIDEO}.mp4", "Fixture Channel [x]"):
        archive.sql("UPDATE videos SET media_path = ? WHERE id = ?", (path, video["id"]))
        assert archive.client.get(f"/api/videos/{video['id']}/media").status_code == 404
        assert archive.client.delete(f"/api/videos/{video['id']}").status_code == 409
        archive.sql("UPDATE videos SET deleted_at = NULL WHERE id = ?", (video["id"],))
    assert secret.read_bytes() == b"secret"


def test_filters_sorting_and_watched(archive):
    archive.youtube.add(VIDEO, "Alpha", upload_date="20240101")
    archive.youtube.add(OTHER, "Beta", upload_date="20250101", width=1080, height=1920, duration=30)
    first, second = add(archive, VIDEO), add(archive, OTHER)
    archive.wait_job(first["job_id"])
    archive.wait_job(second["job_id"])
    client = archive.client

    def titles(**params):
        return [
            video["title"] for video in client.get("/api/videos", params=params).json()["items"]
        ]

    assert titles() == ["Beta", "Alpha"]
    assert titles(sort="title", order="asc") == ["Alpha", "Beta"]
    assert titles(q="alp") == ["Alpha"]
    assert titles(video_type="short") == ["Beta"]
    shorts = client.get(f"/api/videos/{second['id']}").json()
    assert shorts["quality"] == "1080p"  # vertical video: the short side
    watched = client.post(f"/api/videos/{first['id']}/watched", json={"watched": True}).json()
    assert watched["watched_at"]
    assert titles(watched="true") == ["Alpha"]
    assert titles(watched="false") == ["Beta"]


def test_upcoming_videos_wait_instead_of_failing(archive):
    archive.youtube.add(VIDEO, live_status="is_upcoming")
    video = add(archive)
    job = archive.wait(
        lambda: (
            (job := archive.job(video["job_id"]))["run_after"] and job["status"] == "queued" and job
        )
    )
    assert job["attempts"] == 0
    assert "Not available" in job["error"]
    assert archive.client.get(f"/api/videos/{video['id']}").json()["status"] == "queued"
