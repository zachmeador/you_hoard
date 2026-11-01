"""The record of what happened: one append-only table, written only here, and read for the API.

Ids in an event are plain integers, not foreign keys, so the record outlives what it describes.
"""

import logging
from typing import Any, Literal

import aiosqlite

from app.db import Database, later

logger = logging.getLogger(__name__)

# Who caused it: the owner through the API, the app on its own, or the command line.
Actor = Literal["owner", "app", "cli"]
# The prefixes of the events in each group; any other event belongs to the "app" group.
GROUPS = {"jobs": ("job", "jobs"), "youtube": ("youtube",)}
# What the system page counts as YouTube refusing: the gate's own events and a job it turned away.
REFUSALS = ("youtube.refused", "youtube.extras_refused", "job.refused")


async def record(
    target: Database | aiosqlite.Connection,
    event: str,
    *,
    actor: Actor,
    job: dict[str, Any] | None = None,
    video_id: int | None = None,
    subscription_id: int | None = None,
    reason: str | None = None,
    detail: str | None = None,
    level: int = logging.INFO,
) -> None:
    """Add an event to the record and write it to the log, so the two can't disagree.

    Pass a connection to join the caller's transaction. A job fills in the ids it carries: a check's
    subscription, or for a download the subscription it came through.
    """
    job_id = job["id"] if job else None
    job_kind = job["kind"] if job else None
    if job:
        video_id = video_id or job["video_id"]
        subscription_id = (
            subscription_id or job["subscription_id"] or job.get("via_subscription_id")
        )
    await target.execute(
        "INSERT INTO events (event, actor, job_id, job_kind, video_id, subscription_id, reason, "
        "detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (event, actor, job_id, job_kind, video_id, subscription_id, reason, detail),
    )
    about = ", ".join(
        f"{name} {value}"
        for name, value in (("job", job_id), ("video", video_id), ("subscription", subscription_id))
        if value is not None
    )
    logger.log(
        level,
        "%s by %s%s%s%s",
        event,
        actor,
        f" ({about})" if about else "",
        f" [{reason}]" if reason else "",
        f": {detail}" if detail else "",
    )


async def list_events(
    db: Database,
    *,
    job_id: int | None = None,
    video_id: int | None = None,
    subscription_id: int | None = None,
    group: str | None = None,
    before: int | None = None,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int | None]:
    """The newest events first, and the id to pass as `before` for the next page, if there is one."""
    clauses: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("job_id", job_id),
        ("video_id", video_id),
        ("subscription_id", subscription_id),
    ):
        if value is not None:
            clauses.append(f"e.{column} = ?")
            params.append(value)
    if before is not None:
        clauses.append("e.id < ?")
        params.append(before)
    if group:
        # An event's group is the part of its name before the dot.
        prefix = "substr(e.event, 1, instr(e.event, '.') - 1)"
        if group in GROUPS:
            names, negation = GROUPS[group], ""
        else:
            names, negation = [name for members in GROUPS.values() for name in members], "NOT "
        clauses.append(f"{prefix} {negation}IN ({', '.join('?' for _ in names)})")
        params.extend(names)
    rows = await db.fetch_all(
        f"""SELECT e.*, v.title AS video_title, sub.title AS subscription_title
            FROM events e
            LEFT JOIN videos v ON v.id = e.video_id
            LEFT JOIN subscriptions sub ON sub.id = e.subscription_id
            WHERE {" AND ".join(clauses) or "1"}
            ORDER BY e.id DESC LIMIT ?""",
        [*params, limit + 1],
    )
    more = len(rows) > limit
    return rows[:limit], rows[limit - 1]["id"] if more else None


async def activity(db: Database) -> dict[str, Any]:
    """How much has been downloaded lately, and when YouTube last refused. Read from the record,
    so clearing finished jobs doesn't erase it."""
    completed = "event = 'job.completed' AND job_kind = 'download'"
    refused = ", ".join(f"'{event}'" for event in REFUSALS)
    return await db.fetch_one(
        f"""SELECT
                (SELECT count(*) FROM events WHERE {completed} AND at >= ?) AS downloads_last_hour,
                (SELECT count(*) FROM events WHERE {completed} AND at >= ?) AS downloads_last_day,
                (SELECT max(at) FROM events WHERE {completed}) AS last_download_at,
                (SELECT max(at) FROM events WHERE event IN ({refused})) AS last_refusal_at""",
        (later(hours=-1), later(hours=-24)),
    )
