"""A bot check pauses all YouTube work, and downloads rest between one another."""

import asyncio
import contextlib
import logging
import time

import pytest
from yt_dlp.utils import DownloadError

from app import jobs
from app.gate import Paused, YouTubeGate
from app.youtube import Blocked, Inaccessible, Unavailable, YouTubeError, classify
from tests.fake_youtube import AVATAR, AVATAR_URL, CHANNEL_ID
from tests.test_details import sidecar_of
from tests.test_jobs import hold_queue
from tests.test_library import VIDEO, add
from tests.test_subscriptions import CHANNEL_URL, check, ids, seed_tab, subscribe

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
    archive.wait(lambda: all(archive.job(video["job_id"])["run_after"] for video in videos))
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
        assert job["status"] == "queued" and job["run_after"] == resumes
    first = archive.job(videos[0]["job_id"])
    assert first["attempts"] == 0 and first["error"] == BOT  # the block isn't the job's fault

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


def test_a_lookup_that_succeeds_resets_the_backoff(archive):
    archive.youtube.add(VIDEO)

    def look_up() -> None:
        response = archive.client.post("/api/videos/resolve", json={"url": VIDEO})
        assert response.status_code == 200, response.text

    assert 3590 < second_pause(archive, look_up) <= 3600


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


def test_a_refused_subtitle_keeps_the_video_and_holds_the_next_one(archive):
    kept, next_up = IDS[:2]
    archive.youtube.add(kept, refused_extras=RATE_LIMIT)
    first, second = queue_stopped(archive, [kept, next_up])
    archive.wait_job(first["job_id"])

    gate = archive.gate
    assert gate.paused and gate.refusals == 1 and gate.reason == RATE_LIMIT
    time.sleep(0.2)  # time enough for the worker to have moved on to the next job
    assert downloads(archive) == [kept]
    waiting = archive.job(second["job_id"])
    assert waiting["status"] == "queued" and waiting["run_after"] == gate.resumes_at
    video = archive.client.get(f"/api/videos/{first['id']}").json()
    assert "refused" not in sidecar_of(archive, video)["_youhoard"]


def test_a_download_with_refused_extras_does_not_reset_the_backoff(archive):
    video = ids("vid", 1)[0]
    seed_tab(archive, "video", [video])
    sub = subscribe(archive)
    archive.youtube.videos[video].refused_extras = RATE_LIMIT
    refuse(archive)
    resume(archive)
    queued = archive.client.post(f"/api/subscriptions/{sub['id']}/entries/{video}/download")
    archive.wait_job(queued.json()["job_id"])
    assert 7190 < paused_for(archive.gate) <= 7200 and archive.gate.refusals == 2


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
    logged = [record for record in caplog.records if "asked for a bot check;" in record.message]
    assert len(logged) == 1


def test_the_pause_and_the_backoff_survive_a_restart(archive):
    refuse(archive)
    gate = archive.gate

    restarted = reloaded(archive)
    assert restarted.paused and restarted.resumes_at == gate.resumes_at
    assert abs(restarted.paused_until - gate.paused_until) < 1
    assert (restarted.refusals, restarted.reason) == (1, BOT)
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
    assert job["run_after"] == archive.gate.resumes_at


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
    assert job["status"] == "queued" and job["run_after"] == gate.resumes_at
    response = archive.client.post("/api/videos/resolve", json={"url": LOOKUP})
    assert response.status_code == 503

    status = archive.client.get("/api/jobs").json()
    assert status["youtube_paused_until"] == gate.resumes_at
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
    assert job["status"] == "queued" and job["run_after"] == archive.gate.resumes_at


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
        assert job["status"] == "queued" and job["run_after"] == gate.resumes_at
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
    job = archive.wait(lambda: (job := archive.job(queued["job_id"]))["run_after"] and job)

    assert job["status"] == "queued" and job["run_after"] == gate.resumes_at
    assert job["attempts"] == 0 and job["error"] == BOT
    assert archive.client.get("/api/jobs").json()["counts"]["waiting"] == 1
    assert [call[2] for call in archive.youtube.calls if call[0] == "list"] == ["video"]


def test_checks_wait_out_a_pause_but_scans_still_run(archive):
    sub = subscribe(archive)
    runner = archive.app.state.runner
    archive.gate.paused_until = time.time() + 600
    queued = archive.client.post(f"/api/subscriptions/{sub['id']}/check").json()
    scan = archive.client.post("/api/library/rescan").json()
    archive.wait_job(scan["job_id"])
    job = archive.job(queued["job_id"])
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
