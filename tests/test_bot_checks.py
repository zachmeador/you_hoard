"""A bot check pauses all YouTube work, and jobs rest between one another."""

import asyncio
import contextlib
import logging
import time

import pytest
from yt_dlp.utils import DownloadError

from app import pace
from app.db import parse_time, utcnow
from app.gate import YouTubeGate
from app.youtube import (
    Blocked,
    Inaccessible,
    Paused,
    Unavailable,
    YouTubeError,
    classify,
)
from tests.fake_youtube import AVATAR, AVATAR_URL, CHANNEL_ID
from tests.test_details import sidecar_of
from tests.test_jobs import hold_queue
from tests.test_library import VIDEO, add
from tests.test_subscriptions import CHANNEL_URL, PLAYLIST_URL, check, ids, seed_tab, subscribe

BOT = "Sign in to confirm you're not a bot"
AGE_GATE = "Sign in to confirm your age. This video may be inappropriate for some users."
COOKIES = "Use --cookies-from-browser or --cookies for the authentication."
RATE_LIMIT = "Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests"
IDS = ["botcheck001", "botcheck002", "botcheck003"]
LOOKUP = "lookup00001"


def refusal(text: str, youtube_id: str = IDS[0]) -> YouTubeError:
    """What the adapter raises when yt-dlp fails with this message."""
    return classify(DownloadError(f"ERROR: [youtube] {youtube_id}: {text}"))


def one_at_a_time(archive) -> None:
    response = archive.client.put("/api/settings", json={"max_concurrent_downloads": 1})
    assert response.status_code == 200, response.text


def downloads(archive) -> list[str]:
    return [call[1].youtube_id for call in archive.youtube.calls if call[0] == "download"]


def queue_stopped(archive, youtube_ids: list[str]) -> list[dict]:
    """Queue videos with the workers stopped, so none is tried before all are queued."""
    one_at_a_time(archive)
    runner = archive.app.state.runner
    archive.call(runner.stop)
    videos = []
    for youtube_id in youtube_ids:
        if youtube_id not in archive.youtube.videos:
            archive.youtube.add(youtube_id)
        videos.append(add(archive, youtube_id))
    archive.call(runner.start)
    return videos


def queue_blocked(archive) -> list[dict]:
    """Queue three videos; the first one meets a bot check."""
    archive.youtube.download_failures[IDS[0]] = Blocked(BOT)
    videos = queue_stopped(archive, IDS)
    archive.wait(lambda: archive.gate.paused)
    archive.wait(
        lambda: all(archive.job(video["job_id"])["state"] == "waiting" for video in videos)
    )
    return videos


def refuse(archive) -> None:
    """YouTube refuses a lookup: the pause starts, or the next and longer one."""
    archive.youtube.failures[LOOKUP] = Blocked(BOT)
    with pytest.raises(Blocked):
        archive.call(archive.gate.fetch_video, LOOKUP)


def resume(archive) -> None:
    assert archive.client.post("/api/jobs/resume-youtube").status_code == 200


def pause(archive, hours: float = 6) -> None:
    response = archive.client.post("/api/jobs/pause-youtube", json={"hours": hours})
    assert response.status_code == 200, response.text


def paused_for(gate: YouTubeGate) -> float:
    return gate.paused_until - time.time()


def second_pause(archive, succeed) -> float:
    """Seconds the second pause lasts when `succeed` runs between the two refusals."""
    refuse(archive)
    assert 3590 < paused_for(archive.gate) <= 3600
    resume(archive)
    succeed()
    refuse(archive)
    return paused_for(archive.gate)


def reloaded(archive) -> YouTubeGate:
    """A gate that has read what the running one saved, as after a restart."""
    gate = YouTubeGate(archive.youtube, archive.app.state.db)
    archive.call(gate.load)
    return gate


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (f"{AGE_GATE} {COOKIES}", Inaccessible),
        (f"Sign in to confirm you’re not a bot. {COOKIES}", Blocked),
        (f"Sign in to confirm you're not a bot. {COOKIES}", Blocked),
        ("Video unavailable. YouTube is requiring a captcha challenge before playback", Blocked),
        ("Video unavailable", Unavailable),
    ],
    ids=["age gate", "bot check", "bot check, straight apostrophe", "captcha", "gone"],
)
def test_the_classifier_tells_refusals_from_age_gates_and_gone_videos(text, kind):
    assert type(refusal(text)) is kind


def test_a_bot_check_pauses_every_download_instead_of_each_trying(archive):
    videos = queue_blocked(archive)
    time.sleep(0.2)  # time enough for the worker to have moved on to the next job
    assert downloads(archive) == [IDS[0]]

    resumes = archive.client.get("/api/jobs").json()["youtube_paused_until"]
    assert resumes and archive.client.get("/api/system").json()["youtube_paused_until"] == resumes
    assert 3590 < paused_for(archive.gate) <= 3600
    for video in videos:
        job = archive.job(video["job_id"])
        assert job["status"] == "queued" and job["state"] == "waiting"
        assert (job["waiting_on"], job["waits_until"]) == ("youtube", resumes)
    first, *others = (archive.job(video["job_id"]) for video in videos)
    assert first["attempts"] == 0 and first["error"] == BOT  # the block isn't the job's fault
    assert (first["reason"], first["refusals"]) == ("refused", 1)
    assert [(job["reason"], job["refusals"]) for job in others] == [(None, 0), (None, 0)]

    archive.youtube.download_failures.clear()
    resume(archive)
    for video in videos:
        archive.wait_job(video["job_id"])
    assert archive.client.get("/api/jobs").json()["youtube_paused_until"] is None


def test_pauses_grow_while_youtube_keeps_refusing_and_reset_after_a_success(archive):
    queue_blocked(archive)
    gate = archive.gate
    archive.youtube.download_failures[IDS[1]] = Blocked(BOT)
    resume(archive)
    archive.wait(lambda: gate.paused)  # the next video meets the check too
    assert 7190 < paused_for(gate) <= 7200

    archive.youtube.download_failures.clear()
    resume(archive)
    archive.wait_idle()
    archive.youtube.add("botcheck004")
    archive.youtube.download_failures["botcheck004"] = Blocked(BOT)
    add(archive, "botcheck004")
    archive.wait(lambda: gate.paused)
    assert 3590 < paused_for(gate) <= 3600  # back to an hour


def test_a_check_that_succeeds_does_not_reset_the_backoff(archive):
    seed_tab(archive, "video", ids("vid", 2))
    sub = subscribe(archive)
    assert 7190 < second_pause(archive, lambda: check(archive, sub, full=True)) <= 7200
    assert archive.gate.refusals == 2


def test_a_lookup_that_succeeds_does_not_reset_the_backoff(archive):
    archive.youtube.add(VIDEO)

    def look_up() -> None:
        response = archive.client.post("/api/videos/resolve", json={"url": VIDEO})
        assert response.status_code == 200, response.text

    assert 7190 < second_pause(archive, look_up) <= 7200
    assert archive.gate.refusals == 2


def test_a_download_that_succeeds_resets_the_backoff(archive):
    video = ids("vid", 1)[0]
    seed_tab(archive, "video", [video])
    sub = subscribe(archive)

    def download() -> None:
        queued = archive.client.post(f"/api/subscriptions/{sub['id']}/entries/{video}/download")
        archive.wait_job(queued.json()["job_id"])

    assert 3590 < second_pause(archive, download) <= 3600


def test_an_age_gated_video_fails_alone_instead_of_pausing_the_queue(archive):
    age_gated, other = IDS[:2]
    archive.youtube.download_failures[age_gated] = refusal(f"{AGE_GATE} {COOKIES}", age_gated)
    first, second = queue_stopped(archive, [age_gated, other])

    failed = archive.wait_job(first["job_id"], "failed")
    assert failed["attempts"] == 1 and "confirm your age" in failed["error"]
    archive.wait_job(second["job_id"])
    assert not archive.gate.paused and archive.gate.refusals == 0


def test_a_refused_video_goes_behind_the_others_so_it_cannot_hold_up_the_queue(archive):
    stuck, *others = IDS
    first, *rest = queue_blocked(archive)
    resume(archive)
    for video in rest:
        archive.wait_job(video["job_id"])
    archive.wait(lambda: archive.gate.paused)  # its turn comes round again, last
    assert downloads(archive) == [stuck, *others, stuck]
    assert archive.job(first["job_id"])["status"] == "queued"


def test_a_refused_job_goes_behind_every_job_youtube_has_not_refused(archive):
    stuck, middle, low = IDS
    one_at_a_time(archive)
    runner = archive.app.state.runner
    archive.call(runner.stop)
    archive.youtube.download_failures[stuck] = Blocked(BOT)
    for youtube_id in IDS:
        archive.youtube.add(youtube_id)
    jobs = [add(archive, youtube_id)["job_id"] for youtube_id in IDS]
    for job_id, priority in zip(jobs, (10, 5, 0), strict=True):
        archive.sql("UPDATE jobs SET priority = ? WHERE id = ?", (priority, job_id))
    archive.call(runner.start)
    archive.wait(lambda: archive.gate.paused)
    resume(archive)
    archive.wait(lambda: len(downloads(archive)) == 4)
    # The refused job has the highest priority and still goes last.
    assert downloads(archive) == [stuck, middle, low, stuck]


def test_five_generic_download_failures_in_a_row_pause_youtube_for_an_hour(archive):
    failing = [f"failure{n:04d}" for n in range(pace.FAILURE_STREAK + 1)]
    for youtube_id in failing:
        archive.youtube.add(youtube_id)
        archive.youtube.download_failures[youtube_id] = YouTubeError("HTTP Error 503: Unavailable")
    queue_stopped(archive, failing)
    archive.wait(lambda: archive.gate.paused)
    time.sleep(0.2)  # time enough for the worker to have moved on to the next job
    assert downloads(archive) == failing[: pace.FAILURE_STREAK]
    assert 3590 < paused_for(archive.gate) <= 3600
    assert archive.gate.refusals == 0  # nothing was refused, so this stays off the ladder


def test_a_completed_download_ends_the_streak_of_failures(archive):
    failing = [f"failure{n:04d}" for n in range(pace.FAILURE_STREAK * 2 - 1)]
    completed = "completed01"
    archive.youtube.add(completed)
    for youtube_id in failing:
        archive.youtube.add(youtube_id)
        archive.youtube.download_failures[youtube_id] = YouTubeError("HTTP Error 503: Unavailable")
    # One short of a streak, a success, then a full streak: only the last failure pauses.
    order = [*failing[: pace.FAILURE_STREAK - 1], completed, *failing[pace.FAILURE_STREAK - 1 :]]
    queue_stopped(archive, order)
    archive.wait(lambda: archive.gate.paused)
    time.sleep(0.2)  # time enough for the worker to have moved on to the next job
    assert downloads(archive) == order
    assert 3590 < paused_for(archive.gate) <= 3600


def test_pausing_and_resuming_leave_a_retry_backoff_and_a_premiere_wait_as_they_were(archive):
    retry, premiere = IDS[:2]
    archive.youtube.add(retry)
    archive.youtube.download_failures[retry] = YouTubeError("HTTP Error 503: Unavailable")
    archive.youtube.add(premiere, live_status="is_upcoming")
    jobs = [add(archive, youtube_id)["job_id"] for youtube_id in (retry, premiere)]

    def waits() -> dict[int, str | None]:
        return {
            row["id"]: row["run_after"] for row in archive.sql("SELECT id, run_after FROM jobs")
        }

    archive.wait(lambda: all(waits().values()))  # each has its own wait
    before = waits()
    pause(archive)
    assert waits() == before  # pausing writes to no job
    resume(archive)
    assert waits() == before  # and neither does Resume now
    for action in ("pause", "resume"):
        assert archive.client.post(f"/api/jobs/{jobs[0]}/{action}").status_code == 200
        assert waits() == before


def test_a_job_resumed_or_queued_during_a_pause_is_waiting_on_youtube_never_queued(archive):
    runner = archive.app.state.runner
    archive.call(runner.stop)
    for youtube_id in (*IDS, LOOKUP):
        archive.youtube.add(youtube_id)
    held, resumed, retried, again = (add(archive, youtube_id) for youtube_id in (*IDS, LOOKUP))
    assert archive.client.post(f"/api/jobs/{resumed['job_id']}/pause").status_code == 200
    for video in (retried, again):
        assert archive.client.post(f"/api/jobs/{video['job_id']}/cancel").status_code == 200
    pause(archive)

    assert archive.client.post(f"/api/jobs/{resumed['job_id']}/resume").status_code == 200
    assert archive.client.post(f"/api/jobs/{retried['job_id']}/retry").status_code == 200
    queued = archive.client.post(f"/api/videos/{again['id']}/download", json={})
    new_job = queued.json()["job_id"]
    assert new_job != again["job_id"]
    until = archive.gate.resumes_at
    jobs = [held["job_id"], resumed["job_id"], retried["job_id"], new_job]
    for job_id in jobs:
        job = archive.job(job_id)
        assert (job["status"], job["state"]) == ("queued", "waiting")
        assert (job["waiting_on"], job["waits_until"]) == ("youtube", until)
    counts = archive.client.get("/api/jobs").json()["counts"]
    assert counts["queued"] == 0 and counts["waiting"] == 4
    assert archive.jobs(status="queued") == []

    resume(archive)
    for job_id in jobs:
        job = archive.job(job_id)
        assert (job["state"], job["waiting_on"], job["waits_until"]) == ("queued", None, None)


def test_the_gate_stops_the_adapters_calls_while_paused(archive):
    assert archive.youtube.before_call == archive.gate.check
    archive.gate.check()  # nothing is paused
    pause(archive)
    with pytest.raises(Paused):
        archive.gate.check()


def test_a_refused_subtitle_keeps_the_video_and_holds_the_next_one(archive):
    kept, next_up = IDS[:2]
    archive.youtube.add(kept, refused_extras=RATE_LIMIT)
    first, second = queue_stopped(archive, [kept, next_up])
    archive.wait_job(first["job_id"])

    gate = archive.gate
    assert gate.paused and gate.reason == RATE_LIMIT and gate.cause == "extras"
    assert gate.refusals == 0  # YouTube refused an extra, not the video: off the ladder
    assert 3590 < paused_for(gate) <= 3600  # one fixed hour
    time.sleep(0.2)  # time enough for the worker to have moved on to the next job
    assert downloads(archive) == [kept]
    waiting = archive.job(second["job_id"])
    assert waiting["state"] == "waiting" and waiting["waits_until"] == gate.resumes_at
    video = archive.client.get(f"/api/videos/{first['id']}").json()
    assert video["status"] == "archived"
    assert "refused" not in sidecar_of(archive, video)["_youhoard"]
    done = archive.job(first["job_id"])
    assert "refused" in done["result"]
    assert "lost to a refusal" in archive.events(job_id=first["job_id"])[0]["detail"]


def test_a_download_with_refused_extras_still_counts_as_a_success(archive):
    video = ids("vid", 1)[0]
    seed_tab(archive, "video", [video])
    sub = subscribe(archive)
    archive.youtube.videos[video].refused_extras = RATE_LIMIT
    refuse(archive)
    resume(archive)
    queued = archive.client.post(f"/api/subscriptions/{sub['id']}/entries/{video}/download")
    archive.wait_job(queued.json()["job_id"])
    assert archive.gate.refusals == 0  # the video came through, so the ladder starts over
    assert 3590 < paused_for(archive.gate) <= 3600  # and the extra costs a fixed hour, not 2


def test_refusals_that_arrive_together_count_once(archive, caplog):
    caplog.set_level(logging.WARNING)
    archive.youtube.source_failure = Blocked(BOT)

    async def list_twice():
        return await asyncio.gather(
            *(archive.gate.list_entries("channel", CHANNEL_ID, "video") for _ in range(2)),
            return_exceptions=True,
        )

    results = archive.call(list_twice)
    assert all(isinstance(result, Blocked) for result in results)
    assert archive.gate.refusals == 1 and 3590 < paused_for(archive.gate) <= 3600
    logged = [record for record in caplog.records if "YouTube refused a request;" in record.message]
    assert len(logged) == 1


def test_the_pause_and_the_backoff_survive_a_restart(archive):
    refuse(archive)
    gate = archive.gate

    restarted = reloaded(archive)
    assert restarted.paused and restarted.resumes_at == gate.resumes_at
    assert abs(restarted.paused_until - gate.paused_until) < 1
    assert (restarted.refusals, restarted.cause, restarted.reason) == (1, "refused", BOT)
    with pytest.raises(Paused):
        archive.call(restarted.fetch_video, VIDEO)

    resume(archive)
    resumed = reloaded(archive)
    assert not resumed.paused and resumed.resumes_at is None
    assert resumed.refusals == 1  # only a success resets the count


def test_a_restart_during_a_pause_holds_the_jobs_it_brings_back(archive):
    archive.youtube.add(VIDEO)
    runner = archive.app.state.runner
    archive.call(runner.stop)
    video = add(archive)
    refuse(archive)
    archive.sql(
        "UPDATE jobs SET status = 'running', run_after = NULL, attempts = 1 WHERE id = ?",
        (video["job_id"],),
    )
    archive.call(runner.start)
    job = archive.job(video["job_id"])
    assert job["status"] == "queued" and job["attempts"] == 0
    assert (job["state"], job["waiting_on"]) == ("waiting", "youtube")
    assert job["waits_until"] == archive.gate.resumes_at


def test_lookups_wait_out_a_pause_without_asking_youtube(archive):
    archive.youtube.add(VIDEO)
    refuse(archive)
    calls = list(archive.youtube.calls)
    until = archive.gate.resumes_at
    requests = [
        ("/api/videos/resolve", {"url": VIDEO}),
        ("/api/videos", {"url": VIDEO}),
        ("/api/subscriptions/resolve", {"url": CHANNEL_URL}),
        ("/api/subscriptions", {"url": CHANNEL_URL}),
    ]
    for path, body in requests:
        response = archive.client.post(path, json=body)
        assert response.status_code == 503, path
        assert response.json() == {
            "detail": f"YouTube is paused until {until}",
            "resumes_at": until,
        }
    assert archive.youtube.calls == calls


def test_the_owner_can_pause_all_youtube_work(archive):
    archive.youtube.add(VIDEO)
    runner = archive.app.state.runner
    archive.call(runner.stop)
    video = add(archive)
    pause(archive)
    archive.call(runner.start)

    gate = archive.gate
    assert 21590 < paused_for(gate) <= 21600
    time.sleep(0.2)  # time enough for a worker to have taken the job
    assert downloads(archive) == []
    job = archive.job(video["job_id"])
    assert job["status"] == "queued" and job["waits_until"] == gate.resumes_at
    response = archive.client.post("/api/videos/resolve", json={"url": LOOKUP})
    assert response.status_code == 503

    status = archive.client.get("/api/jobs").json()
    assert status["youtube_paused_until"] == gate.resumes_at
    assert status["youtube_pause_cause"] == "asked"
    assert status["youtube_pause_reason"] is None and status["youtube_refusals"] == 0
    assert gate.refusals == 0  # the owner asked, so YouTube refused nothing

    resume(archive)
    archive.wait_job(video["job_id"])


def test_a_pause_on_request_never_shortens_a_longer_one(archive):
    refuse(archive)
    gate = archive.gate
    until = gate.paused_until
    pause(archive, hours=0.5)
    assert gate.paused_until == until and gate.reason == BOT

    pause(archive, hours=2)
    assert gate.paused_until > until and gate.reason is None and gate.refusals == 1
    assert reloaded(archive).reason is None


@pytest.mark.parametrize("hours", [0, -1, 24 * 30 + 1])
def test_a_pause_on_request_needs_a_sensible_length(archive, hours):
    response = archive.client.post("/api/jobs/pause-youtube", json={"hours": hours})
    assert response.status_code == 422
    assert not archive.gate.paused


def test_a_job_retried_during_a_pause_waits_it_out(archive):
    archive.youtube.add(VIDEO)
    archive.youtube.download_failures[VIDEO] = Inaccessible("Join this channel")
    video = add(archive)
    archive.wait_job(video["job_id"], "failed")
    pause(archive)
    assert archive.client.post(f"/api/jobs/{video['job_id']}/retry").status_code == 200
    job = archive.job(video["job_id"])
    assert job["status"] == "queued" and job["waits_until"] == archive.gate.resumes_at


def test_the_api_says_why_youtube_is_paused(archive):
    refuse(archive)
    for path in ("/api/jobs", "/api/system"):
        status = archive.client.get(path).json()
        assert (status["youtube_pause_reason"], status["youtube_refusals"]) == (BOT, 1)
    resume(archive)
    for path in ("/api/jobs", "/api/system"):
        status = archive.client.get(path).json()
        assert (status["youtube_pause_reason"], status["youtube_refusals"]) == (None, 1)


def test_images_and_versions_do_not_wait_for_a_pause(archive):
    refuse(archive)
    assert archive.call(archive.gate.fetch_image, AVATAR_URL) == AVATAR
    assert archive.gate.versions() == archive.youtube.versions()


def test_a_refused_lookup_pauses_youtube_and_queued_downloads_wait(archive):
    running, *waiting = (video["job_id"] for video in hold_queue(archive, queued=2))
    archive.youtube.failures[LOOKUP] = Blocked(BOT)
    response = archive.client.post("/api/videos/resolve", json={"url": LOOKUP})
    assert response.status_code == 502 and BOT in response.json()["detail"]

    gate = archive.gate
    assert gate.paused and 3590 < paused_for(gate) <= 3600
    for job_id in waiting:
        job = archive.job(job_id)
        assert job["status"] == "queued" and job["waits_until"] == gate.resumes_at
    assert archive.job(running)["status"] == "running"

    archive.youtube.hold.clear()
    archive.wait_job(running)
    time.sleep(0.2)  # time enough for the worker to have moved on to the next job
    assert downloads(archive) == [VIDEO]
    assert [archive.job(job_id)["status"] for job_id in waiting] == ["queued", "queued"]
    assert gate.refusals == 1  # that download began before the refusal, so it proves nothing


def test_a_check_stops_at_its_next_call_once_youtube_is_paused(archive, monkeypatch):
    seed_tab(archive, "video", ids("vid", 1))
    seed_tab(archive, "short", ids("sho", 1))
    sub = subscribe(archive, content_types=["video", "short"], enabled=False)
    gate = archive.gate
    archive.youtube.failures[LOOKUP] = Blocked(BOT)
    listed = archive.youtube.list_entries

    async def list_then_meet_a_bot_check_elsewhere(*args, **kwargs):
        listing = await listed(*args, **kwargs)
        with contextlib.suppress(Blocked):
            await gate.fetch_video(LOOKUP)
        return listing

    monkeypatch.setattr(archive.youtube, "list_entries", list_then_meet_a_bot_check_elsewhere)
    queued = archive.client.post(f"/api/subscriptions/{sub['id']}/check").json()
    job = archive.wait(lambda: (job := archive.job(queued["job_id"]))["state"] == "waiting" and job)

    assert job["status"] == "queued" and job["waits_until"] == gate.resumes_at
    assert job["attempts"] == 0 and job["waiting_on"] == "youtube"
    assert archive.client.get("/api/jobs").json()["counts"]["waiting"] == 1
    assert [call[2] for call in archive.youtube.calls if call[0] == "list"] == ["video"]


def test_checks_wait_out_a_pause_but_scans_still_run(archive):
    sub = subscribe(archive)
    runner = archive.app.state.runner
    pause(archive, hours=0.2)
    queued = archive.client.post(f"/api/subscriptions/{sub['id']}/check").json()
    scan = archive.client.post("/api/library/rescan").json()
    archive.wait_job(scan["job_id"])
    job = archive.job(queued["job_id"])
    assert job["status"] == "queued" and job["state"] == "waiting"
    assert archive.call(runner.queue_due_checks) == 0


def test_downloads_rest_between_one_another(archive, monkeypatch):
    monkeypatch.setattr(pace, "REST", {**pace.REST, "download": (1.0, 1.0)})
    one_at_a_time(archive)
    for youtube_id in IDS[:2]:
        archive.youtube.add(youtube_id)
    first, second = (add(archive, youtube_id) for youtube_id in IDS[:2])
    archive.wait_job(first["job_id"])
    assert archive.job(second["job_id"])["status"] == "queued"  # the worker is resting
    archive.wait_job(second["job_id"])


def test_the_api_says_when_a_rest_ends(archive, monkeypatch):
    monkeypatch.setattr(pace, "REST", {**pace.REST, "download": (60.0, 60.0)})
    archive.youtube.add(VIDEO)
    assert archive.client.get("/api/jobs").json()["download_rest_until"] is None

    archive.wait_job(add(archive)["job_id"])
    ends = archive.client.get("/api/jobs").json()["download_rest_until"]
    assert 55 < (parse_time(ends) - utcnow()).total_seconds() <= 62
    assert archive.client.get("/api/system").json()["download_rest_until"] == ends


def test_rest_holds_back_every_worker_not_only_the_one_that_ran(archive, monkeypatch):
    monkeypatch.setattr(pace, "REST", {**pace.REST, "download": (1.0, 1.0)})
    assert (
        archive.client.put("/api/settings", json={"max_concurrent_downloads": 2}).status_code == 200
    )
    archive.youtube.hold.set()  # the first download stays under way
    for youtube_id in IDS[:2]:
        archive.youtube.add(youtube_id)
    before = time.monotonic()
    first, second = (add(archive, youtube_id) for youtube_id in IDS[:2])
    archive.wait_job(first["job_id"], "running")

    time.sleep(0.4)  # the second worker is idle, but the rest since the first began isn't over
    waiting = archive.job(second["job_id"])
    assert (waiting["status"], waiting["state"], waiting["waiting_on"]) == (
        "queued",
        "queued",
        None,
    )

    archive.wait_job(second["job_id"], "running")
    assert time.monotonic() - before >= 1.0
    archive.youtube.hold.clear()
    for video in (first, second):
        archive.wait_job(video["job_id"])


def test_checks_rest_between_one_another(archive, monkeypatch):
    monkeypatch.setattr(pace, "REST", {**pace.REST, "check": (1.0, 1.0)})
    before = time.monotonic()
    for url in (CHANNEL_URL, PLAYLIST_URL):
        assert archive.client.post("/api/subscriptions", json={"url": url}).status_code == 201
    first, second = sorted(job["id"] for job in archive.jobs(kind="check"))
    archive.wait_job(first)
    assert archive.job(second)["status"] == "queued"  # resting, not running
    archive.wait_job(second)
    assert time.monotonic() - before >= 1.0


def test_a_check_resting_does_not_hold_up_a_scan(archive, monkeypatch):
    monkeypatch.setattr(pace, "REST", {**pace.REST, "check": (60.0, 60.0)})
    sub = subscribe(archive)
    queued = archive.client.post(f"/api/subscriptions/{sub['id']}/check").json()
    scan = archive.client.post("/api/library/rescan").json()
    archive.wait_job(scan["job_id"])
    assert archive.job(queued["job_id"])["state"] == "queued"


def test_failures_that_say_what_is_wrong_do_not_count_toward_a_streak(archive):
    wrong = [Unavailable("Private video"), Inaccessible("Join this channel to get access")]
    failing = [f"specific{n:03d}" for n in range(pace.FAILURE_STREAK + 3)]
    for number, youtube_id in enumerate(failing):
        archive.youtube.add(youtube_id)
        archive.youtube.download_failures[youtube_id] = wrong[number % 2]
    upcoming = ["premiere001", "premiere002"]
    for youtube_id in upcoming:
        archive.youtube.add(youtube_id, live_status="is_upcoming")
    queue_stopped(archive, [*failing, *upcoming])
    archive.wait(lambda: len(downloads(archive)) == len(failing) + len(upcoming))
    time.sleep(0.2)  # time enough for the worker to have moved on to another job
    assert not archive.gate.paused and archive.gate.refusals == 0


def test_the_rest_runs_from_when_a_download_finishes_not_only_from_when_it_began(
    archive, monkeypatch
):
    monkeypatch.setattr(pace, "REST", {**pace.REST, "download": (1.0, 1.0)})
    one_at_a_time(archive)
    for youtube_id in IDS[:2]:
        archive.youtube.add(youtube_id)
    archive.youtube.hold.set()
    first, second = (add(archive, youtube_id) for youtube_id in IDS[:2])
    archive.wait_job(first["job_id"], "running")
    time.sleep(1.3)  # the first outlasts the rest that began with it
    archive.youtube.hold.clear()
    archive.wait_job(first["job_id"])
    time.sleep(0.5)  # a rest counted from the start alone would be long over by now
    assert archive.job(second["job_id"])["status"] == "queued"
    archive.wait_job(second["job_id"])


def test_workers_that_look_for_a_job_in_the_same_moment_cannot_both_start_one(archive, monkeypatch):
    monkeypatch.setattr(pace, "REST", {**pace.REST, "download": (60.0, 60.0)})
    runner = archive.app.state.runner
    archive.call(runner.stop)
    assert (
        archive.client.put("/api/settings", json={"max_concurrent_downloads": 3}).status_code == 200
    )
    for youtube_id in IDS:
        archive.youtube.add(youtube_id)
        add(archive, youtube_id)
    archive.youtube.hold.set()
    archive.call(runner.start)  # all three workers reach for a job together

    archive.wait(lambda: archive.client.get("/api/jobs").json()["counts"]["running"])
    time.sleep(0.5)  # long enough for the others to have started too, if they could
    counts = archive.client.get("/api/jobs").json()["counts"]
    assert (counts["running"], counts["queued"]) == (1, 2)
    assert len(downloads(archive)) == 1
