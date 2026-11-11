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
from app.db import Database, dumps, from_timestamp, loads, parse_time
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
    "failures": ("youtube.failures", "Calls to YouTube keep failing"),
}
# The kinds of call whose failures are counted, each run on its own, as a pause names them.
CALLS = {"download": "downloads", "check": "checks", "lookup": "lookups"}


def stamp(timestamp: float) -> str:
    """A time as it is saved and reported: rounded up to the second, so the database never says a
    pause is over while the gate still holds it."""
    return from_timestamp(math.ceil(timestamp))


class YouTubeGate:
    """The YouTube adapter behind a pause. A refusal pauses every call for longer each time
    YouTube refuses in a row, and so does a run of failures nothing explains. The adapter asks
    before every request it sends YouTube, so a pause stops calls already under way too.

    It also keeps the pace between jobs: after one of a kind starts or finishes, no other of that
    kind starts until its rest is over, however many workers there are.

    The pause, the counts and the rests are saved, so a restart keeps them all.
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
        # What each kind of call in CALLS was about, for those that failed for no particular
        # reason since one of that kind went through.
        self.failures: dict[str, list[str]] = {}
        # When each kind of job may start again (monotonic).
        self._rest_until: dict[str, float] = {}
        self._lock = asyncio.Lock()
        # Held while the state is written, so an older state can't land over a newer one.
        self._saving = asyncio.Lock()
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

    async def started(self, kind: str) -> None:
        """A job of this kind began: the rest starts."""
        await self._rest(kind)

    async def finished(self, kind: str) -> None:
        """A job of this kind ended: the rest starts over from now."""
        await self._rest(kind)

    async def _rest(self, kind: str) -> None:
        if rest := pace.REST.get(kind):
            self._rest_until[kind] = time.monotonic() + random.uniform(*rest)
            await self._save()

    async def load(self) -> None:
        """Read what was saved before a restart: the pause, the counts and the rests."""
        row = await self._db.fetch_one(
            "SELECT paused_until, refusals, cause, reason, failures, rests FROM youtube_pause"
        )
        moment = parse_time(row["paused_until"])
        self.paused_until = moment.timestamp() if moment else 0.0
        self.refusals = row["refusals"]
        self.cause = row["cause"]
        self.reason = row["reason"]
        self.failures = loads(row["failures"]) or {}
        for kind, until in (loads(row["rests"]) or {}).items():
            if ends := parse_time(until):
                left = ends.timestamp() - time.time()
                self._rest_until[kind] = time.monotonic() + max(0.0, left)

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

        The runs of refusals and failures stay: only calls that go through end them.
        """
        async with self._lock:
            if not self.paused:
                return False
            left = math.ceil((self.paused_until - time.time()) / 60)
            self.paused_until = 0.0
            await self._save("youtube.resumed", actor, f"Ended {left} minutes early")
            return True

    async def resolve_source(self, kind: str, url: str) -> Source:
        async with self._guarded("lookup", url):
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
        async with self._guarded("check", f"{kind}:{youtube_id}"):
            return await self._youtube.list_entries(
                kind,
                youtube_id,
                video_type,
                known=known,
                stop_after_known=stop_after_known,
                cancelled=cancelled,
            )

    async def fetch_video(self, youtube_id: str) -> dict[str, Any]:
        async with self._guarded("lookup", youtube_id):
            return await self._youtube.fetch_video(youtube_id)

    async def download(
        self, request: DownloadRequest, progress: ProgressCallback, cancelled: threading.Event
    ) -> dict[str, Any]:
        started = time.monotonic()
        async with self._guarded("download", request.youtube_id):
            info = await self._youtube.download(request, progress, cancelled)
        # The video came through, so this counts as a success, but a refused extra means the next
        # videos would lose theirs too.
        await self._succeeded(started)
        if refused := info["_youhoard"].get("refused"):
            await self.hold(pace.EXTRAS_PAUSE, refused, "app", "extras")
        return info

    async def fetch_image(self, url: str) -> bytes:
        """Channel art from YouTube's image CDN. Rare and best-effort, so its failures aren't
        counted, but a pause holds it and a refusal starts one."""
        async with self._guarded():
            return await self._youtube.fetch_image(url)

    def versions(self) -> dict[str, str | None]:
        return self._youtube.versions()

    @asynccontextmanager
    async def _guarded(self, kind: str | None = None, subject: str = "") -> AsyncIterator[None]:
        """Refuse to start while paused; record a refusal from YouTube and pass it on. For a kind
        of call in CALLS, keep the run of failures nothing explains; `subject` is what the call
        was about, a video, a subscription or a URL."""
        self.check()
        try:
            yield
        except Blocked as error:
            await self._refused(error)
            raise
        except Exception as error:
            if kind and is_generic(error):
                await self._failed(kind, subject, error)
            raise
        else:
            if kind and self.failures.get(kind):
                await self._went_through(kind)

    async def _refused(self, error: Blocked) -> None:
        async with self._lock:
            if self.paused:
                return  # the call began before the pause, so it isn't another refusal
            self.refusals += 1
            self._refused_at = time.monotonic()
            seconds = pace.BLOCK_PAUSES[min(self.refusals, len(pace.BLOCK_PAUSES)) - 1]
            await self._pause(seconds, "refused", str(error), "app")

    async def _failed(self, kind: str, subject: str, error: Exception) -> None:
        """A call failed for no particular reason. Enough of one kind in a row, each about
        something different, look like a refusal in words YouHoard doesn't know, or trouble with
        the connection; trying more only makes either worse. One video failing again says only
        that something is wrong with it, so its retries don't count. Past the streak, each
        further failure waits longer, as refusals do."""
        async with self._lock:
            run = self.failures.setdefault(kind, [])
            if subject in run:
                return
            run.append(subject)
            count = len(run)
            if count < pace.FAILURE_STREAK:
                await self._save()
                return
            rung = min(count - pace.FAILURE_STREAK, len(pace.FAILURE_PAUSES) - 1)
            seconds = pace.FAILURE_PAUSES[rung]
            if time.time() + seconds <= self.paused_until:
                await self._save()  # a longer pause already stands
                return
            reason = f"{count} different {CALLS[kind]} in a row failed; the last said: {error}"
            await self._pause(seconds, "failures", reason, "app")

    async def _went_through(self, kind: str) -> None:
        """A call of this kind went through, which ends its run of failures."""
        async with self._lock:
            if self.failures.pop(kind, None):
                await self._save()

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
        """Write the pause, the counts and the rests and, with them, the event that changed them.
        This is the only code that writes the youtube_pause table."""
        async with self._saving, self._db.transaction() as conn:
            rests = {kind: self.rest_ends(kind) for kind in self._rest_until}
            await conn.execute(
                "UPDATE youtube_pause SET paused_until = ?, refusals = ?, cause = ?, reason = ?, "
                "failures = ?, rests = ?",
                (
                    stamp(self.paused_until) if self.paused_until else None,
                    self.refusals,
                    self.cause,
                    self.reason,
                    dumps(self.failures),
                    dumps({kind: ends for kind, ends in rests.items() if ends}),
                ),
            )
            if event:
                level = logging.INFO if actor == "owner" else logging.WARNING
                await events.record(conn, event, actor=actor, detail=detail, level=level)
