"""A bot check pauses all YouTube work, and downloads rest between one another."""

import time

from app import jobs
from app.youtube import Blocked
from tests.test_library import add
from tests.test_subscriptions import subscribe

BOT = "Sign in to confirm you're not a bot"
IDS = ["botcheck001", "botcheck002", "botcheck003"]


def one_at_a_time(archive) -> None:
    response = archive.client.put("/api/settings", json={"max_concurrent_downloads": 1})
    assert response.status_code == 200, response.text


def downloads(archive) -> list[str]:
    return [call[1].youtube_id for call in archive.youtube.calls if call[0] == "download"]


def queue_blocked(archive) -> list[dict]:
    """Queue three videos; the first one meets a bot check."""
    one_at_a_time(archive)
    for youtube_id in IDS:
        archive.youtube.add(youtube_id)
    archive.youtube.download_failures[IDS[0]] = Blocked(BOT)
    videos = [add(archive, youtube_id) for youtube_id in IDS]
    archive.wait(lambda: archive.app.state.runner.youtube_paused)
    return videos


def paused_for(runner) -> float:
    return runner.youtube_paused_until - time.time()


def test_a_bot_check_pauses_every_download_instead_of_each_trying(archive):
    videos = queue_blocked(archive)
    runner = archive.app.state.runner
    time.sleep(0.2)  # time enough for the worker to have moved on to the next job
    assert downloads(archive) == [IDS[0]]

    resumes = archive.client.get("/api/jobs").json()["youtube_paused_until"]
    assert resumes and archive.client.get("/api/system").json()["youtube_paused_until"] == resumes
    assert 3590 < paused_for(runner) <= 3600
    for video in videos:
        job = archive.job(video["job_id"])
        assert job["status"] == "queued" and job["run_after"] == resumes
    assert archive.job(videos[0]["job_id"])["attempts"] == 0  # the block isn't the job's fault

    archive.youtube.download_failures.clear()
    assert archive.client.post("/api/jobs/resume-youtube").status_code == 200
    for video in videos:
        archive.wait_job(video["job_id"])
    assert archive.client.get("/api/jobs").json()["youtube_paused_until"] is None


def test_pauses_grow_while_youtube_keeps_refusing_and_reset_after_a_success(archive):
    queue_blocked(archive)
    runner = archive.app.state.runner
    archive.client.post("/api/jobs/resume-youtube")
    archive.wait(lambda: runner.youtube_paused)  # the first video meets the check again
    assert 7190 < paused_for(runner) <= 7200

    archive.youtube.download_failures.clear()
    archive.client.post("/api/jobs/resume-youtube")
    archive.wait_idle()
    archive.youtube.add("botcheck004")
    archive.youtube.download_failures["botcheck004"] = Blocked(BOT)
    add(archive, "botcheck004")
    archive.wait(lambda: runner.youtube_paused)
    assert 3590 < paused_for(runner) <= 3600  # back to an hour


def test_checks_wait_out_a_pause_but_scans_still_run(archive):
    sub = subscribe(archive)
    runner = archive.app.state.runner
    runner.youtube_paused_until = time.time() + 600
    check = archive.client.post(f"/api/subscriptions/{sub['id']}/check").json()
    scan = archive.client.post("/api/library/rescan").json()
    archive.wait_job(scan["job_id"])
    job = archive.job(check["job_id"])
    assert job["status"] == "queued" and job["run_after"]
    assert archive.call(runner.queue_due_checks) == 0


def test_downloads_rest_between_one_another(archive, monkeypatch):
    monkeypatch.setattr(jobs, "DOWNLOAD_REST", (1.0, 1.0))
    one_at_a_time(archive)
    for youtube_id in IDS[:2]:
        archive.youtube.add(youtube_id)
    first, second = (add(archive, youtube_id) for youtube_id in IDS[:2])
    archive.wait_job(first["job_id"])
    assert archive.job(second["job_id"])["status"] == "queued"  # the worker is resting
    archive.wait_job(second["job_id"])
