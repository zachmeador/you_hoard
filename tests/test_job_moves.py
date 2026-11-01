"""A job changes status only by the moves the table allows, and says why it is where it is."""

import itertools

import pytest

from app import jobs
from app.jobs import MOVES, NotAllowed, Priority
from app.youtube import Blocked, Inaccessible, Unavailable, YouTubeError
from tests.test_bot_checks import BOT, IDS, downloads, one_at_a_time, pause, resume
from tests.test_library import OTHER, VIDEO, add
from tests.test_subscriptions import ids, seed_tab, subscribe

STATUSES = ("queued", "paused", "running", "completed", "failed", "cancelled")
SET_FIELDS = {
    "paused": ", reason = 'asked'",
    "running": ", started_at = '2026-01-01T00:00:00Z', attempts = 1",
    "completed": ", finished_at = '2026-01-01T00:00:00Z'",
    "failed": ", finished_at = '2026-01-01T00:00:00Z', reason = 'error', error = 'it broke'",
    "cancelled": ", finished_at = '2026-01-01T00:00:00Z'",
}
JOB_KEYS = {
    "id",
    "kind",
    "status",
    "state",
    "reason",
    "origin",
    "waiting_on",
    "waits_until",
    "priority",
    "refusals",
    "attempts",
    "max_attempts",
    "error",
    "result",
    "created_at",
    "started_at",
    "finished_at",
    "video",
    "subscription",
    "via_subscription",
    "progress",
}
# What each request needs of a job's status.
REQUESTS = {
    "cancel": ("post", "/api/jobs/{}/cancel", {"queued", "paused", "running"}),
    "retry": ("post", "/api/jobs/{}/retry", {"failed", "cancelled"}),
    "pause": ("post", "/api/jobs/{}/pause", {"queued"}),
    "resume": ("post", "/api/jobs/{}/resume", {"paused"}),
    "run now": ("post", "/api/jobs/{}/run-now", {"queued"}),
    "remove": ("delete", "/api/jobs/{}", {"completed", "failed", "cancelled"}),
}
counter = itertools.count(1)


def make_job(archive, status: str, **fields) -> int:
    """A download job in this status, set up directly: the workers must be stopped."""
    youtube_id = f"mv{next(counter):09d}"
    archive.youtube.add(youtube_id)
    job_id = add(archive, youtube_id, **fields)["job_id"]
    if status != "queued":
        archive.sql(
            f"UPDATE jobs SET status = ?{SET_FIELDS[status]} WHERE id = ?", (status, job_id)
        )
    return job_id


def snapshot(archive, job_id: int) -> tuple[dict, int]:
    """The job's row and how many events there are, to show that a refusal changed neither."""
    row = archive.sql("SELECT * FROM jobs WHERE id = ?", (job_id,))[0]
    return row, archive.sql("SELECT count(*) AS n FROM events")[0]["n"]


def test_the_moves_are_those_the_design_allows():
    assert MOVES == {
        "queued": ("paused", "running", "cancelled"),
        "paused": ("queued", "cancelled"),
        "running": ("queued", "completed", "failed", "cancelled"),
        "failed": ("queued",),
        "cancelled": ("queued",),
        "completed": (),
    }


def test_only_the_moves_in_the_table_happen_and_a_refused_move_changes_nothing(stopped):
    runner = stopped.app.state.runner

    def move(job_id: int, target: str):
        async def run():
            async with stopped.app.state.db.transaction() as conn:
                await runner._move(conn, job_id, target, "job.test", actor="app")

        return stopped.call(run)

    for start in STATUSES:
        for target in STATUSES:
            job_id = make_job(stopped, start)
            before, events = snapshot(stopped, job_id)
            where = f"{start} -> {target}"
            if target in MOVES[start]:
                move(job_id, target)
                after, events_after = snapshot(stopped, job_id)
                assert after["status"] == target, where
                assert events_after == events + 1, where
            else:
                with pytest.raises(NotAllowed):
                    move(job_id, target)
                assert snapshot(stopped, job_id) == (before, events), where


def test_a_request_the_status_forbids_is_a_409_that_changes_nothing(stopped):
    for name, (method, path, allowed) in REQUESTS.items():
        for status in STATUSES:
            if status in allowed:
                continue
            job_id = make_job(stopped, status)
            before = snapshot(stopped, job_id)
            response = stopped.client.request(method, path.format(job_id))
            assert response.status_code == 409, f"{name} a {status} job: {response.text}"
            assert snapshot(stopped, job_id) == before, f"{name} a {status} job"


def test_a_request_for_a_job_that_does_not_exist_is_a_404(archive):
    for method, path, _ in REQUESTS.values():
        response = archive.client.request(method, path.format(9999))
        assert response.status_code == 404, path
        assert response.json() == {"detail": "Job not found"}


def test_jobs_cannot_be_requeued_once_their_video_is_archived(stopped):
    failed, paused = make_job(stopped, "failed"), make_job(stopped, "paused")
    stopped.sql("UPDATE videos SET media_path = 'x.mp4'")
    for path in (f"/api/jobs/{failed}/retry", f"/api/jobs/{paused}/resume"):
        response = stopped.client.post(path)
        assert response.status_code == 409 and "already archived" in response.json()["detail"]
    assert stopped.client.post("/api/jobs/retry-failed").json() == {"retried": 0}
    bulk = stopped.client.post("/api/jobs/resume", json={"ids": [paused]})
    assert bulk.json() == {"resumed": 0}
    assert [stopped.job(job_id)["status"] for job_id in (failed, paused)] == ["failed", "paused"]


def test_a_failed_job_cannot_be_retried_beside_another_for_the_same_video(stopped):
    failed = make_job(stopped, "failed")
    video = stopped.sql("SELECT video_id FROM jobs WHERE id = ?", (failed,))[0]["video_id"]
    again = stopped.client.post(f"/api/videos/{video}/download", json={}).json()["job_id"]
    assert again != failed
    response = stopped.client.post(f"/api/jobs/{failed}/retry")
    assert response.status_code == 409 and "already queued" in response.json()["detail"]
    assert stopped.job(failed)["status"] == "failed"
    assert stopped.client.post("/api/jobs/retry-failed").json() == {"retried": 0}


def test_retrying_starts_a_job_over(stopped):
    job_id = make_job(stopped, "failed")
    stopped.sql("UPDATE jobs SET attempts = 4, refusals = 2 WHERE id = ?", (job_id,))
    assert stopped.client.post(f"/api/jobs/{job_id}/retry").status_code == 200
    job = stopped.job(job_id)
    assert (job["status"], job["reason"], job["error"], job["attempts"], job["refusals"]) == (
        "queued",
        None,
        None,
        0,
        0,
    )
    assert job["finished_at"] is None


def test_retry_failed_skips_the_videos_that_are_gone(archive):
    gone, needs_account, broken = IDS
    for youtube_id in IDS:
        archive.youtube.add(youtube_id)
    archive.youtube.download_failures = {
        gone: Unavailable("Private video"),
        needs_account: Inaccessible("Join this channel to get access"),
        broken: RuntimeError("ffmpeg exploded"),
    }
    jobs_by_id = {youtube_id: add(archive, youtube_id)["job_id"] for youtube_id in IDS}
    for job_id in jobs_by_id.values():
        archive.wait_job(job_id, "failed")
    reasons = {
        youtube_id: archive.job(job_id)["reason"] for youtube_id, job_id in jobs_by_id.items()
    }
    assert reasons == {gone: "gone", needs_account: "needs_account", broken: "error"}

    archive.youtube.download_failures = {gone: Unavailable("Private video")}
    assert archive.client.post("/api/jobs/retry-failed").json() == {"retried": 2}
    for youtube_id in (needs_account, broken):
        archive.wait_job(jobs_by_id[youtube_id])
    assert archive.job(jobs_by_id[gone])["status"] == "failed"
    assert downloads(archive).count(gone) == 1  # not tried a second time


def test_run_now_skips_a_wait_and_keeps_the_attempts_and_the_error(archive):
    archive.youtube.add(VIDEO)
    archive.youtube.download_failures[VIDEO] = YouTubeError("HTTP Error 503: Service Unavailable")
    job_id = add(archive)["job_id"]
    waiting = archive.wait(lambda: (job := archive.job(job_id))["state"] == "waiting" and job)
    assert (waiting["reason"], waiting["waiting_on"], waiting["attempts"]) == ("retry", "retry", 1)
    runner = archive.app.state.runner
    archive.call(runner.stop)
    archive.sql("UPDATE jobs SET refusals = 2 WHERE id = ?", (job_id,))

    assert archive.client.post(f"/api/jobs/{job_id}/run-now").status_code == 200
    job = archive.job(job_id)
    assert (job["state"], job["reason"], job["refusals"]) == ("queued", None, 0)
    assert (job["attempts"], job["error"]) == (waiting["attempts"], waiting["error"])
    assert archive.sql("SELECT run_after FROM jobs WHERE id = ?", (job_id,))[0]["run_after"] is None

    del archive.youtube.download_failures[VIDEO]
    archive.call(runner.start)
    archive.wait_job(job_id)


def test_run_now_is_refused_while_youtube_is_paused(archive):
    archive.youtube.add(VIDEO)
    archive.youtube.download_failures[VIDEO] = YouTubeError("HTTP Error 503: Service Unavailable")
    job_id = add(archive)["job_id"]
    archive.wait(lambda: archive.job(job_id)["state"] == "waiting")
    pause(archive)
    before = snapshot(archive, job_id)
    response = archive.client.post(f"/api/jobs/{job_id}/run-now")
    assert response.status_code == 409 and "paused until" in response.json()["detail"]
    assert snapshot(archive, job_id) == before

    resume(archive)
    assert archive.client.post(f"/api/jobs/{job_id}/run-now").status_code == 200


def test_run_now_puts_a_job_at_the_front_of_the_queue(stopped):
    one_at_a_time(stopped)
    others = [make_job(stopped, "queued") for _ in range(2)]
    refused = make_job(stopped, "queued")  # the newest, with the others asked for by hand too
    stopped.sql("UPDATE jobs SET refusals = 3 WHERE id = ?", (refused,))
    assert stopped.client.get("/api/jobs/ids", params={"status": "queued"}).json()["ids"] == [
        *others,
        refused,
    ]
    assert stopped.client.post(f"/api/jobs/{refused}/run-now").status_code == 200
    assert stopped.client.get("/api/jobs/ids", params={"status": "queued"}).json()["ids"] == [
        refused,
        *others,
    ]


def test_up_next_is_the_order_the_worker_takes(stopped):
    one_at_a_time(stopped)
    keys = {}
    for name, (priority, refusals) in {
        "routine": (0, 0),
        "refused urgent": (10, 1),
        "asked": (5, 0),
        "also asked": (5, 0),
    }.items():
        job_id = make_job(stopped, "queued")
        stopped.sql(
            "UPDATE jobs SET priority = ?, refusals = ? WHERE id = ?", (priority, refusals, job_id)
        )
        keys[name] = job_id
    expected = [keys[name] for name in ("asked", "also asked", "routine", "refused urgent")]
    listed = stopped.client.get("/api/jobs", params={"status": "queued"}).json()["items"]
    assert [job["id"] for job in listed] == expected
    assert (
        stopped.client.get("/api/jobs/ids", params={"status": "queued"}).json()["ids"] == expected
    )

    stopped.call(stopped.app.state.runner.start)
    for job_id in expected:
        stopped.wait_job(job_id)
    taken = {
        stopped.sql("SELECT youtube_id FROM videos WHERE id = ?", (job["video"]["id"],))[0][
            "youtube_id"
        ]: job["id"]
        for job in stopped.jobs(kind="download")
    }
    assert [taken[youtube_id] for youtube_id in downloads(stopped)] == expected


def test_a_waiting_job_names_what_it_waits_on_by_which_wait_ends_later(stopped):
    soon, later_one = make_job(stopped, "queued"), make_job(stopped, "queued")
    stopped.sql(
        "UPDATE jobs SET run_after = ?, reason = 'retry' WHERE id = ?",
        ("2099-01-01T00:00:00Z", later_one),
    )
    soon_at = "2000-01-01T00:00:00Z"  # already over: no longer a wait
    stopped.sql("UPDATE jobs SET run_after = ?, reason = 'retry' WHERE id = ?", (soon_at, soon))
    assert stopped.job(soon)["state"] == "queued"
    assert (stopped.job(later_one)["state"], stopped.job(later_one)["waiting_on"]) == (
        "waiting",
        "retry",
    )

    pause(stopped)  # six hours: the pause ends before 2099 but after a wait that is over
    soon_job, later_job = stopped.job(soon), stopped.job(later_one)
    assert (soon_job["waiting_on"], soon_job["waits_until"]) == ("youtube", stopped.gate.resumes_at)
    assert (later_job["waiting_on"], later_job["waits_until"]) == ("retry", "2099-01-01T00:00:00Z")
    # The soonest comes first in the waiting list, as the later of its two ends.
    listed = stopped.client.get("/api/jobs", params={"status": "waiting"}).json()["items"]
    assert [job["id"] for job in listed] == [soon, later_one]

    stopped.sql("UPDATE jobs SET run_after = ? WHERE id = ?", (soon_at, later_one))
    assert stopped.job(later_one)["waiting_on"] == "youtube"


def test_only_the_jobs_that_talk_to_youtube_wait_out_a_pause(archive):
    seed_tab(archive, "video", ids("vid", 1))
    sub = subscribe(archive)
    archive.call(archive.app.state.runner.stop)
    queued = {
        "download": make_job(archive, "queued"),
        "check": archive.client.post(f"/api/subscriptions/{sub['id']}/check").json()["job_id"],
        "scan": archive.client.post("/api/library/rescan").json()["job_id"],
    }
    pause(archive)
    for kind, job_id in queued.items():
        expected = "waiting" if kind in jobs.YOUTUBE_KINDS else "queued"
        assert archive.job(job_id)["state"] == expected, kind


def test_each_way_of_asking_for_a_job_says_who_asked_and_how_urgently(archive):
    seed_tab(archive, "video", ids("vid", 4))
    sub = subscribe(archive, download_policy="none")
    archive.call(archive.app.state.runner.stop)
    path = f"/api/subscriptions/{sub['id']}"
    archive.youtube.add(VIDEO)
    added = add(archive)["job_id"]
    entry = archive.client.post(f"{path}/entries/{ids('vid', 4)[0]}/download").json()["job_id"]
    patched = archive.client.patch(path, json={"download_policy": "recent", "recent_count": 2})
    assert patched.status_code == 200
    (by_policy,) = (
        job["id"] for job in archive.jobs(kind="download") if job["id"] not in (added, entry)
    )
    check = archive.client.post(f"{path}/check").json()["job_id"]
    scan = archive.client.post("/api/library/rescan").json()["job_id"]

    def traits(job_id):
        job = archive.job(job_id)
        via = job["via_subscription"]
        return job["origin"], job["priority"], via and via["id"]

    assert traits(added) == ("user", Priority.URGENT, None)
    assert traits(entry) == ("user", Priority.ASKED, sub["id"])
    assert traits(by_policy) == ("policy", Priority.ROUTINE, sub["id"])
    assert traits(check) == ("user", Priority.ASKED, None)
    assert traits(scan) == ("user", Priority.SCAN, None)

    # A check that falls due on its own is the schedule's.
    archive.sql("DELETE FROM jobs WHERE id = ?", (check,))
    archive.sql("UPDATE subscriptions SET next_check_at = '2000-01-01T00:00:00Z'")
    assert archive.call(archive.app.state.runner.queue_due_checks) == 1
    (scheduled,) = archive.jobs(kind="check", status="queued")
    assert (scheduled["origin"], scheduled["priority"]) == ("schedule", Priority.ROUTINE)
    assert scheduled["subscription"]["id"] == sub["id"]
    assert [priority.value for priority in Priority] == [0, 1, 5, 10, 20]


def test_deleting_a_subscription_leaves_its_downloads_running_on_library_defaults(archive):
    seed_tab(archive, "video", ids("vid", 2))
    sub = subscribe(archive, download_policy="none", quality="360p")
    archive.call(archive.app.state.runner.stop)
    path = f"/api/subscriptions/{sub['id']}"
    assert archive.client.patch(path, json={"download_policy": "all"}).status_code == 200
    queued = [job["id"] for job in archive.jobs(kind="download")]
    assert len(queued) == 2
    assert archive.client.delete(path).status_code == 200
    for job_id in queued:
        job = archive.job(job_id)
        assert (job["origin"], job["via_subscription"]) == ("policy", None)
    archive.call(archive.app.state.runner.start)
    for job_id in queued:
        archive.wait_job(job_id)
    assert archive.youtube.calls[-1][1].quality == "1080p"  # the library's, not the subscription's


def test_a_job_has_the_shape_the_contract_gives_it(archive):
    seed_tab(archive, "video", ids("vid", 1))
    sub = subscribe(archive)
    archive.youtube.add(VIDEO)
    video = add(archive)
    archive.wait_job(video["job_id"])
    archive.client.post(f"/api/subscriptions/{sub['id']}/entries/{ids('vid', 1)[0]}/download")
    archive.wait_idle()
    listing = archive.client.get("/api/jobs").json()
    assert set(listing["counts"]) == set(jobs.STATES)
    for job in listing["items"]:
        assert set(job) == JOB_KEYS and "run_after" not in job
    download = next(
        job for job in listing["items"] if job["video"] and job["video"]["id"] == video["id"]
    )
    assert set(download["video"]) == {"id", "title", "youtube_id"}
    assert (download["max_attempts"], download["state"], download["origin"]) == (
        4,
        "completed",
        "user",
    )
    check = next(job for job in listing["items"] if job["kind"] == "check")
    assert set(check["subscription"]) == {"id", "title"} and check["video"] is None
    assert check["max_attempts"] == 4
    scan = archive.client.post("/api/library/rescan").json()["job_id"]
    assert archive.wait_job(scan)["max_attempts"] == 1


def test_a_waiting_video_and_entry_carry_the_same_job_shape(archive):
    archive.youtube.add(VIDEO)
    archive.youtube.download_failures[VIDEO] = YouTubeError("HTTP Error 503: Service Unavailable")
    video = add(archive)
    archive.wait(lambda: archive.job(video["job_id"])["state"] == "waiting")
    saved = archive.client.get(f"/api/videos/{video['id']}").json()
    assert set(saved["job"]) == {
        "state",
        "reason",
        "waiting_on",
        "waits_until",
        "attempts",
        "max_attempts",
        "error",
    }
    assert (saved["job"]["state"], saved["job"]["reason"]) == ("waiting", "retry")
    assert saved["job"]["waiting_on"] == "retry" and saved["job"]["max_attempts"] == 4
    assert saved["error_reason"] is None and saved["lost_at"] is None


def test_a_failed_video_says_why_it_failed_and_a_lost_one_says_when(archive):
    archive.youtube.add(VIDEO)
    archive.youtube.download_failures[VIDEO] = Unavailable("Private video")
    video = add(archive)
    archive.wait_job(video["job_id"], "failed")
    saved = archive.client.get(f"/api/videos/{video['id']}").json()
    assert (saved["status"], saved["error"], saved["error_reason"]) == (
        "failed",
        "Private video",
        "gone",
    )
    archive.youtube.download_failures.clear()
    archive.youtube.add(OTHER)
    other = add(archive, OTHER)
    archive.wait_job(other["job_id"])
    assert archive.client.get(f"/api/videos/{other['id']}").json()["error_reason"] is None


def test_the_refused_message_is_the_jobs_error(archive):
    archive.youtube.add(VIDEO)
    archive.youtube.download_failures[VIDEO] = Blocked(BOT)
    job_id = add(archive)["job_id"]
    archive.wait(lambda: archive.gate.paused)
    job = archive.wait(lambda: (job := archive.job(job_id))["reason"] == "refused" and job)
    assert (job["error"], job["refusals"], job["attempts"]) == (BOT, 1, 0)


def test_a_pause_does_not_make_a_job_forget_what_it_was_waiting_for(archive):
    retry, premiere = IDS[:2]
    archive.youtube.add(retry)
    archive.youtube.download_failures[retry] = YouTubeError("HTTP Error 503: Service Unavailable")
    archive.youtube.add(premiere, live_status="is_upcoming")
    jobs_waiting = [add(archive, youtube_id)["job_id"] for youtube_id in (retry, premiere)]
    for job_id in jobs_waiting:
        archive.wait(lambda job_id=job_id: archive.job(job_id)["state"] == "waiting")
    archive.call(archive.app.state.runner.stop)
    refused = make_job(archive, "queued")
    archive.sql("UPDATE jobs SET reason = 'refused', refusals = 1 WHERE id = ?", (refused,))

    def traits(job_id):
        job = archive.job(job_id)
        return job["state"], job["reason"], job["waiting_on"], job["waits_until"]

    for job_id in (*jobs_waiting, refused):
        before = traits(job_id)
        assert archive.client.post(f"/api/jobs/{job_id}/pause").status_code == 200
        assert archive.job(job_id)["reason"] == "asked"
        assert archive.client.post(f"/api/jobs/{job_id}/resume").status_code == 200
        assert traits(job_id) == before, job_id
    assert [archive.job(job_id)["reason"] for job_id in (*jobs_waiting, refused)] == [
        "retry",
        "premiere",
        "refused",
    ]
    # In bulk, too.
    everything = [*jobs_waiting, refused]
    assert archive.client.post("/api/jobs/pause", json={"ids": everything}).json() == {"paused": 3}
    assert archive.client.post("/api/jobs/resume", json={"ids": everything}).json() == {
        "resumed": 3
    }
    assert [archive.job(job_id)["reason"] for job_id in everything] == [
        "retry",
        "premiere",
        "refused",
    ]


def test_a_job_that_was_not_waiting_comes_back_with_no_reason(stopped):
    job_id = make_job(stopped, "queued")
    assert stopped.client.post(f"/api/jobs/{job_id}/pause").status_code == 200
    assert stopped.client.post(f"/api/jobs/{job_id}/resume").status_code == 200
    job = stopped.job(job_id)
    assert (job["reason"], job["state"]) == (None, "queued")
    assert stopped.sql("SELECT resume_reason FROM jobs WHERE id = ?", (job_id,))[0] == {
        "resume_reason": None
    }
