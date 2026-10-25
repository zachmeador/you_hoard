"""Databases from the first release upgrade in place."""

import asyncio
import sqlite3
from pathlib import Path

from app.db import MIGRATIONS, Database


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
        status = conn.execute("SELECT status FROM video_status").fetchone()
        assert status["status"] == "archived"
