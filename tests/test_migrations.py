"""Databases from the first release upgrade in place."""

import asyncio
import sqlite3
from pathlib import Path

import pytest

from app.db import MIGRATIONS, Database

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
        assert status["job_run_after"] is None and status["job_attempts"] is None
        pause = conn.execute("SELECT * FROM youtube_pause").fetchall()
        assert [tuple(row) for row in pause] == [(1, None, 0, None)]


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
