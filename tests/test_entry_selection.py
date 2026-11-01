"""The entry_selection view labels why a policy skips an entry, and selects what the policy did."""

import asyncio
import json
import re
import sqlite3
from collections.abc import Iterator
from itertools import count, product
from pathlib import Path

import pytest

from app.db import MIGRATIONS, VIEWS, Database
from app.youtube import NOT_READY
from tests.test_subscriptions import ids, seed_tab, subscribe

LIVE_STATUSES = (None, "not_live", "was_live", "is_upcoming", "is_live", "post_live")
TYPES = ("video", "short", "live")
POLICIES = ("none", "new", "recent", "all")
TABS = (["video"], ["video", "short"], ["short", "live"], ["video", "short", "live"])
RECENT = 2


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    path = tmp_path / "selection.db"
    asyncio.run(Database(path).migrate())
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


serial = count(1)


def add_subscription(conn, kind="channel", policy="new", tabs=("video",), enabled=1) -> int:
    cursor = conn.execute(
        "INSERT INTO subscriptions (kind, youtube_id, title, content_types, download_policy, "
        "recent_count, enabled) VALUES (?, ?, 'S', ?, ?, ?, ?)",
        (kind, f"source{next(serial):05d}", json.dumps(list(tabs)), policy, RECENT, enabled),
    )
    return cursor.lastrowid


def add_entry(conn, subscription_id, video_type="video", live_status=None, **fields) -> str:
    youtube_id = f"entry{next(serial):06d}"
    values = {
        "subscription_id": subscription_id,
        "youtube_id": youtube_id,
        "video_type": video_type,
        "live_status": live_status,
        "position": 0,
        "baseline": 0,
        "first_seen_at": "then",
        "last_seen_at": "then",
        **fields,
    }
    conn.execute(
        f"INSERT INTO source_entries ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)})",
        tuple(values.values()),
    )
    return youtube_id


def reasons(conn, subscription_id) -> dict[str, str | None]:
    rows = conn.execute(
        "SELECT youtube_id, skip_reason FROM entry_selection WHERE subscription_id = ?",
        (subscription_id,),
    )
    return {row["youtube_id"]: row["skip_reason"] for row in rows}


def selected_before(conn, subscription) -> set[str]:
    """What apply_policy's WHERE clause selected before the view took the rule over."""
    policy = subscription["download_policy"]
    if policy == "none":
        return set()
    if subscription["kind"] == "channel":
        types = json.loads(subscription["content_types"])
    else:
        types = ["video", "short", "live"]
    placeholders = ", ".join("?" for _ in types)
    not_ready = ", ".join(f"'{status}'" for status in sorted(NOT_READY))
    rows = conn.execute(
        f"""SELECT e.youtube_id FROM source_entries e
            LEFT JOIN videos v ON v.youtube_id = e.youtube_id
            WHERE e.subscription_id = ? AND e.removed_at IS NULL AND v.id IS NULL
              AND coalesce(e.live_status, '') NOT IN ({not_ready})
              AND e.video_type IN ({placeholders})
              AND (? = 'all' OR e.baseline = 0 OR (? = 'recent' AND e.position < ?))""",
        (subscription["id"], *types, policy, policy, subscription["recent_count"]),
    )
    return {row["youtube_id"] for row in rows}


def selected_now(conn, subscription_id) -> set[str]:
    """What apply_policy selects now: the view says so, and the library has never seen it."""
    rows = conn.execute(
        """SELECT e.youtube_id FROM entry_selection e
           LEFT JOIN videos v ON v.youtube_id = e.youtube_id
           WHERE e.subscription_id = ? AND e.skip_reason IS NULL AND v.id IS NULL""",
        (subscription_id,),
    )
    return {row["youtube_id"] for row in rows}


def test_the_view_selects_exactly_what_the_policy_query_did(db):
    checked = 0
    for policy, tabs, kind in product(POLICIES, TABS, ("channel", "playlist")):
        subscription_id = add_subscription(db, kind, policy, tabs)
        for video_type, status, baseline, position, removed in product(
            TYPES, LIVE_STATUSES, (0, 1), (0, RECENT - 1, RECENT, 5), (False, True)
        ):
            youtube_id = add_entry(
                db,
                subscription_id,
                video_type,
                status,
                baseline=baseline,
                position=position,
                removed_at="gone" if removed else None,
            )
            if len(youtube_id) % 7 == 0 or position == 5 and baseline:
                # The library has some of them already, which the old query skipped as well.
                db.execute(
                    "INSERT INTO videos (youtube_id, title) VALUES (?, 'Known')", (youtube_id,)
                )
        subscription = dict(
            db.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)).fetchone()
        )
        before = selected_before(db, subscription)
        assert selected_now(db, subscription_id) == before, (policy, tabs, kind)
        checked += len(before)
    assert checked > 1000  # the comparison saw plenty of selected entries, not just empty sets


def test_each_entry_says_the_first_reason_the_policy_skips_it(db):
    nothing = add_subscription(db, policy="none")
    off = add_subscription(db, policy="all", enabled=0)
    channel = add_subscription(db, policy="recent", tabs=("video",))
    entries = {
        "policy_none": add_entry(db, nothing, removed_at="gone", live_status="is_live"),
        "subscription_off": add_entry(db, off, removed_at="gone", live_status="is_live"),
        "removed": add_entry(db, channel, "short", "is_live", removed_at="gone"),
        "not_ready": add_entry(db, channel, "short", "is_upcoming"),
        "tab_off": add_entry(db, channel, "short", "was_live", baseline=0),
        "before_subscribing": add_entry(db, channel, "video", baseline=1, position=RECENT),
        "recent": add_entry(db, channel, "video", baseline=1, position=RECENT - 1),
        "new": add_entry(db, channel, "video", baseline=0, position=9),
    }
    found = {**reasons(db, nothing), **reasons(db, off), **reasons(db, channel)}
    assert {name: found[youtube_id] for name, youtube_id in entries.items()} == {
        "policy_none": "policy_none",
        "subscription_off": "subscription_off",
        "removed": "removed",
        "not_ready": "not_ready",
        "tab_off": "tab_off",
        "before_subscribing": "before_subscribing",
        "recent": None,
        "new": None,
    }


def test_a_playlist_takes_every_type_and_a_policy_of_all_takes_old_entries(db):
    playlist = add_subscription(db, "playlist", "all", tabs=("video",))
    kinds = [add_entry(db, playlist, video_type, baseline=1) for video_type in TYPES]
    assert set(reasons(db, playlist).values()) == {None} and len(kinds) == 3


def test_not_ready_statuses_are_the_ones_the_view_holds_back(db):
    subscription = add_subscription(db, policy="all")
    held = {
        status: add_entry(db, subscription, live_status=status)
        for status in (*NOT_READY, None, "not_live", "was_live")
    }
    found = reasons(db, subscription)
    assert {status for status, youtube_id in held.items() if found[youtube_id] == "not_ready"} == (
        NOT_READY
    )


def test_the_views_file_names_the_same_not_ready_statuses_as_the_adapter():
    sql = VIEWS.read_text()
    clause = re.search(r"coalesce\(e\.live_status, ''\) IN \(([^)]*)\)", sql)
    assert clause, "entry_selection no longer tests live_status the way this test reads it"
    assert set(re.findall(r"'([a-z_]+)'", clause.group(1))) == NOT_READY


def test_the_view_is_in_the_file_migrations_never_define_it():
    for path in MIGRATIONS.glob("*.sql"):
        assert "entry_selection" not in path.read_text(), path.name


def test_entries_say_why_they_were_not_selected_until_the_library_picks_them_up(archive):
    seed_tab(archive, "video", ids("vid", 3))
    sub = subscribe(archive)
    path = f"/api/subscriptions/{sub['id']}/entries"
    entries = archive.client.get(path).json()["items"]
    assert {entry["skip_reason"] for entry in entries} == {"before_subscribing"}

    target = entries[0]["youtube_id"]
    archive.wait_job(archive.client.post(f"{path}/{target}/download").json()["job_id"])
    by_id = {e["youtube_id"]: e for e in archive.client.get(path).json()["items"]}
    assert by_id[target]["status"] == "archived" and by_id[target]["skip_reason"] is None

    archive.client.patch(f"/api/subscriptions/{sub['id']}", json={"download_policy": "none"})
    reasons_now = {
        e["youtube_id"]: e["skip_reason"] for e in archive.client.get(path).json()["items"]
    }
    assert reasons_now[target] is None
    assert {r for y, r in reasons_now.items() if y != target} == {"policy_none"}

    archive.client.patch(f"/api/subscriptions/{sub['id']}", json={"download_policy": "new"})
    archive.client.patch(f"/api/subscriptions/{sub['id']}", json={"content_types": ["short"]})
    tab = {e["youtube_id"]: e["skip_reason"] for e in archive.client.get(path).json()["items"]}
    assert {r for y, r in tab.items() if y != target} == {"tab_off"}
