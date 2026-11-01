"""The gate every YouTube request passes through, so one bot check pauses all of YouTube."""

import asyncio
import logging
import math
import random
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app import events, pace
from app.db import Database, from_timestamp, parse_time
from app.events import Actor
from app.youtube import (
    Blocked,
    DownloadRequest,
    Listing,
    Paused,
    ProgressCallback,
    Source,
    YouTube,
    is_generic,
)

# What can start a pause: the event that records it, and how the record words it.
CAUSES = {
    "asked": ("youtube.paused", "Paused on request"),
    "refused": ("youtube.refused", "YouTube refused a request"),
    "extras": ("youtube.extras_refused", "YouTube refused a subtitle or live chat"),
    "failures": ("youtube.failures", "Downloads keep failing"),
}


def stamp(timestamp: float) -> str:
    """A time as it is saved and reported: rounded up to the second, so the database never says a
    pause is over while the gate still holds it."""
    return from_timestamp(math.ceil(timestamp))


class YouTubeGate:
    """The YouTube adapter behind a pause. A refusal pauses every call for longer each time
    YouTube refuses in a row; the pause and the count are saved, so a restart keeps them.

    It also keeps the pace between jobs: after one of a kind starts or finishes, no other of that
    kind starts until its rest is over, however many workers there are.
    """

    def __init__(self, youtube: YouTube, db: Database) -> None:
        self._youtube = youtube
        self._db = db
        # Epoch seconds the pause ends; 0 when there is none.
        self.paused_until = 0.0
        # Refusals in a row; a completed download resets it.
        self.refusals = 0
        # What started the pause, one of CAUSES, and what was said at the time, if anything.
        self.cause: str | None = None
        self.reason: str | None = None
        # When the latest refusal came (monotonic); a call that began earlier proves nothing.
        self._refused_at = 0.0
        # Downloads that failed for no particular reason since one last completed. Not saved.
        self._failures = 0
        # When each kind of job may start again (monotonic).
        self._rest_until: dict[str, float] = {}
        self._lock = asyncio.Lock()
        youtube.before_call = self.check

    @property
    def paused(self) -> bool:
        return time.time() < self.paused_until

    @property
    def resumes_at(self) -> str | None:
        """When the pause ends, or None when there isn't one."""
        return stamp(self.paused_until) if self.paused else None

    @property
    def status(self) -> dict[str, Any]:
        """What the API reports about the pause and the rest."""
        return {
            "youtube_paused_until": self.resumes_at,
            "youtube_pause_cause": self.cause if self.paused else None,
            "youtube_pause_reason": self.reason if self.paused else None,
            "youtube_refusals": self.refusals,
            "download_rest_until": self.rest_ends("download"),
        }

    def check(self) -> None:
        """Raise Paused while YouTube work is paused. Safe to call from any thread."""
        if until := self.resumes_at:
            raise Paused(until)

    def rest_left(self, kind: str) -> float:
        """Seconds until another job of this kind may start; 0 when it may now."""
        return max(0.0, self._rest_until.get(kind, 0.0) - time.monotonic())

    def rest_ends(self, kind: str) -> str | None:
        """When another job of this kind may start, or None when it may now."""
        left = self.rest_left(kind)
        return stamp(time.time() + left) if left else None

    def can_start(self, kind: str) -> bool:
        return self.rest_left(kind) <= 0

    def started(self, kind: str) -> None:
        """A job of this kind began: the rest starts."""
        self._rest(kind)

    def finished(self, kind: str) -> None:
        """A job of this kind ended: the rest starts over from now."""
        self._rest(kind)

    def _rest(self, kind: str) -> None:
        if rest := pace.REST.get(kind):
            self._rest_until[kind] = time.monotonic() + random.uniform(*rest)

    async def load(self) -> None:
        """Read the pause and the refusal count saved before a restart."""
        row = await self._db.fetch_one(
            "SELECT paused_until, refusals, cause, reason FROM youtube_pause"
        )
        moment = parse_time(row["paused_until"])
        self.paused_until = moment.timestamp() if moment else 0.0
        self.refusals = row["refusals"]
        self.cause = row["cause"]
        self.reason = row["reason"]

    async def hold(
        self,
        seconds: float,
        reason: str | None = None,
        actor: Actor = "owner",
        cause: str = "asked",
    ) -> None:
        """Pause YouTube work. Nothing was refused, so the count stays, and a longer pause that
        is already running stands."""
        async with self._lock:
            if time.time() + seconds > self.paused_until:
                await self._pause(seconds, cause, reason, actor)

    async def resume(self, actor: Actor = "owner") -> bool:
        """End the pause early; False if there wasn't one.

        The refusal count stays: only a completed download resets it.
        """
        async with self._lock:
            if not self.paused:
                return False
            left = math.ceil((self.paused_until - time.time()) / 60)
            self.paused_until = 0.0
            await self._save("youtube.resumed", actor, f"Ended {left} minutes early")
            return True

    async def resolve_source(self, kind: str, url: str) -> Source:
        async with self._guarded():
            return await self._youtube.resolve_source(kind, url)

    async def list_entries(
        self,
        kind: str,
        youtube_id: str,
        video_type: str | None,
        known: set[str] | None = None,
        stop_after_known: int = 10,
        cancelled: threading.Event | None = None,
    ) -> Listing:
        async with self._guarded():
            return await self._youtube.list_entries(
                kind,
                youtube_id,
                video_type,
                known=known,
                stop_after_known=stop_after_known,
                cancelled=cancelled,
            )

    async def fetch_video(self, youtube_id: str) -> dict[str, Any]:
        async with self._guarded():
            return await self._youtube.fetch_video(youtube_id)

    async def download(
        self, request: DownloadRequest, progress: ProgressCallback, cancelled: threading.Event
    ) -> dict[str, Any]:
        started = time.monotonic()
        async with self._guarded():
            try:
                info = await self._youtube.download(request, progress, cancelled)
            except Exception as error:
                if is_generic(error):
                    await self._failed(error)
                raise
        # The video came through, so this counts as a success, but a refused extra means the next
        # videos would lose theirs too.
        self._failures = 0
        await self._succeeded(started)
        if refused := info["_youhoard"].get("refused"):
            await self.hold(pace.EXTRAS_PAUSE, refused, "app", "extras")
        return info

    # Not gated: images come from YouTube's image CDN, and versions is local.
    async def fetch_image(self, url: str) -> bytes:
        return await self._youtube.fetch_image(url)

    def versions(self) -> dict[str, str | None]:
        return self._youtube.versions()

    @asynccontextmanager
    async def _guarded(self) -> AsyncIterator[None]:
        """Refuse to start while paused; record a refusal from YouTube and pass it on."""
        self.check()
        try:
            yield
        except Blocked as error:
            await self._refused(error)
            raise

    async def _refused(self, error: Blocked) -> None:
        async with self._lock:
            if self.paused:
                return  # the call began before the pause, so it isn't another refusal
            self.refusals += 1
            self._refused_at = time.monotonic()
            seconds = pace.BLOCK_PAUSES[min(self.refusals, len(pace.BLOCK_PAUSES)) - 1]
            await self._pause(seconds, "refused", str(error), "app")

    async def _failed(self, error: Exception) -> None:
        """A download failed for no particular reason. Enough of them in a row look like trouble
        with the connection, and trying more only makes it worse."""
        self._failures += 1
        if self._failures >= pace.FAILURE_STREAK:
            self._failures = 0
            reason = f"{pace.FAILURE_STREAK} downloads in a row failed; the last said: {error}"
            await self.hold(pace.FAILURE_PAUSE, reason, "app", "failures")

    async def _succeeded(self, started: float) -> None:
        """A download completed, so YouTube has stopped refusing, provided the download began
        after the latest refusal. One already under way when the pause started doesn't count."""
        if not self.refusals:
            return
        async with self._lock:
            if self.refusals and started > self._refused_at:
                self.refusals = 0
                await self._save()

    async def _pause(self, seconds: float, cause: str, reason: str | None, actor: Actor) -> None:
        self.paused_until = time.time() + seconds
        self.cause, self.reason = cause, reason
        event, words = CAUSES[cause]
        text = f"{words}; all YouTube work waits {int(seconds // 60)} minutes"
        await self._save(event, actor, f"{text}: {reason}" if reason else text)

    async def _save(
        self, event: str | None = None, actor: Actor = "app", detail: str | None = None
    ) -> None:
        """Write the pause and, with it, the event that changed it. This is the only code that
        writes the youtube_pause table."""
        async with self._db.transaction() as conn:
            await conn.execute(
                "UPDATE youtube_pause SET paused_until = ?, refusals = ?, cause = ?, reason = ?",
                (
                    stamp(self.paused_until) if self.paused_until else None,
                    self.refusals,
                    self.cause,
                    self.reason,
                ),
            )
            if event:
                level = logging.INFO if actor == "owner" else logging.WARNING
                await events.record(conn, event, actor=actor, detail=detail, level=level)
