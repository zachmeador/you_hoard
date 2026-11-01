"""Persistent job queue: download workers, one general worker, and the subscription scheduler.

This is the only code that writes the jobs table. Every status change goes through `_move`, which
checks it against `MOVES` and records it as an event in the same transaction.
"""

import asyncio
import logging
import random
import sqlite3
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import timedelta
from enum import IntEnum, StrEnum
from typing import Any, Literal

import aiosqlite

from app import events, pace, trash
from app.db import (
    Database,
    dumps,
    fetch_all,
    fetch_one,
    from_timestamp,
    iso,
    later,
    loads,
    now,
    parse_time,
    utcnow,
)
from app.events import Actor
from app.gate import YouTubeGate
from app.settings import Settings
from app.youtube import (
    Blocked,
    Cancelled,
    Inaccessible,
    NotReady,
    Paused,
    Unavailable,
    YouTubeError,
    is_generic,
)

logger = logging.getLogger(__name__)

MAX_DOWNLOAD_WORKERS = 8
TRASH_PURGE_SECONDS = 3600
# A queued job is waiting while something holds it back; see job_state in app/views.sql.
STATES = ("queued", "waiting", "paused", "running", "completed", "failed", "cancelled")
ACTIVE = ("queued", "paused", "running")
FINISHED = ("completed", "failed", "cancelled")
# Jobs that talk to YouTube, and so wait out a bot check. job_state applies the same rule.
YOUTUBE_KINDS = ("download", "check")
# The moves a job's status can make, and nothing else.
MOVES = {
    "queued": ("paused", "running", "cancelled"),
    "paused": ("queued", "cancelled"),
    "running": ("queued", "completed", "failed", "cancelled"),
    "failed": ("queued",),
    "cancelled": ("queued",),
    "completed": (),
}
# What runs next: jobs YouTube hasn't refused first, then the more urgent, then the older. The
# queries that use it name job_state `j`.
QUEUE_ORDER = "j.refusals, j.priority DESC, j.id"
# Events logged as warnings: the job didn't get what it asked for.
WARNINGS = ("job.refused", "job.retrying", "job.failed")

Origin = Literal["user", "policy", "schedule"]
Handler = Callable[["JobRunner", dict[str, Any], threading.Event], Awaitable[dict[str, Any]]]


class Priority(IntEnum):
    ROUTINE = 0  # what a subscription's policy or schedule queues
    SCAN = 1
    ASKED = 5  # something the owner asked for from a list
    URGENT = 10  # a video the owner added or downloaded by hand
    NOW = 20  # the owner said to run this one next


class Reason(StrEnum):
    """Why a job is in its current status."""

    # Paused
    ASKED = "asked"
    SUBSCRIPTION_OFF = "subscription_off"
    # Queued
    RETRY = "retry"
    PREMIERE = "premiere"
    REFUSED = "refused"
    # Failed
    GONE = "gone"
    NEEDS_ACCOUNT = "needs_account"
    DECLINED = "declined"
    ERROR = "error"


class Declined(Exception):
    """A job that declined to run; it fails with this message and isn't retried."""


class NotAllowed(Exception):
    """A change the job's status doesn't permit."""


class JobNotFound(Exception):
    pass


@dataclass
class Progress:
    phase: str = "downloading"
    percent: float | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    speed: float | None = None
    eta: int | None = None

    def update(self, data: dict[str, Any]) -> None:
        if data.get("status") == "processing":
            self.phase, self.speed, self.eta = "processing", None, None
            return
        if data.get("status") != "downloading":
            return
        self.phase = "downloading"
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        self.downloaded_bytes = data.get("downloaded_bytes")
        self.total_bytes = int(total) if total else None
        if total and self.downloaded_bytes is not None:
            self.percent = round(min(100.0, self.downloaded_bytes / total * 100), 1)
        self.speed = data.get("speed")
        self.eta = data.get("eta")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


JOB_SELECT = """
SELECT j.*, v.title AS video_title, v.youtube_id AS video_youtube_id,
       sub.title AS subscription_title, via.title AS via_subscription_title
FROM job_state j
LEFT JOIN videos v ON v.id = j.video_id
LEFT JOIN subscriptions sub ON sub.id = j.subscription_id
LEFT JOIN subscriptions via ON via.id = j.via_subscription_id
"""
# Under way first, then queued and waiting jobs as the worker will take them, then paused ones,
# then what has finished, newest first.
LIST_ORDER = f"""
ORDER BY CASE j.state WHEN 'running' THEN 0 WHEN 'queued' THEN 1 WHEN 'waiting' THEN 1
                      WHEN 'paused' THEN 2 WHEN 'failed' THEN 3 ELSE 4 END,
         CASE WHEN j.status IN {FINISHED} THEN coalesce(j.finished_at, j.created_at) END DESC,
         CASE WHEN j.status IN {FINISHED} THEN j.id END DESC,
         {QUEUE_ORDER}
"""
WAITING_ORDER = "ORDER BY j.wait_ends, j.id"


def max_attempts(kind: str) -> int:
    """How many tries a job gets: only the jobs that talk to YouTube are retried."""
    return len(pace.RETRY_DELAYS) + 1 if kind in YOUTUBE_KINDS else 1


def failure_reason(error: Exception) -> Reason:
    if isinstance(error, Unavailable):
        return Reason.GONE
    if isinstance(error, Inaccessible):
        return Reason.NEEDS_ACCOUNT
    if isinstance(error, Declined):
        return Reason.DECLINED
    return Reason.ERROR


def summary(kind: str, result: dict[str, Any]) -> str:
    """What a finished job did, in a line for the record."""
    if kind == "download":
        text = result.get("skipped") or (
            f"{result['height']}p" if result.get("height") else "Archived"
        )
        return f"{text}; subtitles or chat lost to a refusal" if result.get("refused") else text
    if kind == "check":
        return (
            f"{result['listed']} listed, {result['new_entries']} new, "
            f"{result['removed']} removed, {result['queued']} queued"
        )
    return (
        f"{result['files']} files, {result['added']} added, {result['relinked']} relinked, "
        f"{result['missing']} missing"
    )


def job_filter(states: Iterable[str] | None, kind: str | None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if states:
        wanted = list(dict.fromkeys(states))
        # The state is the rule. A waiting job is a queued one, which lets SQLite find the jobs in
        # a state by their status, as the Queue page's frequent polls for running jobs need.
        statuses = list(
            dict.fromkeys("queued" if state == "waiting" else state for state in wanted)
        )
        for column, values in (("status", statuses), ("state", wanted)):
            clauses.append(f"j.{column} IN ({', '.join('?' for _ in values)})")
            params.extend(values)
    if kind:
        clauses.append("j.kind = ?")
        params.append(kind)
    return " AND ".join(clauses) or "1", params


def next_check(previous: str | None, hours: int) -> str:
    """The first time on a subscription's own schedule after now, with some jitter. Counting on
    from its last time, not from now, keeps checks as spread out as they were: after a long pause
    they would otherwise all fall due together and stay that way."""
    moment, current = parse_time(previous) or utcnow(), utcnow()
    while moment <= current:
        moment += timedelta(hours=hours * random.uniform(0.9, 1.1))
    return iso(moment)


async def load_job(conn: aiosqlite.Connection, job_id: int) -> dict[str, Any]:
    job = await fetch_one(conn, "SELECT * FROM jobs WHERE id = ?", (job_id,))
    if job is None:
        raise JobNotFound(job_id)
    return job


class JobRunner:
    def __init__(self, db: Database, youtube: YouTubeGate, settings: Settings) -> None:
        self.db = db
        self.youtube = youtube
        self.settings = settings
        self.handlers: dict[str, Handler] = {}
        self.progress: dict[int, Progress] = {}
        self._cancel: dict[int, threading.Event] = {}
        self._cancelled_by: dict[int, Actor] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._wake = asyncio.Event()
        # Held while a job is chosen and its rest begins, so two workers can't both start one.
        self._claim_lock = asyncio.Lock()
        self._stopping = False

    async def start(self) -> None:
        if self._tasks:
            return
        from app.checks import run_check
        from app.downloads import run_download
        from app.scanner import run_scan

        self.handlers = {"download": run_download, "check": run_check, "scan": run_scan}
        await self._return_running()
        self._stopping = False
        self._tasks = [
            *(asyncio.create_task(self._download_worker(i)) for i in range(MAX_DOWNLOAD_WORKERS)),
            asyncio.create_task(self._worker(("check", "scan"))),
            asyncio.create_task(self._scheduler()),
        ]

    async def stop(self) -> None:
        self._stopping = True
        for event in self._cancel.values():
            event.set()
        self._wake.set()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    @property
    def stopping(self) -> bool:
        return self._stopping

    def wake(self) -> None:
        self._wake.set()

    async def enqueue(
        self,
        kind: str,
        *,
        origin: Origin,
        actor: Actor,
        video_id: int | None = None,
        subscription_id: int | None = None,
        via_subscription_id: int | None = None,
        options: dict[str, Any] | None = None,
        priority: Priority = Priority.ROUTINE,
        conn: aiosqlite.Connection | None = None,
    ) -> int:
        """Queue a job, or return the existing active job for the same video/subscription."""
        async with self._transaction(conn) as tx:
            job = await fetch_one(
                tx,
                "INSERT OR IGNORE INTO jobs (kind, video_id, subscription_id, "
                "via_subscription_id, origin, options, priority) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "RETURNING *",
                (
                    kind,
                    video_id,
                    subscription_id,
                    via_subscription_id,
                    origin,
                    dumps(options or {}),
                    priority,
                ),
            )
            if job:
                await events.record(
                    tx, "job.queued", actor=actor, job=job, detail=f"origin {origin}"
                )
            else:
                job = await fetch_one(
                    tx,
                    "SELECT * FROM jobs WHERE kind = ? AND video_id IS ? AND subscription_id IS ? "
                    "AND status IN ('queued', 'paused', 'running')",
                    (kind, video_id, subscription_id),
                )
                await self._merge(tx, job, kind, origin, options, via_subscription_id)
        self._wake.set()
        return job["id"]

    async def _merge(
        self,
        conn: aiosqlite.Connection,
        job: dict[str, Any],
        kind: str,
        origin: Origin,
        options: dict[str, Any] | None,
        via_subscription_id: int | None,
    ) -> None:
        """Fold a repeated request into the job that already exists, unless it is running."""
        if job["status"] == "running":
            return
        changes: dict[str, Any] = {}
        if origin == "user" and job["status"] == "queued" and job["origin"] != "user":
            # The owner asked for it by hand, so a policy or the schedule has no say over it.
            changes["origin"] = origin
        if kind == "check" and options and options.get("full"):
            changes["options"] = dumps(options)
        if kind == "download":
            if options:
                changes["options"] = dumps({**loads(job["options"]), **options})
            if via_subscription_id:
                changes["via_subscription_id"] = via_subscription_id
        if changes:
            await self._write(conn, job["id"], **changes)

    async def cancel(self, job_id: int, *, actor: Actor) -> None:
        """Cancel a queued, paused or running job. Running downloads stop at the next update."""
        async with self.db.transaction() as conn:
            job = await load_job(conn, job_id)
            if job["status"] not in ACTIVE:
                raise NotAllowed("Only queued, paused or running jobs can be cancelled")
            if job["status"] != "running":
                await self._move(
                    conn, job_id, "cancelled", "job.cancelled", actor=actor, finished_at=now()
                )
        if job["status"] == "running":
            self._cancelled_by[job_id] = actor
            self._cancel.setdefault(job_id, threading.Event()).set()

    async def pause(self, job_id: int, *, actor: Actor) -> None:
        async with self.db.transaction() as conn:
            await self._move(conn, job_id, "paused", "job.paused", actor=actor, reason=Reason.ASKED)

    async def resume(self, job_id: int, *, actor: Actor) -> None:
        async with self.db.transaction() as conn:
            await self._move(conn, job_id, "queued", "job.resumed", actor=actor, only=("paused",))
        self.wake()

    async def retry(self, job_id: int, *, actor: Actor) -> None:
        """Queue a failed or cancelled job to start over."""
        try:
            async with self.db.transaction() as conn:
                await self._retry(conn, job_id, actor)
        except sqlite3.IntegrityError as error:
            raise NotAllowed("Another job for this is already queued") from error
        self.wake()

    async def run_now(self, job_id: int, *, actor: Actor) -> None:
        """Make a queued job the next to run: it skips its own wait and goes to the front. It
        keeps its attempts and its error."""
        async with self.db.transaction() as conn:
            job = await load_job(conn, job_id)
            if job["status"] != "queued":
                raise NotAllowed(f"Cannot do that to a {job['status']} job")
            if until := self.youtube.resumes_at:
                raise NotAllowed(f"YouTube is paused until {until}")
            await self._write(
                conn, job_id, run_after=None, refusals=0, reason=None, priority=Priority.NOW
            )
            await events.record(conn, "job.run_now", actor=actor, job=job)
        self.wake()

    async def pause_many(
        self,
        job_ids: list[int],
        *,
        actor: Actor,
        reason: Reason = Reason.ASKED,
        conn: aiosqlite.Connection | None = None,
    ) -> int:
        """Pause the listed jobs that are still queued, ready or waiting; skip the rest."""
        async with self._transaction(conn) as tx:
            rows = await fetch_all(
                tx,
                "SELECT id FROM jobs WHERE status = 'queued' "
                "AND id IN (SELECT value FROM json_each(?)) ORDER BY id",
                (dumps(job_ids),),
            )
            for row in rows:
                await self._move(tx, row["id"], "paused", "job.paused", actor=actor, reason=reason)
        return len(rows)

    async def resume_many(
        self, job_ids: list[int], *, actor: Actor, conn: aiosqlite.Connection | None = None
    ) -> int:
        """Queue the listed jobs that are still paused, except downloads of archived videos."""
        resumed = 0
        async with self._transaction(conn) as tx:
            rows = await fetch_all(
                tx,
                "SELECT id FROM jobs WHERE status = 'paused' "
                "AND id IN (SELECT value FROM json_each(?)) ORDER BY id",
                (dumps(job_ids),),
            )
            for row in rows:
                try:
                    await self._move(
                        tx, row["id"], "queued", "job.resumed", actor=actor, only=("paused",)
                    )
                except NotAllowed:
                    continue
                resumed += 1
        self.wake()
        return resumed

    async def retry_failed(self, *, actor: Actor) -> int:
        """Queue every failed job to start over, except those whose video is gone: retrying
        those can't help."""
        retried = 0
        async with self.db.transaction() as conn:
            for job in await fetch_all(
                conn,
                "SELECT id FROM jobs WHERE status = 'failed' AND coalesce(reason, '') != ? "
                "ORDER BY id",
                (Reason.GONE,),
            ):
                try:
                    await self._retry(conn, job["id"], actor)
                except (NotAllowed, sqlite3.IntegrityError):
                    continue
                retried += 1
        self.wake()
        return retried

    async def remove(self, job_id: int, *, actor: Actor) -> None:
        """Delete a finished job's row. What happened to it stays in the record."""
        async with self.db.transaction() as conn:
            job = await load_job(conn, job_id)
            if job["status"] not in FINISHED:
                raise NotAllowed("Only finished jobs can be removed")
            await conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            await events.record(conn, "job.removed", actor=actor, job=job)

    async def clear_finished(self, *, actor: Actor) -> int:
        """Delete the rows of completed and cancelled jobs; failed ones stay to be dealt with."""
        async with self.db.transaction() as conn:
            cursor = await conn.execute(
                "DELETE FROM jobs WHERE status IN ('completed', 'cancelled')"
            )
            if cursor.rowcount:
                detail = f"{cursor.rowcount} jobs"
                await events.record(conn, "jobs.cleared", actor=actor, detail=detail)
            return cursor.rowcount

    async def resume_youtube(self, *, actor: Actor) -> None:
        """End a pause on YouTube work early."""
        await self.youtube.resume(actor)
        self.wake()

    async def list_jobs(
        self, states: list[str] | None, kind: str | None, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = job_filter(states, kind)
        total = await self.db.fetch_value(f"SELECT count(*) FROM job_state j WHERE {where}", params)
        rows = await self.db.fetch_all(
            f"{JOB_SELECT} WHERE {where} {self._order(states)} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        return rows, total

    async def job_ids(self, states: list[str] | None, kind: str | None) -> list[int]:
        """Every id the same filters would list, in the same order."""
        where, params = job_filter(states, kind)
        rows = await self.db.fetch_all(
            f"SELECT j.id FROM job_state j WHERE {where} {self._order(states)}", params
        )
        return [row["id"] for row in rows]

    async def counts(self, kind: str | None = None) -> dict[str, int]:
        """How many jobs are in each state."""
        where, params = job_filter(None, kind)
        counts = dict.fromkeys(STATES, 0)
        for row in await self.db.fetch_all(
            f"SELECT j.state, count(*) AS n FROM job_state j WHERE {where} GROUP BY j.state", params
        ):
            counts[row["state"]] = row["n"]
        return counts

    def _order(self, states: list[str] | None) -> str:
        return WAITING_ORDER if states and set(states) == {"waiting"} else LIST_ORDER

    async def queue_due_checks(self) -> int:
        if self.youtube.paused:
            return 0  # they fall due again once the pause ends
        due = await self.db.fetch_all(
            "SELECT id, check_interval_hours, next_check_at FROM subscriptions "
            "WHERE enabled = 1 AND (next_check_at IS NULL OR next_check_at <= ?)",
            (now(),),
        )
        for subscription in due:
            async with self.db.transaction() as conn:
                await self.enqueue(
                    "check",
                    subscription_id=subscription["id"],
                    origin="schedule",
                    actor="app",
                    conn=conn,
                )
                await conn.execute(
                    "UPDATE subscriptions SET next_check_at = ? WHERE id = ?",
                    (
                        next_check(
                            subscription["next_check_at"], subscription["check_interval_hours"]
                        ),
                        subscription["id"],
                    ),
                )
        return len(due)

    async def purge_trash(self) -> None:
        """Delete the trash entries that have expired, and record that some went."""
        if deleted := await asyncio.to_thread(trash.purge):
            detail = f"{deleted} expired entries deleted"
            await events.record(self.db, "trash.purged", actor="app", detail=detail)

    @asynccontextmanager
    async def _transaction(
        self, conn: aiosqlite.Connection | None
    ) -> AsyncIterator[aiosqlite.Connection]:
        """The caller's transaction if it passed one, else a new one."""
        if conn is not None:
            yield conn
            return
        async with self.db.transaction() as own:
            yield own

    async def _download_worker(self, index: int) -> None:
        while not self._stopping:
            try:
                limit = await self.settings.get("max_concurrent_downloads")
                job = await self._claim(("download",)) if index < limit else None
                if job:
                    await self._run(job)
                else:
                    await self._idle(self._poll(("download",)))
            except Exception:
                logger.exception("Download worker error")
                await self._idle()

    async def _worker(self, kinds: tuple[str, ...]) -> None:
        while not self._stopping:
            try:
                job = await self._claim(kinds)
                if job:
                    await self._run(job)
                else:
                    await self._idle(self._poll(kinds))
            except Exception:
                logger.exception("Worker error")
                await self._idle()

    async def _scheduler(self) -> None:
        purged_at = 0.0
        while not self._stopping:
            try:
                await self.queue_due_checks()
                if time.monotonic() - purged_at >= TRASH_PURGE_SECONDS:
                    purged_at = time.monotonic()
                    await self.purge_trash()
            except Exception:
                logger.exception("Scheduler error")
            await self._idle(30)

    async def _idle(self, seconds: float = 5) -> None:
        self._wake.clear()
        if self._stopping:
            return
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=seconds)
        except TimeoutError:
            pass

    def _poll(self, kinds: tuple[str, ...]) -> float:
        """How long an idle worker waits before looking again: not past the end of a rest."""
        rests = (self.youtube.rest_left(kind) for kind in kinds)
        return min([5.0, *(seconds for seconds in rests if seconds > 0)])

    async def _return_running(self) -> None:
        """Jobs a stop or a crash left running go back to the queue without using an attempt."""
        async with self.db.transaction() as conn:
            for job in await fetch_all(
                conn, "SELECT id, attempts FROM jobs WHERE status = 'running'"
            ):
                await self._move(
                    conn,
                    job["id"],
                    "queued",
                    "job.returned",
                    actor="app",
                    detail="restart",
                    started_at=None,
                    attempts=max(job["attempts"] - 1, 0),
                )

    async def _claim(self, kinds: tuple[str, ...]) -> dict[str, Any] | None:
        """The job to run next, if a kind in `kinds` has rested and one is ready."""
        async with self._claim_lock:
            kinds = tuple(kind for kind in kinds if self.youtube.can_start(kind))
            if not kinds:
                return None
            marks = ", ".join("?" for _ in kinds)
            async with self.db.transaction() as conn:
                # Both tests say queued: the status lets SQLite use the index, the state is the rule.
                ready = await fetch_one(
                    conn,
                    f"SELECT j.id, j.attempts FROM job_state j WHERE j.status = 'queued' "
                    f"AND j.state = 'queued' AND j.kind IN ({marks}) ORDER BY {QUEUE_ORDER} LIMIT 1",
                    kinds,
                )
                if ready is None:
                    return None
                job = await self._move(
                    conn,
                    ready["id"],
                    "running",
                    "job.started",
                    actor="app",
                    started_at=now(),
                    finished_at=None,
                    run_after=None,
                    attempts=ready["attempts"] + 1,
                )
            self.youtube.started(job["kind"])
            return job

    async def _run(self, job: dict[str, Any]) -> None:
        cancel = self._cancel.setdefault(job["id"], threading.Event())
        try:
            result = await self.handlers[job["kind"]](self, job, cancel)
        except Cancelled:
            if self._stopping:
                await self._return(job, "shutting down")
            else:
                actor = self._cancelled_by.get(job["id"], "app")
                await self._settle(
                    job, "cancelled", "job.cancelled", actor=actor, finished_at=now()
                )
        except NotReady as error:
            starts = error.retry_at or 0
            if starts > time.time():
                retry_at = starts + pace.PREMIERE_DELAY
            else:
                retry_at = time.time() + pace.PREMIERE_RECHECK
            await self._settle(
                job,
                "queued",
                "job.deferred",
                reason=Reason.PREMIERE,
                detail=str(error),
                error=str(error),
                run_after=from_timestamp(retry_at),
                started_at=None,
                attempts=max(job["attempts"] - 1, 0),
            )
        except Blocked as error:
            # It gets its attempt back, since a refusal is rarely the job's fault. It goes behind
            # the others in case it is: one video YouTube won't serve mustn't hold up the queue.
            await self._settle(
                job,
                "queued",
                "job.refused",
                reason=Reason.REFUSED,
                detail=str(error),
                error=str(error),
                refusals=job["refusals"] + 1,
                started_at=None,
                attempts=max(job["attempts"] - 1, 0),
            )
        except Paused as error:
            await self._return(job, str(error))
        except YouTubeError as error:
            await self._fail_or_retry(job, error, retryable=is_generic(error))
        except Declined as error:
            await self._fail_or_retry(job, error, retryable=False)
        except Exception as error:
            logger.exception("Job %s failed", job["id"])
            await self._fail_or_retry(job, error, retryable=False)
        else:
            await self._settle(
                job,
                "completed",
                "job.completed",
                detail=summary(job["kind"], result),
                result=dumps(result),
                error=None,
                run_after=None,
                finished_at=now(),
            )
        finally:
            self._cancel.pop(job["id"], None)
            self._cancelled_by.pop(job["id"], None)
            self.progress.pop(job["id"], None)
            self.youtube.finished(job["kind"])

    async def _settle(
        self, job: dict[str, Any], to: str, event: str, *, actor: Actor = "app", **fields: Any
    ) -> None:
        """Move a job that has been running to where its outcome puts it."""
        async with self.db.transaction() as conn:
            await self._move(conn, job["id"], to, event, actor=actor, **fields)

    async def _return(self, job: dict[str, Any], detail: str) -> None:
        """Back to the queue without using an attempt: the job never got to try."""
        await self._settle(
            job,
            "queued",
            "job.returned",
            detail=detail,
            started_at=None,
            attempts=max(job["attempts"] - 1, 0),
        )

    async def _fail_or_retry(self, job: dict[str, Any], error: Exception, retryable: bool) -> None:
        message = str(error) or type(error).__name__
        if retryable and job["attempts"] <= len(pace.RETRY_DELAYS):
            delay = pace.RETRY_DELAYS[job["attempts"] - 1]
            await self._settle(
                job,
                "queued",
                "job.retrying",
                reason=Reason.RETRY,
                detail=f"Retrying in {delay // 60} minutes: {message}",
                error=message,
                run_after=later(seconds=delay),
                started_at=None,
            )
        else:
            await self._settle(
                job,
                "failed",
                "job.failed",
                reason=failure_reason(error),
                detail=message,
                error=message,
                finished_at=now(),
            )

    async def _retry(self, conn: aiosqlite.Connection, job_id: int, actor: Actor) -> None:
        await self._move(
            conn,
            job_id,
            "queued",
            "job.retried",
            actor=actor,
            only=("failed", "cancelled"),
            attempts=0,
            refusals=0,
            error=None,
            run_after=None,
            started_at=None,
            finished_at=None,
        )

    async def _move(
        self,
        conn: aiosqlite.Connection,
        job_id: int,
        to: str,
        event: str,
        *,
        actor: Actor,
        only: tuple[str, ...] | None = None,
        reason: Reason | None = None,
        detail: str | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """The one way a job's status changes: check the move against MOVES, write it, and record
        it in the same transaction. `only` narrows the move to jobs in those statuses, for the
        actions that share a destination; `reason` says why the job ends up here (a job leaving a
        pause gets back the one it had before); anything else in `fields` is written with it."""
        job = await load_job(conn, job_id)
        if to not in MOVES[job["status"]] or (only and job["status"] not in only):
            raise NotAllowed(f"Cannot do that to a {job['status']} job")
        if to == "queued" and job["kind"] == "download" and job["status"] != "running":
            video = await fetch_one(
                conn, "SELECT media_path FROM videos WHERE id = ?", (job["video_id"],)
            )
            if video["media_path"]:
                raise NotAllowed("This video is already archived")
        if to == "paused":
            # A pause replaces the reason but not the wait, which has to be explained when the
            # job comes back.
            fields["resume_reason"] = job["reason"]
        elif job["status"] == "paused":
            fields["resume_reason"] = None
            if to == "queued" and reason is None:
                reason = job["resume_reason"]
        job = await self._write(conn, job_id, status=to, reason=reason, **fields)
        level = logging.WARNING if event in WARNINGS else logging.INFO
        await events.record(
            conn, event, actor=actor, job=job, reason=reason, detail=detail, level=level
        )
        return job

    async def _write(
        self, conn: aiosqlite.Connection, job_id: int, **fields: Any
    ) -> dict[str, Any]:
        """The only statement that changes a job row. Returns the row as written."""
        assignments = ", ".join(f"{column} = ?" for column in fields)
        return await fetch_one(
            conn,
            f"UPDATE jobs SET {assignments} WHERE id = ? RETURNING *",
            (*fields.values(), job_id),
        )
