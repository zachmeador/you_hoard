"""The persistent queue: retries, cancellation, pausing and restart recovery."""

import asyncio

from app.youtube import Unavailable, YouTubeError
from tests.test_library import OTHER, VIDEO, add

QUEUED = ("queue000001", "queue000002", "queue000003", "queue000004")
LATER = "2099-01-01T00:00:00Z"
SOONER = "2098-01-01T00:00:00Z"


def hold_queue(archive, queued=3):
    """A download held while it runs, with more queued behind it. Returns their videos."""
    archive.youtube.hold.set()
    archive.client.put("/api/settings", json={"max_concurrent_downloads": 1})
    videos = []
    for youtube_id in (VIDEO, *QUEUED[:queued]):
        archive.youtube.add(youtube_id)
        videos.append(add(archive, youtube_id))
    archive.wait_job(videos[0]["job_id"], "running")
    return videos


def test_transient_failures_back_off_then_fail(archive):
    archive.youtube.add(VIDEO)
    archive.youtube.download_failures[VIDEO] = YouTubeError("HTTP Error 503: Service Unavailable")
    video = add(archive)
    for attempt in range(1, 4):
        job = archive.wait(
            lambda attempt=attempt: (
                (job := archive.job(video["job_id"]))["attempts"] == attempt
                and job["status"] == "queued"
                and job
            )
        )
        assert job["run_after"] and "503" in job["error"]
        archive.sql("UPDATE jobs SET run_after = NULL")
        archive.app.state.runner.wake()
    failed = archive.wait_job(video["job_id"], "failed")
    assert failed["attempts"] == 4

    del archive.youtube.download_failures[VIDEO]
    assert archive.client.post(f"/api/jobs/{failed['id']}/retry").status_code == 200
    archive.wait_job(failed["id"])
    assert archive.client.post(f"/api/jobs/{failed['id']}/retry").status_code == 409


def test_gone_videos_fail_at_once_and_are_flagged(archive):
    archive.youtube.add(VIDEO)
    archive.youtube.download_failures[VIDEO] = Unavailable("Private video")
    video = add(archive)
    job = archive.wait_job(video["job_id"], "failed")
    assert job["attempts"] == 1 and job["error"] == "Private video"
    saved = archive.client.get(f"/api/videos/{video['id']}").json()
    assert saved["status"] == "failed" and saved["unavailable"] is True
    assert saved["error"] == "Private video"


def test_running_downloads_can_be_cancelled(archive):
    archive.youtube.add(VIDEO)
    archive.youtube.hold.set()
    video = add(archive)
    running = archive.wait_job(video["job_id"], "running")
    assert running["progress"]["percent"] == 10.0
    workdir = archive.media / ".youhoard" / "incomplete" / VIDEO
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "media.mp4.part").write_bytes(b"partial")
    assert archive.client.post(f"/api/jobs/{running['id']}/cancel").status_code == 200
    archive.wait_job(running["id"], "cancelled")
    assert not workdir.exists()
    assert archive.client.get(f"/api/videos/{video['id']}").json()["status"] == "missing"
    assert archive.client.post(f"/api/jobs/{running['id']}/cancel").status_code == 409


def test_pause_resume_and_one_active_job_per_video(archive):
    archive.youtube.add(VIDEO)
    archive.youtube.add(OTHER)
    archive.youtube.hold.set()
    archive.client.put("/api/settings", json={"max_concurrent_downloads": 1})
    first, second = add(archive, VIDEO), add(archive, OTHER)
    archive.wait_job(first["job_id"], "running")
    assert archive.client.post(f"/api/jobs/{second['job_id']}/pause").status_code == 200
    again = archive.client.post(f"/api/videos/{second['id']}/download", json={})
    assert again.json()["job_id"] == second["job_id"]

    async def enqueue_many():
        runner = archive.app.state.runner
        return await asyncio.gather(
            *(runner.enqueue("download", video_id=second["id"]) for _ in range(10))
        )

    assert set(archive.call(enqueue_many)) == {second["job_id"]}
    archive.youtube.hold.clear()
    archive.wait_job(first["job_id"])
    assert archive.job(second["job_id"])["status"] == "paused"
    assert archive.client.post(f"/api/jobs/{second['job_id']}/resume").status_code == 200
    archive.wait_job(second["job_id"])

    counts = archive.client.get("/api/jobs").json()["counts"]
    assert counts["completed"] == 2
    assert archive.client.post("/api/jobs/clear").json() == {"cleared": 2}


def test_bulk_pause_and_resume_skip_jobs_in_the_wrong_state(archive):
    videos = hold_queue(archive)
    ids = [video["job_id"] for video in videos]
    running, waiting, second, third = ids
    archive.sql("UPDATE jobs SET run_after = ? WHERE id = ?", (LATER, waiting))

    def states():
        by_id = {job["id"]: job["status"] for job in archive.jobs()}
        return [by_id[job_id] for job_id in ids]

    def post(action, *job_ids):
        response = archive.client.post(f"/api/jobs/{action}", json={"ids": list(job_ids)})
        assert response.status_code == 200, response.text
        return response.json()

    assert states() == ["running", "queued", "queued", "queued"]
    assert post("pause", running, waiting, second, 9999) == {"paused": 2}
    assert states() == ["running", "paused", "paused", "queued"]
    assert archive.job(waiting)["run_after"] == LATER
    assert post("pause", waiting, second) == {"paused": 0}

    archive.sql("UPDATE videos SET media_path = 'x.mp4' WHERE id = ?", (videos[1]["id"],))
    assert post("resume", running, waiting, second, third, 9999) == {"resumed": 1}
    assert states() == ["running", "paused", "queued", "queued"]
    assert archive.client.post(f"/api/jobs/{waiting}/resume").status_code == 409

    archive.youtube.hold.clear()
    for job_id in (running, second, third):
        archive.wait_job(job_id)
    assert states() == ["completed", "paused", "completed", "completed"]

    for action in ("pause", "resume"):
        assert archive.client.post(f"/api/jobs/{action}", json={"ids": []}).status_code == 422


def test_job_ids_list_the_selection_in_the_lists_order(archive):
    videos = hold_queue(archive, queued=4)
    running, waiting, paused, urgent, sooner = (video["job_id"] for video in videos)
    archive.sql("UPDATE jobs SET run_after = ? WHERE id = ?", (LATER, waiting))
    archive.sql("UPDATE jobs SET run_after = ? WHERE id = ?", (SOONER, sooner))
    archive.sql("UPDATE jobs SET priority = 20 WHERE id = ?", (urgent,))
    archive.client.post("/api/jobs/pause", json={"ids": [paused]})

    def ids(**params):
        response = archive.client.get("/api/jobs/ids", params=params)
        assert response.status_code == 200, response.text
        return response.json()["ids"]

    assert ids() == [running, urgent, waiting, sooner, paused]
    assert ids(status="queued") == [urgent]
    assert ids(status="waiting") == [sooner, waiting]
    assert ids(status=["waiting", "queued"]) == [urgent, waiting, sooner]
    assert ids(status=["paused", "running"]) == [running, paused]
    assert ids(kind="check") == []
    for params in ({"status": "waiting"}, {"status": ["paused", "queued"]}, {"kind": "download"}):
        assert ids(**params) == [job["id"] for job in archive.jobs(**params)]
    assert archive.client.get("/api/jobs/ids", params={"status": "nope"}).status_code == 422


def test_interrupted_jobs_resume_after_restart(archive):
    archive.youtube.add(VIDEO)
    runner = archive.app.state.runner
    archive.call(runner.stop)
    video = add(archive)
    archive.sql("UPDATE jobs SET status = 'running', attempts = 1 WHERE id = ?", (video["job_id"],))
    archive.call(runner.start)
    job = archive.wait_job(video["job_id"])
    assert job["attempts"] == 1


def test_settings_round_trip_and_system_status(archive):
    settings = archive.client.get("/api/settings").json()
    assert settings["default_quality"] == "1080p" and "2160p" in settings["options"]["qualities"]
    updated = archive.client.put(
        "/api/settings", json={"default_quality": "best", "subtitle_languages": ["en", " de "]}
    ).json()
    assert updated["default_quality"] == "best" and updated["subtitle_languages"] == ["en", "de"]
    assert (
        archive.client.put("/api/settings", json={"max_concurrent_downloads": 50}).status_code
        == 422
    )
    system = archive.client.get("/api/system").json()
    assert system["js_runtime"] == "deno 0.0" and system["library"]["videos"] == 0
