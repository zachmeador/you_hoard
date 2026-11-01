"""The subscription check job: refresh a source's inventory, then apply its download policy."""

import threading
from typing import Any

import aiosqlite

from app import events
from app.artwork import save_channel_art
from app.db import dumps, fetch_all, fetch_one, loads, now
from app.events import Actor
from app.jobs import JobRunner, Priority, Reason
from app.library import ensure_video, upsert_channel
from app.youtube import NOT_READY, Cancelled, Source

ROUTINE_STOP_AFTER_KNOWN = 10
# The settings that decide which inventory entries the policy selects.
SELECTION = ("content_types", "download_policy", "recent_count")


async def refresh_channel(runner: JobRunner, channel_id: int, source: Source) -> None:
    """Bring a channel's row up to date from a listing of its tab, and save its art."""
    async with runner.db.transaction() as conn:
        await upsert_channel(
            conn,
            source.youtube_id,
            source.channel_name,
            source.channel_handle,
            source.description,
            source.subscriber_count,
            source.verified,
        )
    await save_channel_art(runner.db, runner.youtube, channel_id, source)


async def run_check(
    runner: JobRunner, job: dict[str, Any], cancel: threading.Event
) -> dict[str, Any]:
    db = runner.db
    sub = await db.fetch_one("SELECT * FROM subscriptions WHERE id = ?", (job["subscription_id"],))
    full_requested = bool((loads(job["options"]) or {}).get("full"))
    inventoried = set(loads(sub["inventoried_types"]))
    tabs = loads(sub["content_types"]) if sub["kind"] == "channel" else [None]
    result = {"listed": 0, "new_entries": 0, "removed": 0, "queued": 0, "full": False}
    channel_refreshed = False

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
        listing = await runner.youtube.list_entries(
            sub["kind"],
            sub["youtube_id"],
            video_type,
            known=known,
            stop_after_known=ROUTINE_STOP_AFTER_KNOWN,
            cancelled=cancel,
        )
        entries = listing.entries
        if listing.source and sub["channel_id"] and not channel_refreshed:
            channel_refreshed = True
            await refresh_channel(runner, sub["channel_id"], listing.source)
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
                               channel_youtube_id = coalesce(?, channel_youtube_id),
                               channel_name = coalesce(?, channel_name),
                               view_count = coalesce(?, view_count),
                               last_seen_at = ?, removed_at = NULL,
                               position = CASE WHEN ? THEN ? ELSE position END
                           WHERE subscription_id = ? AND youtube_id = ?""",
                        (
                            entry.title,
                            entry.duration,
                            entry.live_status,
                            entry.channel_youtube_id,
                            entry.channel_name,
                            entry.view_count,
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
                               title, duration, position, baseline, live_status,
                               channel_youtube_id, channel_name, view_count, first_seen_at,
                               last_seen_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            sub["id"],
                            entry.youtube_id,
                            entry.video_type,
                            entry.title,
                            entry.duration,
                            position,
                            first and entry.live_status not in NOT_READY,
                            entry.live_status,
                            entry.channel_youtube_id,
                            entry.channel_name,
                            entry.view_count,
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
        result["queued"] = await apply_policy(runner, conn, sub["id"], actor="app")
        await conn.execute(
            "UPDATE subscriptions SET last_checked_at = ? WHERE id = ?", (now(), sub["id"])
        )
    return result


async def entry_channel(
    conn: aiosqlite.Connection, sub: dict[str, Any], entry: dict[str, Any]
) -> int | None:
    """The channel a listed video belongs to: the channel's own, or a playlist entry's uploader."""
    if sub["channel_id"]:
        return sub["channel_id"]
    if entry["channel_youtube_id"]:
        return await upsert_channel(conn, entry["channel_youtube_id"], entry["channel_name"])
    return None


async def apply_policy(
    runner: JobRunner, conn: aiosqlite.Connection, subscription_id: int, *, actor: Actor
) -> int:
    """Queue downloads for inventory entries the policy selects and the library has never seen.

    The entry_selection view decides what the policy selects, including that a subscription that
    is off selects nothing, so no caller needs to check.
    """
    sub = await fetch_one(conn, "SELECT * FROM subscriptions WHERE id = ?", (subscription_id,))
    entries = await fetch_all(
        conn,
        """SELECT e.* FROM entry_selection e
           LEFT JOIN videos v ON v.youtube_id = e.youtube_id
           WHERE e.subscription_id = ? AND e.skip_reason IS NULL AND v.id IS NULL
           ORDER BY e.baseline, e.position""",
        (subscription_id,),
    )
    for entry in entries:
        video_id = await ensure_video(
            conn,
            entry["youtube_id"],
            entry["title"],
            entry["video_type"],
            channel_id=await entry_channel(conn, sub, entry),
            duration=entry["duration"],
        )
        await runner.enqueue(
            "download",
            video_id=video_id,
            via_subscription_id=sub["id"],
            origin="policy",
            actor=actor,
            conn=conn,
        )
    return len(entries)


def downloading(sub: dict[str, Any]) -> bool:
    """Whether a subscription's policy is queueing downloads: it is on and wants some."""
    return bool(sub["enabled"]) and sub["download_policy"] != "none"


async def subscription_changed(
    runner: JobRunner,
    conn: aiosqlite.Connection,
    before: dict[str, Any],
    subscription_id: int,
    *,
    actor: Actor,
) -> None:
    """Bring a subscription's downloads in line with a change just saved, in the same transaction.

    Switching it off, by disabling it or setting its policy to none, pauses the downloads its
    policy queued; switching it back on resumes exactly those. Downloads asked for by hand, and
    jobs the owner paused, are left alone either way. Off comes before anything is queued.
    """
    after = await fetch_one(conn, "SELECT * FROM subscriptions WHERE id = ?", (subscription_id,))
    if downloading(before) and not downloading(after):
        ids = await policy_downloads(conn, subscription_id, "queued")
        paused = await runner.pause_many(
            ids, actor=actor, reason=Reason.SUBSCRIPTION_OFF, conn=conn
        )
        detail = f"{paused} downloads paused"
        await events.record(
            conn, "subscription.off", actor=actor, subscription_id=subscription_id, detail=detail
        )
    elif downloading(after) and not downloading(before):
        ids = await policy_downloads(conn, subscription_id, "paused", Reason.SUBSCRIPTION_OFF)
        resumed = await runner.resume_many(ids, actor=actor, conn=conn)
        detail = f"{resumed} downloads resumed"
        await events.record(
            conn, "subscription.on", actor=actor, subscription_id=subscription_id, detail=detail
        )
    if any(before[key] != after[key] for key in SELECTION):
        await apply_policy(runner, conn, subscription_id, actor=actor)
        added = set(loads(after["content_types"])) - set(loads(before["content_types"]))
        if after["enabled"] and added:
            await runner.enqueue(
                "check",
                subscription_id=subscription_id,
                priority=Priority.ASKED,
                origin="user",
                actor=actor,
                conn=conn,
            )


async def policy_downloads(
    conn: aiosqlite.Connection, subscription_id: int, status: str, reason: Reason | None = None
) -> list[int]:
    """The ids of the downloads a subscription's policy queued that are in this status."""
    rows = await fetch_all(
        conn,
        "SELECT id FROM jobs WHERE kind = 'download' AND origin = 'policy' "
        "AND via_subscription_id = ? AND status = ? AND (? IS NULL OR reason = ?) ORDER BY id",
        (subscription_id, status, reason, reason),
    )
    return [row["id"] for row in rows]


async def queue_entry_download(
    runner: JobRunner,
    conn: aiosqlite.Connection,
    sub: dict[str, Any],
    entry: dict[str, Any],
    *,
    actor: Actor,
) -> tuple[int, int]:
    """An explicit download of one inventory entry, regardless of policy."""
    channel_id = await entry_channel(conn, sub, entry)
    video_id = await ensure_video(
        conn,
        entry["youtube_id"],
        entry["title"],
        entry["video_type"],
        channel_id=channel_id,
        duration=entry["duration"],
    )
    await conn.execute(
        "UPDATE videos SET deleted_at = NULL, channel_id = coalesce(channel_id, ?) WHERE id = ?",
        (channel_id, video_id),
    )
    job_id = await runner.enqueue(
        "download",
        video_id=video_id,
        via_subscription_id=sub["id"],
        priority=Priority.ASKED,
        origin="user",
        actor=actor,
        conn=conn,
    )
    return video_id, job_id
