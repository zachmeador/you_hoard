"""Databases from the first release upgrade in place."""

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import youtube
from app.config import config
from app.db import MIGRATIONS, Database
from main import create_app
from tests.fake_youtube import FakeYouTube

BOT_CHECK = "[youtube] oldvideo001: Sign in to confirm you’re not a bot."
FAR_OFF = "2999-01-01T00:00:00Z"
PAST = "2000-01-01T00:00:00Z"


def test_a_version_one_database_gains_the_new_columns_and_keeps_its_rows(tmp_path: Path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript((MIGRATIONS / "001_initial.sql").read_text())
        conn.execute("INSERT INTO channels (youtube_id, name) VALUES ('UCold', 'Old channel')")
        conn.execute(
            "INSERT INTO videos (youtube_id, channel_id, title, published_at, media_path) "
            "VALUES ('oldvideo001', 1, 'Old video', '2020-02-02', 'Old/old.mp4')"
        )
        conn.execute(
            "INSERT INTO subscriptions (kind, youtube_id, title, channel_id, quality) "
            "VALUES ('channel', 'UCold', 'Old channel', 1, '720p')"
        )
        conn.execute(
            "INSERT INTO source_entries (subscription_id, youtube_id, position, baseline, "
            "first_seen_at, last_seen_at) VALUES (1, 'oldvideo001', 0, 1, 'then', 'then')"
        )
        conn.execute("PRAGMA user_version = 1")

    database = Database(path)
    asyncio.run(database.migrate())
    asyncio.run(database.migrate())  # a second start changes nothing

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("PRAGMA user_version").fetchone()[0] >= 2
        video = conn.execute("SELECT * FROM videos").fetchone()
        assert video["title"] == "Old video" and video["published_at"] == "2020-02-02"
        for column in ("availability", "age_limit", "fps", "vcodec", "acodec", "dynamic_range"):
            assert video[column] is None, column
        assert video["audio_languages"] is None and video["subtitle_tracks"] is None
        channel = conn.execute("SELECT * FROM channels").fetchone()
        assert channel["verified"] == 0 and channel["avatar_path"] is None
        subscription = conn.execute("SELECT * FROM subscriptions").fetchone()
        assert subscription["quality"] == "720p"
        for column in ("audio_languages", "auto_captions", "live_chat", "sponsorblock"):
            assert subscription[column] is None, column
        entry = conn.execute("SELECT * FROM source_entries").fetchone()
        assert entry["channel_name"] is None and entry["view_count"] is None
        status = conn.execute("SELECT * FROM video_status").fetchone()
        assert status["status"] == "archived"
        assert status["job_waits_until"] is None and status["job_attempts"] is None
        pause = conn.execute("SELECT * FROM youtube_pause").fetchall()
        assert [tuple(row) for row in pause] == [(1, None, 0, None, None)]


def pause_after_upgrading(path: Path, error: str | None, run_after: str, status: str = "queued"):
    """A version 3 database with one job, after the upgrade that saves the pause."""
    with sqlite3.connect(path) as conn:
        for name in ("001_initial", "002_archive_details", "003_video_job_state"):
            conn.executescript((MIGRATIONS / f"{name}.sql").read_text())
        conn.execute("INSERT INTO videos (youtube_id, title) VALUES ('oldvideo001', 'Old video')")
        conn.execute(
            "INSERT INTO jobs (kind, video_id, status, error, run_after) "
            "VALUES ('download', 1, ?, ?, ?)",
            (status, error, run_after),
        )
        conn.execute("PRAGMA user_version = 3")
    asyncio.run(Database(path).migrate())
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT paused_until, refusals, reason FROM youtube_pause").fetchone()


def test_a_pause_running_during_the_upgrade_carries_over(tmp_path: Path):
    pause = pause_after_upgrading(tmp_path / "old.db", BOT_CHECK, FAR_OFF)
    assert pause == (FAR_OFF, 1, BOT_CHECK)


@pytest.mark.parametrize(
    ("error", "run_after", "status"),
    [
        (BOT_CHECK, PAST, "queued"),
        (BOT_CHECK, FAR_OFF, "failed"),
        ("HTTP Error 500: Internal Server Error", FAR_OFF, "queued"),
        (None, FAR_OFF, "queued"),
    ],
    ids=["already over", "not queued", "a retry", "a premiere"],
)
def test_other_waits_are_not_a_pause(tmp_path: Path, error, run_after, status):
    pause = pause_after_upgrading(tmp_path / "old.db", error, run_after, status)
    assert pause == (None, 0, None)


PAUSE = "2999-01-01T00:00:00Z"
AGE_GATE = "Sign in to confirm your age. This video may be inappropriate for some users."
CAPTCHA_GONE = "Video unavailable. YouTube is requiring a captcha challenge before playback"
STOPPED_SCAN = "Rescan stopped: 12 of 20 archived videos aren't in the media folder (/media)."


def old_job(conn: sqlite3.Connection, kind: str, status: str, video: int | None = None, **fields):
    """A job as version 4 stores it. Returns its id."""
    columns = {
        "kind": kind,
        "status": status,
        "video_id": video,
        "subscription_id": 1 if kind == "check" else None,
        **fields,
    }
    cursor = conn.execute(
        f"INSERT INTO jobs ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        tuple(columns.values()),
    )
    return cursor.lastrowid


def stalled(path: Path) -> dict[str, int]:
    """A version 4 database as a deployment left it after days stalled behind a pause: jobs paused
    before anything recorded why, queued jobs holding the pause as their own wait, jobs that
    failed on a bot check, a download for a subscription deleted since, and finished jobs.
    Returns the jobs' ids by what they are."""
    with sqlite3.connect(path) as conn:
        for name in (
            "001_initial",
            "002_archive_details",
            "003_video_job_state",
            "004_youtube_pause",
        ):
            conn.executescript((MIGRATIONS / f"{name}.sql").read_text())
        conn.execute(
            "UPDATE youtube_pause SET paused_until = ?, refusals = 2, reason = ?",
            (PAUSE, BOT_CHECK),
        )
        conn.execute("INSERT INTO channels (youtube_id, name) VALUES ('UCold', 'Old channel')")
        conn.execute(
            "INSERT INTO subscriptions (id, kind, youtube_id, title, channel_id) "
            "VALUES (1, 'channel', 'UCold', 'Old channel', 1)"
        )
        for number in range(1, 21):
            conn.execute(
                "INSERT INTO videos (youtube_id, title) VALUES (?, ?)",
                (f"oldvideo{number:03d}", f"Old video {number}"),
            )
        policy = json.dumps({"subscription_id": 1})
        deleted = json.dumps({"subscription_id": 99, "quality": "720p"})
        done = "2026-10-01T00:00:{:02d}Z".format
        jobs = {
            # Paused before reasons existed: one from a policy, one the owner asked for.
            "paused by policy": old_job(conn, "download", "paused", 1, options=policy),
            "paused by hand": old_job(conn, "download", "paused", 2, options=policy, priority=5),
            # Held by the pause: the one YouTube refused, one with nothing recorded, and a check.
            "refused": old_job(
                conn,
                "download",
                "queued",
                3,
                options=policy,
                error=BOT_CHECK,
                run_after=PAUSE,
                priority=-2,
            ),
            "held": old_job(conn, "download", "queued", 4, run_after=PAUSE),
            "held check": old_job(conn, "check", "queued", run_after=PAUSE),
            # Waits of their own, which outlast the pause.
            "retry": old_job(
                conn,
                "download",
                "queued",
                5,
                error="HTTP Error 503",
                run_after="2999-06-01T00:00:00Z",
            ),
            "premiere": old_job(
                conn,
                "download",
                "queued",
                6,
                error="Not available for download yet (is upcoming)",
                run_after="2999-03-01T00:00:00Z",
            ),
            # A download whose subscription is gone, and a plain one.
            "orphan": old_job(conn, "download", "queued", 7, options=deleted),
            "plain": old_job(conn, "download", "queued", 8),
            # Paused while the pause lasted, which copied it onto them, and paused in a backoff.
            "paused in the pause": old_job(
                conn, "download", "paused", 16, options=policy, error=BOT_CHECK, run_after=PAUSE
            ),
            "paused in a backoff": old_job(
                conn,
                "download",
                "paused",
                17,
                error="HTTP Error 503",
                run_after="2999-07-01T00:00:00Z",
            ),
            # Under way when the app stopped.
            "running": old_job(
                conn, "download", "running", 18, started_at="2026-10-01T00:00:00Z", attempts=1
            ),
            # Finished, oldest first by when they finished.
            "cancelled": old_job(conn, "download", "cancelled", 9, finished_at=done(1)),
            "completed": old_job(conn, "download", "completed", 10, finished_at=done(2)),
            "bot check": old_job(
                conn, "download", "failed", 11, error=BOT_CHECK, finished_at=done(3)
            ),
            "captcha": old_job(
                conn, "download", "failed", 12, error=CAPTCHA_GONE, finished_at=done(4)
            ),
            "private": old_job(
                conn, "download", "failed", 13, error="Private video", finished_at=done(5)
            ),
            "age gate": old_job(
                conn, "download", "failed", 14, error=AGE_GATE, finished_at=done(6)
            ),
            "broken": old_job(
                conn, "download", "failed", 15, error="ffmpeg exploded", finished_at=done(7)
            ),
            "stopped scan": old_job(
                conn, "scan", "failed", error=STOPPED_SCAN, finished_at=done(8)
            ),
            "completed check": old_job(conn, "check", "completed", priority=5, finished_at=done(9)),
            "completed scan": old_job(conn, "scan", "completed", finished_at=done(10)),
        }
        conn.execute("PRAGMA user_version = 4")
    return jobs


class Upgraded:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.ids = stalled(path)
        asyncio.run(Database(path).migrate())
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row

    def job(self, name: str) -> sqlite3.Row:
        return self.conn.execute("SELECT * FROM jobs WHERE id = ?", (self.ids[name],)).fetchone()


@pytest.fixture
def upgraded(tmp_path: Path):
    database = Upgraded(tmp_path / "stalled.db")
    yield database
    database.conn.close()


def column(conn, sql: str, params: tuple = ()) -> list:
    return [row[0] for row in conn.execute(sql, params)]


def test_a_database_stalled_behind_a_pause_carries_across(upgraded):
    conn = upgraded.conn
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    pause = conn.execute("SELECT paused_until, refusals, reason FROM youtube_pause").fetchone()
    assert tuple(pause) == (PAUSE, 2, BOT_CHECK)  # the pause itself is untouched
    assert column(conn, "SELECT cause FROM youtube_pause") == ["refused"]
    assert column(conn, "SELECT count(*) FROM jobs") == [len(upgraded.ids)]
    assert column(conn, "SELECT id FROM jobs ORDER BY id") == sorted(upgraded.ids.values())

    def traits(name):
        job = upgraded.job(name)
        return (
            job["status"],
            job["origin"],
            job["reason"],
            job["via_subscription_id"],
            job["run_after"],
        )

    # Paused jobs keep their status and stay without a reason: nothing recorded one.
    assert traits("paused by policy") == ("paused", "policy", None, 1, None)
    assert traits("paused by hand") == ("paused", "user", None, 1, None)
    # The pause copied onto queued jobs is gone, and so is what it said; a wait of the job's own
    # stays, and says whether it is a retry or a premiere.
    assert traits("refused") == ("queued", "policy", "refused", 1, None)
    assert traits("held") == ("queued", "user", None, None, None)
    assert traits("held check") == ("queued", "schedule", None, None, None)
    assert traits("retry") == ("queued", "user", "retry", None, "2999-06-01T00:00:00Z")
    assert traits("premiere") == ("queued", "user", "premiere", None, "2999-03-01T00:00:00Z")
    # A subscription that no longer exists is not kept as a link, and the key leaves the options.
    assert traits("orphan") == ("queued", "policy", None, None, None)
    assert json.loads(upgraded.job("orphan")["options"]) == {"quality": "720p"}
    assert json.loads(upgraded.job("paused by policy")["options"]) == {}
    assert traits("plain")[:2] == ("queued", "user")
    # Asking for a check by hand gave it a priority; a scan is always the owner's.
    assert upgraded.job("completed check")["origin"] == "user"
    assert (
        upgraded.job("stopped scan")["origin"] == upgraded.job("completed scan")["origin"] == "user"
    )
    # What the old code did to a refused job's priority is replaced by a count of refusals, of at
    # least one wherever the error says YouTube refused it.
    refused = {row["id"] for row in conn.execute("SELECT id FROM jobs WHERE refusals > 0")}
    assert refused == {upgraded.ids["refused"], upgraded.ids["paused in the pause"]}
    assert upgraded.job("refused")["priority"] == 0
    assert (traits("paused in the pause")) == ("paused", "policy", None, 1, None)
    assert traits("paused in a backoff") == ("paused", "user", None, None, "2999-07-01T00:00:00Z")
    # A paused job remembers what it was waiting for, so that resuming doesn't forget it.
    assert [
        upgraded.job(name)["resume_reason"]
        for name in ("paused in the pause", "paused in a backoff", "paused by policy", "refused")
    ] == ["refused", "retry", None, None]
    # Why finished jobs failed. Refusals are errors to retry, never gone, even when a message
    # also says "video unavailable".
    failed = ("bot check", "captcha", "private", "age gate", "broken", "stopped scan")
    assert [upgraded.job(name)["reason"] for name in failed] == [
        "error",
        "error",
        "gone",
        "needs_account",
        "error",
        "declined",
    ]
    done = ("cancelled", "completed", "completed check", "completed scan")
    assert [upgraded.job(name)["reason"] for name in done] == [None] * 4


def test_a_stalled_job_reads_as_waiting_on_youtube_without_anything_copied_to_it(upgraded):
    states = {
        row["job_id"]: row
        for row in upgraded.conn.execute(
            "SELECT job_id, job_state, job_waiting_on, job_waits_until, status "
            "FROM video_status WHERE job_id IS NOT NULL"
        )
    }

    def state(name):
        row = states[upgraded.ids[name]]
        return row["job_state"], row["job_waiting_on"], row["job_waits_until"]

    assert state("refused") == ("waiting", "youtube", PAUSE)
    assert state("held") == ("waiting", "youtube", PAUSE)
    assert state("retry") == ("waiting", "retry", "2999-06-01T00:00:00Z")
    assert state("premiere") == ("waiting", "premiere", "2999-03-01T00:00:00Z")
    assert state("paused by policy") == ("paused", None, None)
    assert states[upgraded.ids["plain"]]["status"] == "queued"


def test_finished_jobs_become_events_in_the_order_they_finished(upgraded):
    events = upgraded.conn.execute(
        "SELECT at, event, actor, job_id, job_kind, video_id, subscription_id, reason, detail "
        "FROM events ORDER BY id"
    ).fetchall()
    finished = (
        "cancelled",
        "completed",
        "bot check",
        "captcha",
        "private",
        "age gate",
        "broken",
        "stopped scan",
        "completed check",
        "completed scan",
    )
    assert [(e["event"], e["job_id"]) for e in events] == [
        (event, upgraded.ids[name])
        for event, name in zip(
            [
                "job.cancelled",
                "job.completed",
                *["job.failed"] * 6,
                "job.completed",
                "job.completed",
            ],
            finished,
            strict=True,
        )
    ]
    assert [e["at"] for e in events] == sorted(e["at"] for e in events)
    by_name = dict(zip(finished, events, strict=True))
    assert by_name["cancelled"]["actor"] == "owner"
    assert {e["actor"] for name, e in by_name.items() if name != "cancelled"} == {"app"}
    bot = by_name["bot check"]
    assert (bot["reason"], bot["detail"], bot["job_kind"]) == ("error", BOT_CHECK, "download")
    assert (by_name["private"]["reason"], by_name["stopped scan"]["reason"]) == ("gone", "declined")
    assert (by_name["completed"]["reason"], by_name["completed"]["detail"]) == (None, None)
    check = by_name["completed check"]
    assert (check["job_kind"], check["subscription_id"], check["video_id"]) == ("check", 1, None)
    assert by_name["completed scan"]["job_kind"] == "scan"


def test_the_error_text_alone_decides_what_a_job_waits_or_failed_for(tmp_path: Path):
    """Every phrase the classifier knows is read the same way here, with the classifier's order."""
    cases = [("queued", "premiere", phrase, youtube.NotReady) for phrase in youtube.WAITING]
    cases += [("queued", "refused", phrase, youtube.Blocked) for phrase in youtube.BLOCKED]
    cases += [
        ("failed", "needs_account", phrase, youtube.Inaccessible) for phrase in youtube.INACCESSIBLE
    ]
    cases += [("failed", "gone", phrase, youtube.Unavailable) for phrase in youtube.GONE]
    path = tmp_path / "phrases.db"
    stalled(path)
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM jobs")
        for number, (status, _, phrase, _) in enumerate(cases, start=1):
            conn.execute(
                "INSERT INTO videos (youtube_id, title) VALUES (?, 'x')", (f"phrase{number:05d}",)
            )
            old_job(
                conn,
                "download",
                status,
                20 + number,
                error=f"ERROR: [youtube] x: {phrase.title()} etc",
                finished_at="2026-10-01T00:00:00Z" if status == "failed" else None,
            )
    asyncio.run(Database(path).migrate())
    with sqlite3.connect(path) as conn:
        reasons = column(conn, "SELECT reason FROM jobs ORDER BY id")
    assert reasons == [reason for _, reason, _, _ in cases]
    for _, _, phrase, kind in cases:
        assert type(youtube.classify(Exception(f"ERROR: x: {phrase.title()} etc"))) is kind


def test_job_ids_are_not_reused_even_after_the_newest_job_is_deleted(upgraded):
    conn = upgraded.conn
    newest = max(upgraded.ids.values())
    conn.execute("DELETE FROM jobs WHERE id = ?", (newest,))
    conn.execute("INSERT INTO jobs (kind, origin) VALUES ('scan', 'user')")
    assert column(conn, "SELECT max(id) FROM jobs") == [newest + 1]


def test_a_fresh_database_and_an_upgraded_one_have_the_same_shape(tmp_path: Path, upgraded):
    fresh = tmp_path / "fresh.db"
    asyncio.run(Database(fresh).migrate())

    def shape(conn):
        tables = ("jobs", "events", "videos", "subscriptions", "youtube_pause")
        return {
            table: [tuple(row[1:3]) for row in conn.execute(f"PRAGMA table_info({table})")]
            for table in tables
        }

    def names(conn):
        sql = "SELECT name FROM sqlite_master WHERE type IN ('index', 'view', 'table')"
        return sorted(column(conn, sql))

    with sqlite3.connect(fresh) as conn:
        assert shape(conn) == shape(upgraded.conn)
        assert names(conn) == names(upgraded.conn)


def test_views_are_rebuilt_from_their_file_at_every_start(upgraded):
    conn = upgraded.conn
    conn.executescript("DROP VIEW job_state; CREATE VIEW job_state AS SELECT 1 AS wrong;")
    conn.executescript("DROP VIEW video_status; CREATE VIEW stale AS SELECT 1;")
    asyncio.run(Database(upgraded.path).migrate())
    views = column(conn, "SELECT name FROM sqlite_master WHERE type = 'view' ORDER BY name")
    assert views == ["entry_selection", "job_state", "video_status"]
    assert "state" in [row[1] for row in conn.execute("PRAGMA table_info(job_state)")]
    assert column(conn, "SELECT count(*) FROM job_state") == [len(upgraded.ids)]


def test_the_app_starts_on_a_stalled_database_and_says_what_waits_and_why(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path / "media")
    config.database_path.parent.mkdir(parents=True)
    ids = stalled(config.database_path)
    with TestClient(create_app(youtube=FakeYouTube())) as client:
        setup = client.post(
            "/api/auth/setup", json={"username": "owner", "password": "correct horse"}
        )
        assert setup.status_code == 200, setup.text
        listing = client.get("/api/jobs", params={"limit": 200}).json()
        jobs = {job["id"]: job for job in listing["items"]}

        def state(name):
            job = jobs[ids[name]]
            return job["state"], job["waiting_on"], job["waits_until"], job["reason"]

        # The saved pause still holds, and every job it holds says so without a copy of it.
        assert listing["youtube_paused_until"] == PAUSE and listing["youtube_refusals"] == 2
        assert state("refused") == ("waiting", "youtube", PAUSE, "refused")
        assert state("held") == ("waiting", "youtube", PAUSE, None)
        assert state("retry")[:3] == ("waiting", "retry", "2999-06-01T00:00:00Z")
        assert state("premiere")[:3] == ("waiting", "premiere", "2999-03-01T00:00:00Z")
        # The job that was running when the app stopped is back in the queue, behind the pause.
        assert state("running")[:3] == ("waiting", "youtube", PAUSE)
        assert jobs[ids["running"]]["attempts"] == 0
        counts = listing["counts"]
        assert (counts["waiting"], counts["paused"], counts["failed"]) == (8, 4, 6)
        assert (counts["completed"], counts["cancelled"], counts["running"]) == (3, 1, 0)

        # Resuming a job paused in a backoff brings back what it was waiting for.
        paused = ids["paused in a backoff"]
        assert client.post(f"/api/jobs/{paused}/resume").status_code == 200
        resumed = next(
            job for job in client.get("/api/jobs").json()["items"] if job["id"] == paused
        )
        assert (resumed["state"], resumed["reason"], resumed["waiting_on"]) == (
            "waiting",
            "retry",
            "retry",
        )
        # The record has the old history, then the start, then what the start did.
        events = [
            e["event"]
            for e in reversed(client.get("/api/events", params={"limit": 50}).json()["items"])
        ]
        assert events[:10].count("job.failed") == 6
        assert events[10:13] == ["app.started", "job.returned", "job.resumed"]
