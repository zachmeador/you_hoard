"""Session expiry and recovery of persisted queue state."""

from tests.support import TestEnvironment, add_video, wait_job


def test_expired_legacy_session_is_removed(archive: TestEnvironment) -> None:
    client = archive.client
    token = client.cookies["session_token"]
    client.portal.call(
        archive.db.update, "sessions", {"expires_at": "2000-01-01T00:00:00"}, "token = ?", (token,)
    )
    assert client.get("/api/videos").status_code == 401
    assert (
        client.portal.call(
            archive.db.execute_one, "SELECT * FROM sessions WHERE token = ?", (token,)
        )
        is None
    )
    assert client.get("/api/auth/status").json() == {
        "authenticated": False,
        "username": None,
        "setup_required": False,
    }


def test_startup_deduplicates_legacy_queue_entries(archive: TestEnvironment) -> None:
    client = archive.client
    client.portal.call(archive.downloader.stop)
    video = add_video(archive)
    duplicate_id = client.portal.call(
        archive.db.insert,
        "job_queue",
        {
            "job_type": "download",
            "video_id": video["id"],
            "status": "queued",
        },
    )
    client.portal.call(archive.downloader.start)
    duplicate = wait_job(archive, duplicate_id, state="failed")
    assert "Superseded" in duplicate["error_message"]
    jobs = client.get("/api/downloads").json()["downloads"]
    original_id = next(job["id"] for job in jobs if job["id"] != duplicate_id)
    wait_job(archive, original_id)
    assert len(archive.fake.download_calls) == 1
