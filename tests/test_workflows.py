"""API integration tests for sessions, queue recovery, discovery and local media."""

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.core.config import settings
from tests.support import MEDIA, SECOND_ID, VIDEO_ID, add_video, subscription, wait_job


@pytest.mark.parametrize(
    "path",
    [
        "/api/videos",
        "/api/channels",
        "/api/subscriptions",
        "/api/downloads",
        "/api/videos/1/file",
        "/api/videos/1/thumbnail",
    ],
)
def test_api_requires_login(environment, path):
    assert environment.client.get(path).status_code == 401


def test_first_run_and_sessions(environment):
    client = environment.client
    assert client.get("/api/auth/status").json()["setup_required"] is True
    assert (
        client.post("/api/auth/setup", json={"username": "owner", "password": "short"}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/auth/setup", json={"username": "owner", "password": "test-password"}
        ).status_code
        == 200
    )
    assert client.get("/api/auth/status").json()["authenticated"] is True
    assert client.get("/api/videos").status_code == 200
    assert (
        client.post(
            "/api/auth/setup", json={"username": "other", "password": "test-password"}
        ).status_code
        == 409
    )
    client.post("/api/auth/logout")
    assert "session_token" not in client.cookies
    assert client.get("/api/videos").status_code == 401
    assert (
        client.post("/api/auth/login", json={"username": "owner", "password": "wrong"}).status_code
        == 401
    )
    login = client.post("/api/auth/login", json={"username": "owner", "password": "test-password"})
    assert login.status_code == 200
    assert "HttpOnly" in login.headers["set-cookie"]
    token = login.json()["token"]
    client.cookies.clear()
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/videos", headers=headers).status_code == 200
    client.post("/api/auth/logout", headers=headers)
    assert client.get("/api/videos", headers=headers).status_code == 401


def test_cookie_mutations_are_same_origin(archive):
    response = archive.client.post(
        "/api/videos",
        headers={"Origin": "https://unrelated.example"},
        json={"youtube_id": VIDEO_ID},
    )
    assert response.status_code == 403
    assert archive.client.get("/api/videos").json()["total"] == 0


def test_json_not_html_for_missing_resources(archive):
    for path in (
        "/api/not-real",
        "/api/videos/999",
        "/storage/private.info.json",
        "/assets/not-real.js",
    ):
        response = archive.client.get(path)
        assert response.status_code == 404
        assert response.headers["content-type"] == "application/json"


@pytest.mark.parametrize(
    "payload",
    [
        {"url": "http://127.0.0.1/private"},
        {"url": "https://www.youtube.com/playlist?list=foo"},
        {"youtube_id": "../secret"},
        {"youtube_id": VIDEO_ID, "quality": "5000p"},
    ],
)
def test_invalid_add_is_rejected_before_network(archive, payload):
    assert archive.client.post("/api/videos", json=payload).status_code == 422
    assert not archive.fake.extract_calls


def test_save_progress_play_remove_and_remember(archive):
    client = archive.client
    video = add_video(archive, quality="2160p")
    job = wait_job(archive)
    assert job["quality"] == "2160p"
    assert job["video_id"] == video["id"]
    saved = client.get(f"/api/videos/{video['id']}").json()
    assert saved["file_path"].endswith("/video.mp4")
    assert saved["file_size"] == len(MEDIA)
    assert saved["quality"] == "720p"  # Actual result, not the requested maximum.
    assert saved["upload_date"].startswith("2025-01-01")
    assert client.get(saved["thumbnail_url"]).content == b"fixture-image"
    file_url = f"/api/videos/{video['id']}/file"
    assert client.get(file_url).content == MEDIA
    partial = client.get(file_url, headers={"Range": "bytes=0-9"})
    assert partial.status_code == 206
    assert partial.content == MEDIA[:10]
    assert client.head(file_url).status_code == 200
    calls = len(archive.fake.extract_calls)
    assert (
        client.post("/api/videos", json={"url": f"https://youtu.be/{VIDEO_ID}?t=1"}).status_code
        == 409
    )
    assert len(archive.fake.extract_calls) == calls  # Up-front deduplication.
    directory = Path(settings.STORAGE_PATH) / saved["file_path"]
    assert client.delete(f"/api/videos/{video['id']}").status_code == 200
    assert not directory.parent.exists()
    assert client.get("/api/videos").json()["total"] == 0
    assert client.get("/api/videos?status=deleted").json()["total"] == 1
    assert client.get(file_url).status_code == 404
    assert client.post("/api/videos", json={"youtube_id": VIDEO_ID}).status_code == 409
    assert client.post(f"/api/videos/{video['id']}/download", json={}).status_code == 200
    wait_job(archive)
    assert client.get(file_url).content == MEDIA


def test_failed_download_can_really_be_retried(archive):
    archive.fake.fail_download = True
    video = add_video(archive)
    job = wait_job(archive, state="failed")
    assert "expired YouTube login" in job["error_message"]
    archive.fake.fail_download = False
    assert archive.client.post(f"/api/downloads/{job['id']}/retry").status_code == 200
    retried = wait_job(archive, job["id"])
    assert retried["error_message"] is None
    assert len(archive.fake.download_calls) == 2
    assert archive.client.get(f"/api/videos/{video['id']}").json()["download_status"] == "completed"
    assert archive.client.post(f"/api/downloads/{job['id']}/retry").status_code == 409


def test_no_output_is_not_reported_as_success(archive):
    archive.fake.write_media = False
    add_video(archive)
    job = wait_job(archive, state="failed")
    assert "without producing a video file" in job["error_message"]


def test_one_job_per_video_even_for_concurrent_enqueue(archive):
    archive.fake.hold_downloads = True
    video = add_video(archive)

    async def enqueue_many():
        return await asyncio.gather(
            *(archive.downloader.queue_download(video["id"]) for _ in range(10))
        )

    ids = archive.client.portal.call(enqueue_many)
    assert len(set(ids)) == 1
    job = wait_job(archive, ids[0], state="downloading")
    assert archive.client.post(f"/api/downloads/{job['id']}/pause").status_code == 409
    assert archive.client.delete(f"/api/downloads/{job['id']}").status_code == 409
    assert archive.client.delete(f"/api/videos/{video['id']}").status_code == 409
    archive.fake.hold_downloads = False
    wait_job(archive)


def test_queued_pause_resume_and_restart_recovery(archive):
    client = archive.client
    client.portal.call(archive.downloader.stop)
    video = add_video(archive)
    job_id = client.portal.call(archive.downloader.queue_download, video["id"])
    assert client.post(f"/api/downloads/{job_id}/pause").status_code == 200
    client.portal.call(archive.downloader.start)
    time.sleep(0.05)
    assert client.get("/api/downloads?status=paused").json()["downloads"][0]["id"] == job_id
    assert client.post(f"/api/downloads/{job_id}/resume").status_code == 200
    wait_job(archive, job_id)
    client.portal.call(archive.downloader.stop)
    # Simulate the persisted state after a process was killed in a different download.
    other = add_video(archive, SECOND_ID)
    interrupted_id = client.portal.call(archive.downloader.queue_download, other["id"])
    client.portal.call(
        archive.db.update, "job_queue", {"status": "downloading"}, "id = ?", (interrupted_id,)
    )
    client.portal.call(
        archive.db.update, "videos", {"download_status": "downloading"}, "id = ?", (other["id"],)
    )
    client.portal.call(archive.downloader.start)
    wait_job(archive, interrupted_id)
    assert client.app.state.scheduler.downloader is archive.downloader


def test_playlist_discovery_is_bounded_and_keeps_uploaders(archive):
    sub = subscription(archive, subtitle_languages=[])
    assert sub["auto_download"] is False
    checked = archive.client.post(f"/api/subscriptions/{sub['id']}/check")
    assert checked.status_code == 202
    job = wait_job(archive, checked.json()["job_id"])
    assert job["result_data"]["videos_added"] == 2
    assert job["result_data"]["videos_queued"] == 0
    videos = archive.client.get("/api/videos").json()["videos"]
    assert len(videos) == 2
    assert len({video["channel_id"] for video in videos}) == 2
    source_calls = [config for url, config in archive.fake.extract_calls if "/watch?" not in url]
    assert all(config["playlistend"] <= 20 for config in source_calls)
    check_again = archive.client.post(f"/api/subscriptions/{sub['id']}/check").json()
    assert wait_job(archive, check_again["job_id"])["result_data"]["videos_added"] == 0
    current = archive.client.get(f"/api/subscriptions/{sub['id']}").json()
    assert current["last_check"] is not None
    assert current["last_job"]["status"] == "completed"
    assert archive.client.get("/api/subscriptions?search=not-found").json()["total"] == 0
    assert archive.client.get("/api/subscriptions?search=Fixture").json()["total"] == 1


def test_subscription_download_preferences_and_deleted_suppression(archive):
    sub = subscription(
        archive,
        auto_download=True,
        quality_preference="1440p",
        download_comments=True,
        subtitle_languages=["fr"],
    )
    job_id = archive.client.post(f"/api/subscriptions/{sub['id']}/check").json()["job_id"]
    wait_job(archive, job_id)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        videos = archive.client.get("/api/videos").json()["videos"]
        if all(video["download_status"] == "completed" for video in videos):
            break
        time.sleep(0.02)
    assert len(archive.fake.download_calls) == 2
    for _, _, options in archive.fake.download_calls:
        assert options["getcomments"] is True
        assert options["subtitleslangs"] == ["fr"]
        assert "1440" in options["format"]
        assert isinstance(options["outtmpl"], dict)
    video_id = videos[0]["id"]
    assert archive.client.delete(f"/api/videos/{video_id}").status_code == 200
    check_again = archive.client.post(f"/api/subscriptions/{sub['id']}/check").json()
    assert wait_job(archive, check_again["job_id"])["result_data"]["videos_queued"] == 0
    assert len(archive.fake.download_calls) == 2


def test_scheduling_validation_and_actual_failure_history(archive):
    sub = subscription(archive, enabled=True)
    wait_job(archive, sub["last_job"]["id"])
    client = archive.client
    assert client.get("/api/subscriptions/scheduler/status").json()["total_jobs"] == 1
    assert client.post(f"/api/subscriptions/{sub['id']}/pause").status_code == 200
    assert client.get("/api/subscriptions/scheduler/status").json()["total_jobs"] == 0
    assert (
        client.put(
            f"/api/subscriptions/{sub['id']}", json={"check_frequency": "90 * * * *"}
        ).status_code
        == 422
    )
    assert (
        client.put(
            f"/api/subscriptions/{sub['id']}", json={"check_frequency": "nonsense"}
        ).status_code
        == 422
    )
    assert client.put(f"/api/subscriptions/{sub['id']}", json={"enabled": None}).status_code == 422
    archive.fake.fail_source = True
    check = client.post(f"/api/subscriptions/{sub['id']}/check").json()
    failed = wait_job(archive, check["job_id"], state="failed")
    assert "unavailable" in failed["error_message"]
    events = client.portal.call(
        archive.db.execute, "SELECT * FROM scheduler_events ORDER BY id DESC"
    )
    assert events[0]["event_type"] == "check_failed"
    assert events[0]["status"] == "failed"
    assert client.post(f"/api/subscriptions/{sub['id']}/resume").status_code == 200
    assert client.delete(f"/api/subscriptions/{sub['id']}").status_code == 200
    assert client.get("/api/videos").json()["total"] == 2  # Unsubscribe preserves media metadata.


def test_confined_media_paths_and_legacy_directory_path(archive):
    video = add_video(archive)
    wait_job(archive)
    saved = archive.client.get(f"/api/videos/{video['id']}").json()
    parent = str(Path(saved["file_path"]).parent)
    archive.client.portal.call(
        archive.db.update, "videos", {"file_path": parent}, "id = ?", (video["id"],)
    )
    assert archive.client.get(f"/api/videos/{video['id']}/file").content == MEDIA
    outside = archive.root / "secret.mp4"
    outside.write_bytes(b"secret")
    archive.client.portal.call(
        archive.db.update, "videos", {"file_path": "../secret.mp4"}, "id = ?", (video["id"],)
    )
    assert archive.client.get(f"/api/videos/{video['id']}/file").status_code == 404
    assert archive.client.delete(f"/api/videos/{video['id']}").status_code == 409
    assert outside.read_bytes() == b"secret"


def test_real_ytdlp_adapter_does_not_block_api_or_replace_output_templates(archive, monkeypatch):
    """Exercise the actual threaded adapter, replacing only yt-dlp's network calls."""
    from app.core import downloader, ytdlp_service

    entered, release = threading.Event(), threading.Event()
    configs = []

    class LocalYoutubeDL:
        def __init__(self, config):
            self.config = config
            configs.append(config)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def sanitize_info(self, info):
            return info

        def extract_info(self, url, download=False):
            entered.set()
            assert release.wait(3)
            return archive.fake.video_info(VIDEO_ID)

        def download(self, urls):
            directory = Path(self.config["outtmpl"]["default"]).parent
            (directory / "video.mp4").write_bytes(MEDIA)
            (directory / "video.info.json").write_text(
                json.dumps(archive.fake.video_info(VIDEO_ID))
            )
            return 0

    monkeypatch.setattr(ytdlp_service.yt_dlp, "YoutubeDL", LocalYoutubeDL)
    monkeypatch.setattr(settings, "YTDLP_MIN_REQUEST_INTERVAL", 0)
    service = ytdlp_service.YTDLPService()
    monkeypatch.setattr(downloader, "get_ytdlp_service", lambda: service)
    with ThreadPoolExecutor(max_workers=2) as executor:
        added = executor.submit(archive.client.post, "/api/videos", json={"youtube_id": VIDEO_ID})
        try:
            assert entered.wait(2)
            health = executor.submit(archive.client.get, "/api/health")
            assert health.result(timeout=1).status_code == 200
        finally:
            release.set()
        assert added.result(timeout=3).status_code == 201
    job = wait_job(archive)
    assert job["status"] == "completed"
    download_config = next(config for config in configs if "outtmpl" in config)
    assert isinstance(download_config["outtmpl"], dict)
    assert download_config["outtmpl"]["default"].endswith("video.%(ext)s")
