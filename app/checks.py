"""The subscription check job: refresh a source's inventory, then apply its download policy."""

import threading
from typing import Any

import aiosqlite

from app.db import dumps, fetch_all, fetch_one, loads, now
from app.jobs import JobRunner
from app.library import ensure_video
from app.youtube import NOT_READY, Cancelled

ROUTINE_STOP_AFTER_KNOWN = 10


async def run_check(
    runner: JobRunner, job: dict[str, Any], cancel: threading.Event
) -> dict[str, Any]:
    db = runner.db
    sub = await db.fetch_one("SELECT * FROM subscriptions WHERE id = ?", (job["subscription_id"],))
    full_requested = bool((loads(job["options"]) or {}).get("full"))
    inventoried = set(loads(sub["inventoried_types"]))
    tabs = loads(sub["content_types"]) if sub["kind"] == "channel" else [None]
    result = {"listed": 0, "new_entries": 0, "removed": 0, "queued": 0, "full": False}

    for video_type in tabs:
        if cancel.is_set():
            raise Cancelled("Cancelled")
        tab = video_type or "playlist"
        first = tab not in inventoried
        complete = first or full_requested or sub["kind"] == "playlist"
        known = None
        if not complete:
            rows = await db.fetch_all(
                "SELECT youtube_id FROM source_entries WHERE subscription_id = ? AND video_type = ?",
                (sub["id"], video_type),
            )
            known = {row["youtube_id"] for row in rows}
        entries = await runner.youtube.list_entries(
            sub["kind"],
            sub["youtube_id"],
            video_type,
            known=known,
            stop_after_known=ROUTINE_STOP_AFTER_KNOWN,
            cancelled=cancel,
        )
        stamp = now()
        async with db.transaction() as conn:
            for position, entry in enumerate(entries):
                existing = await fetch_one(
                    conn,
                    "SELECT 1 FROM source_entries WHERE subscription_id = ? AND youtube_id = ?",
                    (sub["id"], entry.youtube_id),
                )
                if existing:
                    await conn.execute(
                        """UPDATE source_entries SET title = coalesce(?, title),
                               duration = coalesce(?, duration), live_status = ?,
                               last_seen_at = ?, removed_at = NULL,
                               position = CASE WHEN ? THEN ? ELSE position END
                           WHERE subscription_id = ? AND youtube_id = ?""",
                        (
                            entry.title,
                            entry.duration,
                            entry.live_status,
                            stamp,
                            sub["kind"] == "playlist",
                            position,
                            sub["id"],
                            entry.youtube_id,
                        ),
                    )
                else:
                    await conn.execute(
                        """INSERT INTO source_entries (subscription_id, youtube_id, video_type,
                               title, duration, position, baseline, live_status, first_seen_at,
                               last_seen_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            sub["id"],
                            entry.youtube_id,
                            entry.video_type,
                            entry.title,
                            entry.duration,
                            position,
                            first and entry.live_status not in NOT_READY,
                            entry.live_status,
                            stamp,
                            stamp,
                        ),
                    )
                    if not first:
                        result["new_entries"] += 1
            if complete:
                cursor = await conn.execute(
                    """UPDATE source_entries SET removed_at = ?
                       WHERE subscription_id = ? AND removed_at IS NULL
                         AND (? IS NULL OR video_type = ?)
                         AND youtube_id NOT IN (SELECT value FROM json_each(?))""",
                    (
                        stamp,
                        sub["id"],
                        video_type,
                        video_type,
                        dumps([entry.youtube_id for entry in entries]),
                    ),
                )
                result["removed"] += cursor.rowcount
                inventoried.add(tab)
                await conn.execute(
                    "UPDATE subscriptions SET inventoried_types = ? WHERE id = ?",
                    (dumps(sorted(inventoried)), sub["id"]),
                )
        result["listed"] += len(entries)
        result["full"] = result["full"] or complete

    async with db.transaction() as conn:
        result["queued"] = await apply_policy(runner, conn, sub["id"])
        await conn.execute(
            "UPDATE subscriptions SET last_checked_at = ? WHERE id = ?", (now(), sub["id"])
        )
    return result


def subscription_download_options(sub: dict[str, Any]) -> dict[str, Any]:
    """Per-subscription overrides; anything left out falls back to library settings."""
    options = {
        "quality": sub["quality"],
        "subtitle_languages": loads(sub["subtitle_languages"]),
        "download_comments": None
        if sub["download_comments"] is None
        else bool(sub["download_comments"]),
    }
    return {key: value for key, value in options.items() if value is not None}


async def apply_policy(runner: JobRunner, conn: aiosqlite.Connection, subscription_id: int) -> int:
    """Queue downloads for inventory entries the policy selects and the library has never seen."""
    sub = await fetch_one(conn, "SELECT * FROM subscriptions WHERE id = ?", (subscription_id,))
    policy = sub["download_policy"]
    if policy == "none":
        return 0
    types = loads(sub["content_types"]) if sub["kind"] == "channel" else ["video", "short", "live"]
    placeholders = ", ".join("?" for _ in types)
    not_ready = ", ".join(f"'{status}'" for status in sorted(NOT_READY))
    entries = await fetch_all(
        conn,
        f"""SELECT e.* FROM source_entries e
            LEFT JOIN videos v ON v.youtube_id = e.youtube_id
            WHERE e.subscription_id = ? AND e.removed_at IS NULL AND v.id IS NULL
              AND coalesce(e.live_status, '') NOT IN ({not_ready})
              AND e.video_type IN ({placeholders})
              AND (? = 'all' OR e.baseline = 0 OR (? = 'recent' AND e.position < ?))
            ORDER BY e.baseline, e.position""",
        (subscription_id, *types, policy, policy, sub["recent_count"]),
    )
    options = subscription_download_options(sub)
    for entry in entries:
        video_id = await ensure_video(
            conn,
            entry["youtube_id"],
            entry["title"],
            entry["video_type"],
            channel_id=sub["channel_id"],
            duration=entry["duration"],
        )
        await runner.enqueue("download", video_id=video_id, options=options, conn=conn)
    return len(entries)


async def queue_entry_download(
    runner: JobRunner, conn: aiosqlite.Connection, sub: dict[str, Any], entry: dict[str, Any]
) -> tuple[int, int]:
    """An explicit download of one inventory entry, regardless of policy."""
    video_id = await ensure_video(
        conn,
        entry["youtube_id"],
        entry["title"],
        entry["video_type"],
        channel_id=sub["channel_id"],
        duration=entry["duration"],
    )
    await conn.execute("UPDATE videos SET deleted_at = NULL WHERE id = ?", (video_id,))
    job_id = await runner.enqueue(
        "download",
        video_id=video_id,
        options=subscription_download_options(sub),
        priority=5,
        conn=conn,
    )
    return video_id, job_id
