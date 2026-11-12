"""What a download missed, subtitles and live chat, is fetched by a job of its own later."""

from app.youtube import Blocked, Paused, YouTubeError
from tests.fake_youtube import chat_line
from tests.test_bot_checks import BOT, RATE_LIMIT, pause, resume
from tests.test_details import archived, sidecar_of
from tests.test_library import VIDEO, add
from tests.test_scan import rescan

SUBTITLES = {"en": "English", "de": "German", "fr": "French"}


def queue_extras(archive, youtube_id=VIDEO, **options) -> int:
    video = next(
        v
        for v in archive.client.get("/api/videos").json()["items"]
        if v["youtube_id"] == youtube_id
    )
    return archive.call(
        lambda: archive.app.state.runner.enqueue(
            "extras", video_id=video["id"], origin="user", actor="owner", options=options
        )
    )


def detail(archive, youtube_id=VIDEO) -> dict:
    items = archive.client.get("/api/videos").json()["items"]
    video = next(v for v in items if v["youtube_id"] == youtube_id)
    return archive.client.get(f"/api/videos/{video['id']}").json()


def langs(video) -> list[str]:
    return [track["lang"] for track in video["subtitles"]]


def lose_subtitles(archive, **fields) -> dict:
    """A download whose subtitles YouTube refused, with the pause it started lifted, so that the
    extras job it queued is the only thing left to run once the refusal has been cleared."""
    archive.youtube.add(VIDEO, subtitles=SUBTITLES, refused_extras=RATE_LIMIT, **fields)
    video = add(archive, subtitle_languages=["en", "de"])
    archive.wait_job(video["job_id"])
    return video


def test_a_refused_subtitle_keeps_the_video_and_queues_a_job_that_waits_on_the_pause(archive):
    lose_subtitles(archive)
    gate = archive.gate
    assert gate.paused and gate.cause == "extras" and gate.refusals == 0

    video = detail(archive)
    assert video["status"] == "archived" and video["subtitles"] == []
    job = video["extras_job"]
    assert (job["state"], job["waiting_on"], job["waits_until"]) == (
        "waiting",
        "youtube",
        gate.resumes_at,
    )
    result = archive.job(1)["result"]
    assert result["extras_job"] == job["id"] and "refused" in result
    own = sidecar_of(archive, video)["_youhoard"]
    assert "refused" not in own and "extras_missing" not in own and own["subtitles"] == []
    queued = archive.events(job_id=job["id"])
    assert [(e["event"], e["actor"]) for e in queued] == [("job.queued", "app")]


def test_the_job_fetches_what_was_lost_and_places_it_with_the_media(archive):
    lose_subtitles(archive)
    archive.youtube.videos[VIDEO].refused_extras = None
    job_id = detail(archive)["extras_job"]["id"]
    resume(archive)
    done = archive.wait_job(job_id)
    assert done["result"] == {"saved": ["en", "de"], "chat": False, "missing": []}
    assert "Saved en, de" in archive.events(job_id=job_id)[0]["detail"]

    video = detail(archive)
    assert video["extras_job"] is None
    assert langs(video) == ["en", "de"] and [t["source"] for t in video["subtitles"]] == [
        "uploaded",
        "uploaded",
    ]
    media = archive.media / video["media_path"]
    for lang in ("en", "de"):
        assert (media.parent / f"{media.stem}.{lang}.vtt").read_text().startswith("WEBVTT")
    assert not list((archive.media / ".youhoard" / "incomplete").glob("*/*"))
    assert [t["lang"] for t in sidecar_of(archive, video)["_youhoard"]["subtitles"]] == [
        "en",
        "de",
    ]

    rescan(archive)
    assert langs(detail(archive)) == ["en", "de"]


def test_the_job_asks_only_for_what_is_not_already_there(archive):
    archive.youtube.add(VIDEO, subtitles=SUBTITLES, chat=[chat_line(0, "A", "hi")])
    archived(archive, subtitle_languages=["en"])
    wanted = {"subtitle_languages": ["en", "de"], "live_chat": True}
    done = archive.wait_job(queue_extras(archive, **wanted))
    assert done["result"] == {"saved": ["de"], "chat": True, "missing": []}
    assert "Saved de, live chat" in archive.events(job_id=done["id"])[0]["detail"]
    call = archive.youtube.calls[-1]
    assert call[0] == "extras" and call[2:] == ({"en"}, False)
    assert call[1].quality is None and call[1].comments is False
    video = detail(archive)
    assert langs(video) == ["en", "de"] and video["chat_url"]

    again = archive.wait_job(queue_extras(archive, **wanted))
    assert again["result"] == {"saved": [], "chat": False, "missing": []}
    assert "Nothing left to fetch" in archive.events(job_id=again["id"])[0]["detail"]
    assert archive.youtube.calls[-1][2:] == ({"en", "de"}, True)


def test_a_refusal_during_the_job_pauses_everything_and_marks_the_job_refused(archive):
    archive.youtube.add(VIDEO, subtitles=SUBTITLES)
    archived(archive, subtitle_languages=["en"])
    archive.youtube.videos[VIDEO].refused_extras = RATE_LIMIT
    job_id = queue_extras(archive, subtitle_languages=["en", "de"])
    job = archive.wait(lambda: (j := archive.job(job_id))["reason"] == "refused" and j)

    gate = archive.gate
    assert gate.paused and gate.cause == "extras" and gate.reason == RATE_LIMIT
    assert gate.refusals == 0
    assert (job["status"], job["state"], job["waiting_on"]) == ("queued", "waiting", "youtube")
    assert (job["refusals"], job["attempts"]) == (1, 0)
    assert langs(detail(archive)) == ["en"]
    assert not list((archive.media / ".youhoard" / "incomplete").glob("*/*"))

    archive.youtube.videos[VIDEO].refused_extras = None
    resume(archive)
    assert archive.wait_job(job_id)["result"]["saved"] == ["de"]


def test_a_bot_check_while_the_job_reads_the_video_pauses_everything(archive):
    archive.youtube.add(VIDEO, subtitles=SUBTITLES)
    archived(archive, subtitle_languages=["en"])
    archive.youtube.extras_failures[VIDEO] = Blocked(BOT)
    job_id = queue_extras(archive, subtitle_languages=["en", "de"])
    job = archive.wait(lambda: (j := archive.job(job_id))["reason"] == "refused" and j)
    assert archive.gate.paused and archive.gate.cause == "refused" and archive.gate.refusals == 1
    assert job["waiting_on"] == "youtube"


def test_a_failure_nothing_explains_is_retried_later(archive):
    archive.youtube.add(VIDEO, subtitles=SUBTITLES)
    archived(archive, subtitle_languages=["en"])
    archive.youtube.extras_failures[VIDEO] = YouTubeError("HTTP Error 503: Unavailable")
    job_id = queue_extras(archive, subtitle_languages=["en", "de"])
    job = archive.wait(lambda: (j := archive.job(job_id))["reason"] == "retry" and j)
    assert (job["status"], job["attempts"], job["max_attempts"]) == ("queued", 1, 4)
    assert not archive.gate.paused


def test_a_track_that_stays_missing_keeps_what_did_arrive_and_retries(archive):
    archive.youtube.add(VIDEO, subtitles=SUBTITLES, failing_subtitles={"de"})
    archived(archive, subtitle_languages=["en"])
    job_id = queue_extras(archive, subtitle_languages=["en", "de", "fr"])
    job = archive.wait(lambda: (j := archive.job(job_id))["reason"] == "retry" and j)
    assert job["error"] == "YouTube didn't serve de"
    assert langs(detail(archive)) == ["en", "fr"]  # fr was placed, de is asked for again


def test_translations_that_stay_missing_do_not_keep_the_job_going(archive):
    archive.youtube.add(
        VIDEO,
        subtitles={"en": "English"},
        automatic_captions={"fr": "French"},
        failing_subtitles={"fr"},
    )
    archived(archive, subtitle_languages=["en"])
    job_id = queue_extras(archive, subtitle_languages=["en", "fr"])
    done = archive.wait_job(job_id)
    assert done["result"] == {"saved": [], "chat": False, "missing": ["fr"]}
    assert "Nothing left to fetch; fr unavailable" in archive.events(job_id=job_id)[0]["detail"]


def test_a_pause_that_begins_during_the_job_returns_it_to_the_queue(archive):
    archive.youtube.add(VIDEO, subtitles=SUBTITLES)
    archived(archive, subtitle_languages=["en"])
    archive.youtube.extras_failures[VIDEO] = Paused("2999-01-01T00:00:00Z")
    job_id = queue_extras(archive, subtitle_languages=["en", "de"])
    archive.wait(lambda: any(e["event"] == "job.returned" for e in archive.events(job_id=job_id)))
    # It never tried, so nothing is spent: no retry, no failure, whatever it does next.
    names = {e["event"] for e in archive.events(job_id=job_id)}
    assert not names & {"job.retrying", "job.failed", "job.refused"}
    assert archive.job(job_id)["attempts"] <= 1


def test_a_video_that_is_no_longer_archived_has_nothing_to_fetch(archive):
    archive.youtube.add(VIDEO, subtitles=SUBTITLES)
    video = archived(archive, subtitle_languages=["en"])
    assert archive.client.delete(f"/api/videos/{video['id']}").status_code == 200
    queued = archive.call(
        lambda: archive.app.state.runner.enqueue(
            "extras", video_id=video["id"], origin="user", actor="owner"
        )
    )
    done = archive.wait_job(queued)
    assert done["result"] == {"skipped": "No longer archived"}
    assert archive.youtube.calls[-1][0] != "extras"


def test_a_download_missing_a_track_for_another_reason_queues_a_job_too(archive):
    archive.youtube.add(VIDEO, subtitles=SUBTITLES, failing_subtitles={"de"})
    video = add(archive, subtitle_languages=["en", "de"])
    result = archive.wait_job(video["job_id"])["result"]
    assert "refused" not in result and result["extras_job"]
    detail_text = archive.events(job_id=video["job_id"])[0]["detail"]
    assert detail_text.endswith("subtitles or chat to be fetched later")
    assert archive.job(result["extras_job"])["kind"] == "extras"
    assert not archive.gate.paused


def test_a_download_with_everything_saved_queues_nothing(archive):
    archive.youtube.add(VIDEO, subtitles=SUBTITLES)
    video = add(archive, subtitle_languages=["en", "de"])
    result = archive.wait_job(video["job_id"])["result"]
    assert "extras_job" not in result
    assert [job for job in archive.jobs() if job["kind"] == "extras"] == []


def test_the_extras_job_waits_out_a_pause_like_a_download(archive):
    archive.youtube.add(VIDEO, subtitles=SUBTITLES)
    archived(archive, subtitle_languages=["en"])
    pause(archive)
    job = archive.job(queue_extras(archive, subtitle_languages=["en", "de"]))
    assert (job["state"], job["waiting_on"]) == ("waiting", "youtube")
