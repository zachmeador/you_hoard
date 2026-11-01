"""The gate every YouTube request passes through, so one bot check pauses all of YouTube."""

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from app.db import Database, from_timestamp, parse_time
from app.youtube import Blocked, DownloadRequest, Listing, ProgressCallback, Source, YouTube

logger = logging.getLogger(__name__)

# How long YouTube work waits after a bot check, longer each time YouTube refuses again.
BLOCK_PAUSES = (3600, 2 * 3600, 4 * 3600, 8 * 3600, 12 * 3600)
Listener = Callable[[str], Awaitable[None]]


class Paused(Exception):
    """YouTube work is waiting, after a refusal or because the owner asked.

    Not a YouTubeError, so the API's handlers for those don't turn it into a 502.
    """

    def __init__(self, until: str) -> None:
        super().__init__(f"YouTube is paused until {until}")
        self.until = until


class YouTubeGate:
    """The YouTube adapter behind a pause. A refusal pauses every call for longer each time
    YouTube refuses in a row; the pause and the count are saved, so a restart keeps them."""

    def __init__(self, youtube: YouTube, db: Database) -> None:
        self._youtube = youtube
        self._db = db
        # Epoch seconds the pause ends; 0 when there is none.
        self.paused_until = 0.0
        # Refusals in a row; a video request that goes through resets it.
        self.refusals = 0
        # What YouTube said when it refused; None once the owner has asked for a pause.
        self.reason: str | None = None
        # When the latest refusal came (monotonic); a call that began earlier proves nothing.
        self._refused_at = 0.0
        self._lock = asyncio.Lock()
        self._listeners: list[Listener] = []

    @property
    def paused(self) -> bool:
        return time.time() < self.paused_until

    @property
    def resumes_at(self) -> str | None:
        """When the pause ends, or None when there isn't one."""
        return from_timestamp(self.paused_until) if self.paused else None

    @property
    def status(self) -> dict[str, Any]:
        """What the API reports about the pause."""
        return {
            "youtube_paused_until": self.resumes_at,
            "youtube_pause_reason": self.reason if self.paused else None,
            "youtube_refusals": self.refusals,
        }

    def when_paused(self, listener: Listener) -> None:
        """Call `listener` with the time the pause ends whenever one starts."""
        self._listeners.append(listener)

    async def load(self) -> None:
        """Read the pause and the refusal count saved before a restart."""
        row = await self._db.fetch_one("SELECT paused_until, refusals, reason FROM youtube_pause")
        moment = parse_time(row["paused_until"])
        self.paused_until = moment.timestamp() if moment else 0.0
        self.refusals = row["refusals"]
        self.reason = row["reason"]

    async def hold(self, seconds: float) -> None:
        """Pause on request. Nothing was refused, so the count stays, and a longer pause stands."""
        async with self._lock:
            until = time.time() + seconds
            if until > self.paused_until:
                self.paused_until = until
                self.reason = None
                await self._save()
                await self._announce()

    async def resume(self) -> str | None:
        """End the pause early and return when it would have ended, or None if there was none.

        The refusal count stays: only a success resets it.
        """
        async with self._lock:
            if not self.paused_until:
                return None
            until = from_timestamp(self.paused_until)
            self.paused_until = 0.0
            await self._save()
            return until

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
        started = time.monotonic()
        async with self._guarded():
            info = await self._youtube.fetch_video(youtube_id)
        await self._succeeded(started)
        return info

    async def download(
        self, request: DownloadRequest, progress: ProgressCallback, cancelled: threading.Event
    ) -> dict[str, Any]:
        started = time.monotonic()
        async with self._guarded():
            info = await self._youtube.download(request, progress, cancelled)
        # The video is safe, but a refused extra means the next ones would lose theirs too.
        if refused := info["_youhoard"].pop("refused", None):
            await self._refused(Blocked(refused))
        else:
            await self._succeeded(started)
        return info

    # Not gated: images come from YouTube's image CDN, and versions is local.
    async def fetch_image(self, url: str) -> bytes:
        return await self._youtube.fetch_image(url)

    def versions(self) -> dict[str, str | None]:
        return self._youtube.versions()

    @asynccontextmanager
    async def _guarded(self) -> AsyncIterator[None]:
        """Refuse to start while paused; record a refusal from YouTube and pass it on."""
        if until := self.resumes_at:
            raise Paused(until)
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
            seconds = BLOCK_PAUSES[min(self.refusals, len(BLOCK_PAUSES)) - 1]
            self.paused_until = time.time() + seconds
            self.reason = str(error)
            await self._save()
            logger.warning(
                "YouTube asked for a bot check; all YouTube work waits %s minutes: %s",
                seconds // 60,
                error,
            )
            await self._announce()

    async def _announce(self) -> None:
        until = from_timestamp(self.paused_until)
        for listener in self._listeners:
            await listener(until)

    async def _succeeded(self, started: float) -> None:
        """A video request went through, so YouTube has stopped refusing, provided the request
        began after the latest refusal. A download already under way when the pause started
        doesn't count."""
        if not self.refusals:
            return
        async with self._lock:
            if self.refusals and started > self._refused_at:
                self.refusals = 0
                await self._save()

    async def _save(self) -> None:
        await self._db.execute(
            "UPDATE youtube_pause SET paused_until = ?, refusals = ?, reason = ?",
            (
                from_timestamp(self.paused_until) if self.paused_until else None,
                self.refusals,
                self.reason,
            ),
        )
