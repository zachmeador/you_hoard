"""What happens is recorded: who did it, which job and video it touched, and why."""

import argparse
import logging
import sqlite3

from fastapi.testclient import TestClient

from app import pace, trash
from app.__main__ import rescan
from app.config import config
from app.youtube import Blocked, Unavailable, YouTubeError
from main import create_app
from tests.fake_youtube import FakeYouTube
from tests.test_bot_checks import (
    BOT,
    IDS,
    RATE_LIMIT,
    pause,
    queue_stopped,
    refuse,
    resume,
)
from tests.test_job_moves import make_job
from tests.test_library import OTHER, VIDEO, add
from tests.test_subscriptions import ids, seed_tab, subscribe


def recorded(archive, **params) -> list[tuple[str, str]]:
    """The (event, actor) pairs that match, oldest first."""
    return [(event["event"], event["actor"]) for event in reversed(archive.events(**params))]


def latest(archive, name: str, **params) -> dict:
    return next(event for event in archive.events(**params) if event["event"] == name)


def test_a_download_is_recorded_from_request_to_completion(archive):
    archive.youtube.add(VIDEO, "Recorded")
    video = add(archive)
    archive.wait_job(video["job_id"])
    assert recorded(archive, job_id=video["job_id"]) == [
        ("job.queued", "owner"),
        ("job.started", "app"),
        ("job.completed", "app"),
    ]
    queued, started, completed = reversed(archive.events(job_id=video["job_id"]))
    assert queued["detail"] == "origin user" and queued["job_kind"] == "download"
    assert queued["video"] == {"id": video["id"], "title": "Recorded"}
    assert started["reason"] is None and completed["detail"] == "1080p"
    assert recorded(archive, video_id=video["id"]) == recorded(archive, job_id=video["job_id"])


def test_what_the_owner_does_to_jobs_is_recorded_as_the_owners(stopped):
    job_id = make_job(stopped, "queued")
    post = stopped.client.post
    assert post(f"/api/jobs/{job_id}/pause").status_code == 200
    assert post(f"/api/jobs/{job_id}/resume").status_code == 200
    assert post("/api/jobs/pause", json={"ids": [job_id]}).json() == {"paused": 1}
    assert post("/api/jobs/resume", json={"ids": [job_id]}).json() == {"resumed": 1}
    assert post(f"/api/jobs/{job_id}/run-now").status_code == 200
    assert post(f"/api/jobs/{job_id}/cancel").status_code == 200
    assert post(f"/api/jobs/{job_id}/retry").status_code == 200
    assert post(f"/api/jobs/{job_id}/cancel").status_code == 200
    stopped.sql("UPDATE jobs SET status = 'failed', reason = 'error' WHERE id = ?", (job_id,))
    assert post("/api/jobs/retry-failed").json() == {"retried": 1}
    assert post(f"/api/jobs/{job_id}/cancel").status_code == 200
    assert stopped.client.delete(f"/api/jobs/{job_id}").status_code == 200

    names = [
        "job.queued",
        "job.paused",
        "job.resumed",
        "job.paused",
        "job.resumed",
        "job.run_now",
        "job.cancelled",
        "job.retried",
        "job.cancelled",
        "job.retried",
        "job.cancelled",
        "job.removed",
    ]
    assert recorded(stopped, job_id=job_id) == [(name, "owner") for name in names]
    paused = [event for event in stopped.events(job_id=job_id) if event["event"] == "job.paused"]
    assert [event["reason"] for event in paused] == ["asked", "asked"]


def test_clearing_finished_jobs_is_recorded_and_erases_nothing(archive):
    for youtube_id in (VIDEO, OTHER):
        archive.youtube.add(youtube_id)
    done = [add(archive, youtube_id)["job_id"] for youtube_id in (VIDEO, OTHER)]
    for job_id in done:
        archive.wait_job(job_id)
    before = {job_id: recorded(archive, job_id=job_id) for job_id in done}
    system = archive.client.get("/api/system").json()["activity"]

    assert archive.client.post("/api/jobs/clear").json() == {"cleared": 2}
    assert archive.jobs() == []
    for job_id in done:
        assert recorded(archive, job_id=job_id) == before[job_id]
    cleared = latest(archive, "jobs.cleared")
    assert (cleared["actor"], cleared["detail"], cleared["job_id"]) == ("owner", "2 jobs", None)
    assert archive.client.get("/api/system").json()["activity"] == system
    assert archive.client.post("/api/jobs/clear").json() == {"cleared": 0}
    assert [e["event"] for e in archive.events() if e["event"] == "jobs.cleared"] == [
        "jobs.cleared"
    ]


def test_removing_one_job_leaves_its_history(archive):
    archive.youtube.add(VIDEO)
    job_id = add(archive)["job_id"]
    archive.wait_job(job_id)
    assert archive.client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert archive.jobs() == []
    assert recorded(archive, job_id=job_id)[-1] == ("job.removed", "owner")
    assert ("job.completed", "app") in recorded(archive, job_id=job_id)


def test_job_ids_are_never_handed_out_twice(archive):
    archive.youtube.add(VIDEO)
    first = add(archive)["job_id"]
    archive.wait_job(first)
    archive.client.post("/api/jobs/clear")
    archive.youtube.add(OTHER)
    second = add(archive, OTHER)["job_id"]
    archive.wait_job(second)
    # A cleared job's id would otherwise be reused, and its events would become the new job's.
    assert second > first
    assert recorded(archive, job_id=second)[0] == ("job.queued", "owner")


def test_the_app_records_what_it_does_to_a_job_on_its_own(archive):
    gone, flaky, premiere = IDS
    archive.youtube.add(gone)
    archive.youtube.add(flaky)
    archive.youtube.add(premiere, live_status="is_upcoming")
    archive.youtube.download_failures[gone] = Unavailable("Private video")
    archive.youtube.download_failures[flaky] = YouTubeError("HTTP Error 503: Service Unavailable")
    jobs = {youtube_id: add(archive, youtube_id)["job_id"] for youtube_id in IDS}
    archive.wait_job(jobs[gone], "failed")
    archive.wait(lambda: archive.job(jobs[flaky])["state"] == "waiting")
    archive.wait(lambda: archive.job(jobs[premiere])["state"] == "waiting")

    failed = latest(archive, "job.failed", job_id=jobs[gone])
    assert (failed["actor"], failed["reason"], failed["detail"]) == ("app", "gone", "Private video")
    retrying = latest(archive, "job.retrying", job_id=jobs[flaky])
    assert (retrying["actor"], retrying["reason"]) == ("app", "retry")
    assert retrying["detail"] == "Retrying in 15 minutes: HTTP Error 503: Service Unavailable"
    deferred = latest(archive, "job.deferred", job_id=jobs[premiere])
    assert (deferred["actor"], deferred["reason"]) == ("app", "premiere")
    assert "Not available for download yet" in deferred["detail"]


def test_a_refusal_is_recorded_for_the_job_and_for_youtube(archive):
    archive.youtube.add(VIDEO)
    archive.youtube.download_failures[VIDEO] = Blocked(BOT)
    job_id = add(archive)["job_id"]
    archive.wait(lambda: archive.gate.paused)
    archive.wait(lambda: any(e["event"] == "job.refused" for e in archive.events()))

    refused = latest(archive, "job.refused")
    assert (refused["actor"], refused["reason"], refused["detail"]) == ("app", "refused", BOT)
    assert refused["job_id"] == job_id
    paused = latest(archive, "youtube.refused")
    assert (paused["actor"], paused["job_id"]) == ("app", None)
    assert BOT in paused["detail"] and "waits 60 minutes" in paused["detail"]
    assert paused["detail"].startswith("YouTube refused a request;")


def test_pausing_and_resuming_youtube_are_the_owners(archive):
    pause(archive, hours=2)
    resume(archive)
    assert [(e["event"], e["actor"]) for e in archive.events(group="youtube")] == [
        ("youtube.resumed", "owner"),
        ("youtube.paused", "owner"),
    ]
    paused = archive.events(group="youtube")[1]
    assert paused["detail"] == "Paused on request; all YouTube work waits 120 minutes"
    # Nothing changed, so nothing is recorded.
    resume(archive)
    pause(archive, hours=2)
    pause(archive, hours=1)
    assert len(archive.events(group="youtube")) == 3


def test_a_refused_extra_and_a_run_of_failures_are_recorded_as_the_apps(archive):
    kept = IDS[0]
    archive.youtube.add(kept, refused_extras=RATE_LIMIT)
    archive.wait_job(add(archive, kept)["job_id"])
    refused = latest(archive, "youtube.extras_refused")
    assert (refused["actor"], refused["job_id"]) == ("app", None)
    assert RATE_LIMIT in refused["detail"] and "waits 60 minutes" in refused["detail"]
    resume(archive)

    failing = [f"failure{n:04d}" for n in range(pace.FAILURE_STREAK)]
    for youtube_id in failing:
        archive.youtube.add(youtube_id)
        archive.youtube.download_failures[youtube_id] = YouTubeError("HTTP Error 503: Unavailable")
    queue_stopped(archive, failing)
    archive.wait(lambda: any(e["event"] == "youtube.failures" for e in archive.events()))
    streak = latest(archive, "youtube.failures")
    assert streak["actor"] == "app" and "5 downloads in a row failed" in streak["detail"]
    assert archive.client.get("/api/jobs").json()["youtube_pause_cause"] == "failures"


def test_jobs_a_restart_brings_back_are_returned_and_say_so(archive):
    archive.youtube.add(VIDEO)
    runner = archive.app.state.runner
    archive.call(runner.stop)
    job_id = add(archive)["job_id"]
    archive.sql("UPDATE jobs SET status = 'running', attempts = 1 WHERE id = ?", (job_id,))
    archive.call(runner.start)
    archive.wait_job(job_id)
    returned = latest(archive, "job.returned", job_id=job_id)
    assert (returned["actor"], returned["detail"]) == ("app", "restart")


def test_a_stop_returns_running_jobs_without_using_an_attempt(archive):
    archive.youtube.add(VIDEO)
    archive.youtube.hold.set()
    job_id = add(archive)["job_id"]
    archive.wait_job(job_id, "running")
    runner = archive.app.state.runner
    archive.call(runner.stop)
    job = archive.job(job_id)
    assert (job["status"], job["attempts"]) == ("queued", 0)
    assert latest(archive, "job.returned", job_id=job_id)["detail"] == "shutting down"
    archive.youtube.hold.clear()
    archive.call(runner.start)
    archive.wait_job(job_id)


def test_cancelling_a_running_job_is_the_owners_doing(archive):
    archive.youtube.add(VIDEO)
    archive.youtube.hold.set()
    job_id = add(archive)["job_id"]
    archive.wait_job(job_id, "running")
    assert archive.client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
    archive.wait_job(job_id, "cancelled")
    assert recorded(archive, job_id=job_id)[-1] == ("job.cancelled", "owner")


def test_switching_a_subscription_off_and_on_is_recorded_with_how_many_moved(archive):
    seed_tab(archive, "video", ids("vid", 3))
    sub = subscribe(archive)
    archive.call(archive.app.state.runner.stop)
    path = f"/api/subscriptions/{sub['id']}"
    assert archive.client.patch(path, json={"download_policy": "all"}).status_code == 200
    assert archive.client.patch(path, json={"enabled": False}).status_code == 200
    assert archive.client.patch(path, json={"enabled": True}).status_code == 200

    off = latest(archive, "subscription.off")
    on = latest(archive, "subscription.on")
    assert (off["actor"], off["detail"], off["subscription"]["id"]) == (
        "owner",
        "3 downloads paused",
        sub["id"],
    )
    assert (on["actor"], on["detail"]) == ("owner", "3 downloads resumed")
    # The jobs it moved are in the subscription's history too, each one the owner's doing.
    moved = [e for e in archive.events(subscription_id=sub["id"]) if e["event"] == "job.paused"]
    assert len(moved) == 3 and {e["reason"] for e in moved} == {"subscription_off"}
    assert {e["actor"] for e in moved} == {"owner"}


def test_a_check_queueing_downloads_is_the_apps_doing(archive):
    seed_tab(archive, "video", ids("old", 1))
    sub = subscribe(archive)
    seed_tab(archive, "video", ids("new", 1) + ids("old", 1))
    archive.client.post(f"/api/subscriptions/{sub['id']}/check")
    archive.wait_idle()
    queued = [
        e for e in archive.events() if e["event"] == "job.queued" and e["job_kind"] == "download"
    ]
    assert [(e["actor"], e["detail"]) for e in queued] == [("app", "origin policy")]
    assert queued[0]["subscription"]["id"] == sub["id"]


def test_a_deleted_subscription_stays_in_the_record_by_its_id(archive):
    seed_tab(archive, "video", ids("vid", 1))
    sub = subscribe(archive)
    archive.client.patch(f"/api/subscriptions/{sub['id']}", json={"enabled": False})
    assert archive.client.delete(f"/api/subscriptions/{sub['id']}").status_code == 200
    off = latest(archive, "subscription.off")
    assert off["subscription"] == {"id": sub["id"], "title": None}


def test_deleting_expired_trash_is_recorded(archive, monkeypatch):
    runner = archive.app.state.runner
    monkeypatch.setattr(trash, "purge", lambda: 0)
    archive.call(runner.purge_trash)
    assert not [e for e in archive.events() if e["event"] == "trash.purged"]
    monkeypatch.setattr(trash, "purge", lambda: 2)
    archive.call(runner.purge_trash)
    purged = latest(archive, "trash.purged")
    assert (purged["actor"], purged["detail"]) == ("app", "2 expired entries deleted")


def test_the_command_lines_rescan_is_recorded_as_the_command_lines(archive):
    archive.call(rescan, argparse.Namespace(force=False), archive.app.state.db)
    scan = latest(archive, "scan.completed")
    assert scan["actor"] == "cli" and scan["detail"] == "0 files, 0 added, 0 relinked, 0 missing"
    assert scan["job_id"] is None


def test_the_app_records_when_it_starts_and_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path / "media")
    with TestClient(create_app(youtube=FakeYouTube())):
        pass
    with sqlite3.connect(config.database_path) as conn:
        rows = conn.execute("SELECT event, actor FROM events ORDER BY id").fetchall()
    assert rows == [("app.started", "app"), ("app.stopped", "app")]


def test_every_event_is_written_to_the_log_too(archive, caplog):
    caplog.set_level(logging.INFO, logger="app.events")
    archive.youtube.add(VIDEO)
    archive.call(archive.app.state.runner.stop)
    video = add(archive)
    archive.client.post(f"/api/jobs/{video['job_id']}/pause")
    refuse(archive)

    lines = {(record.levelno, record.getMessage()) for record in caplog.records}
    job = video["job_id"]
    assert (
        logging.INFO,
        f"job.paused by owner (job {job}, video {video['id']}) [asked]",
    ) in lines
    assert (
        logging.INFO,
        f"job.queued by owner (job {job}, video {video['id']}): origin user",
    ) in lines
    # A refusal is a warning, with what YouTube said.
    refusals = [
        m for level, m in lines if level == logging.WARNING and m.startswith("youtube.refused")
    ]
    assert len(refusals) == 1 and BOT in refusals[0]
    # And the log says no more than the record does (the start-up line came before the test).
    logged = [r.getMessage() for r in caplog.records if r.name == "app.events"]
    assert len(logged) == len(archive.events()) - 1


def test_events_page_newest_first_by_id(archive):
    archive.youtube.add(VIDEO)
    archive.wait_job(add(archive)["job_id"])  # queued, started, completed
    for n in range(2):
        pause(archive, hours=1 + n)
    everything = archive.events()
    assert [e["id"] for e in everything] == sorted((e["id"] for e in everything), reverse=True)

    seen, before = [], None
    while True:
        params = {"limit": 2, **({"before": before} if before else {})}
        page = archive.client.get("/api/events", params=params).json()
        assert len(page["items"]) <= 2
        seen += [e["id"] for e in page["items"]]
        before = page["next_before"]
        if before is None:
            break
        assert before == page["items"][-1]["id"]  # the next page is everything older than this
    assert seen == [e["id"] for e in everything]
    assert len(set(seen)) == len(seen)


def test_events_filter_by_what_they_are_about_and_by_group(archive):
    seed_tab(archive, "video", ids("vid", 1))
    sub = subscribe(archive)
    archive.youtube.add(VIDEO)
    video = add(archive)
    archive.wait_job(video["job_id"])
    pause(archive)

    def names(**params):
        return {e["event"] for e in archive.events(**params)}

    assert names(group="youtube") == {"youtube.paused"}
    assert "job.completed" in names(group="jobs") and "youtube.paused" not in names(group="jobs")
    assert names(group="app") == {"app.started"}
    assert names(job_id=video["job_id"]) == {"job.queued", "job.started", "job.completed"}
    assert names(video_id=video["id"]) == names(job_id=video["job_id"])
    assert {e["subscription"]["id"] for e in archive.events(subscription_id=sub["id"])} == {
        sub["id"]
    }
    assert {e["job_kind"] for e in archive.events(subscription_id=sub["id"])} == {"check"}
    assert names(job_id=video["job_id"], group="youtube") == set()
    for bad in ({"group": "other"}, {"limit": 0}, {"limit": 201}, {"before": 0}):
        assert archive.client.get("/api/events", params=bad).status_code == 422, bad


def test_an_event_has_the_shape_the_contract_gives_it(archive):
    archive.youtube.add(VIDEO)
    archive.wait_job(add(archive)["job_id"])
    page = archive.client.get("/api/events", params={"limit": 3}).json()
    assert set(page) == {"items", "next_before"}
    for event in page["items"]:
        assert set(event) == {
            "id",
            "at",
            "event",
            "actor",
            "job_id",
            "job_kind",
            "video",
            "subscription",
            "reason",
            "detail",
        }
    completed = page["items"][0]
    assert set(completed["video"]) == {"id", "title"} and completed["subscription"] is None


def test_the_system_page_reports_the_pace_and_how_much_was_done(archive, monkeypatch):
    monkeypatch.setattr(pace, "REST", {"download": (120.0, 240.0), "check": (20.0, 40.0)})
    system = archive.client.get("/api/system").json()
    assert system["pace"] == {"download_rest": [120, 240], "check_rest": [20, 40]}
    assert system["activity"] == {
        "downloads_last_hour": 0,
        "downloads_last_day": 0,
        "last_download_at": None,
        "last_refusal_at": None,
    }
    monkeypatch.setattr(pace, "REST", dict.fromkeys(pace.REST, (0.0, 0.0)))
    for youtube_id in (VIDEO, OTHER):
        archive.youtube.add(youtube_id)
        archive.wait_job(add(archive, youtube_id)["job_id"])
    archive.sql("UPDATE events SET at = '2000-01-01T00:00:00Z' WHERE job_id = 1")
    refuse(archive)
    activity = archive.client.get("/api/system").json()["activity"]
    assert (activity["downloads_last_hour"], activity["downloads_last_day"]) == (1, 1)
    assert activity["last_download_at"] > "2026" and activity["last_refusal_at"] > "2026"
    archive.client.post("/api/jobs/clear")
    assert archive.client.get("/api/system").json()["activity"] == activity
    # Everything also appears on the Queue page's counts, from the same view.
    assert archive.client.get("/api/system").json()["queue"] == {
        "queued": 0,
        "waiting": 0,
        "running": 0,
        "failed": 0,
    }
