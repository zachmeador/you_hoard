"""Persistent job queue: download workers, one general worker, and the subscription scheduler."""

import asyncio
import logging
import random
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

import aiosqlite

from app.db import Database, dumps, fetch_one, from_timestamp, later, now
from app.settings import Settings
from app.youtube import Blocked, Cancelled, NotReady, YouTube, YouTubeError

logger = logging.getLogger(__name__)

MAX_DOWNLOAD_WORKERS = 8
RETRY_DELAYS = (15 * 60, 60 * 60, 4 * 60 * 60)
ACTIVE = ("queued", "paused", "running")
Handler = Callable[["JobRunner", dict[str, Any], threading.Event], Awaitable[dict[str, Any]]]


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


class JobRunner:
    def __init__(self, db: Database, youtube: YouTube, settings: Settings) -> None:
        self.db = db
        self.youtube = youtube
        self.settings = settings
        self.handlers: dict[str, Handler] = {}
        self.progress: dict[int, Progress] = {}
        self._cancel: dict[int, threading.Event] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._wake = asyncio.Event()
        self._stopping = False

    async def start(self) -> None:
        if self._tasks:
            return
        from app.checks import run_check
        from app.downloads import run_download
        from app.scanner import run_scan

        self.handlers = {"download": run_download, "check": run_check, "scan": run_scan}
        await self.db.execute(
            "UPDATE jobs SET status = 'queued', started_at = NULL, attempts = max(attempts - 1, 0) "
            "WHERE status = 'running'"
        )
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
        video_id: int | None = None,
        subscription_id: int | None = None,
        options: dict[str, Any] | None = None,
        priority: int = 0,
        conn: aiosqlite.Connection | None = None,
    ) -> int:
        """Queue a job, or return the existing active job for the same video/subscription."""

        async def insert(conn: aiosqlite.Connection) -> int:
            cursor = await conn.execute(
                "INSERT OR IGNORE INTO jobs (kind, video_id, subscription_id, options, priority) "
                "VALUES (?, ?, ?, ?, ?)",
                (kind, video_id, subscription_id, dumps(options or {}), priority),
            )
            if cursor.rowcount:
                return cursor.lastrowid
            existing = await fetch_one(
                conn,
                "SELECT id, status FROM jobs WHERE kind = ? AND video_id IS ? "
                "AND subscription_id IS ? AND status IN ('queued', 'paused', 'running')",
                (kind, video_id, subscription_id),
            )
            if (
                kind == "check"
                and options
                and options.get("full")
                and existing["status"] != "running"
            ):
                await conn.execute(
                    "UPDATE jobs SET options = ? WHERE id = ?", (dumps(options), existing["id"])
                )
            return existing["id"]

        if conn is not None:
            job_id = await insert(conn)
        else:
            async with self.db.transaction() as conn:
                job_id = await insert(conn)
        self._wake.set()
        return job_id

    async def cancel(self, job_id: int) -> bool:
        """Cancel a queued, paused or running job. Running downloads stop at the next update."""
        async with self.db.transaction() as conn:
            job = await fetch_one(conn, "SELECT status FROM jobs WHERE id = ?", (job_id,))
            if not job or job["status"] not in ACTIVE:
                return False
            if job["status"] != "running":
                await conn.execute(
                    "UPDATE jobs SET status = 'cancelled', finished_at = ? WHERE id = ?",
                    (now(), job_id),
                )
        if job["status"] == "running":
            self._cancel.setdefault(job_id, threading.Event()).set()
        return True

    async def queue_due_checks(self) -> int:
        due = await self.db.fetch_all(
            "SELECT id, check_interval_hours FROM subscriptions "
            "WHERE enabled = 1 AND (next_check_at IS NULL OR next_check_at <= ?)",
            (now(),),
        )
        for subscription in due:
            hours = subscription["check_interval_hours"]
            async with self.db.transaction() as conn:
                await self.enqueue("check", subscription_id=subscription["id"], conn=conn)
                await conn.execute(
                    "UPDATE subscriptions SET next_check_at = ? WHERE id = ?",
                    (later(hours=hours * random.uniform(0.9, 1.1)), subscription["id"]),
                )
        return len(due)

    async def _download_worker(self, index: int) -> None:
        while not self._stopping:
            try:
                limit = await self.settings.get("max_concurrent_downloads")
                job = await self._claim(("download",)) if index < limit else None
                if job:
                    await self._run(job)
                else:
                    await self._idle()
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
                    await self._idle()
            except Exception:
                logger.exception("Worker error")
                await self._idle()

    async def _scheduler(self) -> None:
        while not self._stopping:
            try:
                await self.queue_due_checks()
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

    async def _claim(self, kinds: tuple[str, ...]) -> dict[str, Any] | None:
        placeholders = ", ".join("?" for _ in kinds)
        async with self.db.transaction() as conn:
            return await fetch_one(
                conn,
                f"""UPDATE jobs SET status = 'running', started_at = ?, finished_at = NULL,
                        attempts = attempts + 1
                    WHERE id = (
                        SELECT id FROM jobs
                        WHERE status = 'queued' AND kind IN ({placeholders})
                          AND (run_after IS NULL OR run_after <= ?)
                        ORDER BY priority DESC, id LIMIT 1)
                    RETURNING *""",
                (now(), *kinds, now()),
            )

    async def _finish(self, job_id: int, **fields: Any) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        await self.db.execute(
            f"UPDATE jobs SET {assignments} WHERE id = ?", (*fields.values(), job_id)
        )

    async def _run(self, job: dict[str, Any]) -> None:
        cancel = self._cancel.setdefault(job["id"], threading.Event())
        try:
            result = await self.handlers[job["kind"]](self, job, cancel)
        except Cancelled:
            if self._stopping:
                await self._requeue(job, None)
            else:
                await self._finish(job["id"], status="cancelled", finished_at=now())
        except NotReady as error:
            starts = error.retry_at or 0
            retry_at = starts + 600 if starts > time.time() else time.time() + 3600
            await self._requeue(job, from_timestamp(retry_at), str(error))
        except YouTubeError as error:
            retryable = type(error) is YouTubeError or isinstance(error, Blocked)
            await self._fail_or_retry(job, error, retryable)
        except Exception as error:
            logger.exception("Job %s failed", job["id"])
            await self._fail_or_retry(job, error, retryable=False)
        else:
            await self._finish(
                job["id"],
                status="completed",
                result=dumps(result),
                error=None,
                run_after=None,
                finished_at=now(),
            )
        finally:
            self._cancel.pop(job["id"], None)
            self.progress.pop(job["id"], None)

    async def _requeue(
        self, job: dict[str, Any], run_after: str | None, error: str | None = None
    ) -> None:
        await self._finish(
            job["id"],
            status="queued",
            started_at=None,
            run_after=run_after,
            error=error,
            attempts=max(job["attempts"] - 1, 0),
        )

    async def _fail_or_retry(self, job: dict[str, Any], error: Exception, retryable: bool) -> None:
        message = str(error) or type(error).__name__
        if retryable and job["attempts"] <= len(RETRY_DELAYS):
            delay = RETRY_DELAYS[job["attempts"] - 1]
            logger.warning("Job %s will retry in %ss: %s", job["id"], delay, message)
            await self._finish(
                job["id"],
                status="queued",
                started_at=None,
                run_after=later(seconds=delay),
                error=message,
            )
        else:
            await self._finish(job["id"], status="failed", error=message, finished_at=now())
