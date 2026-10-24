"""Run blocking yt-dlp work off the server's event loop."""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import yt_dlp

from app.core.config import settings

logger = logging.getLogger(__name__)


class YTDLPService:
    def __init__(self):
        self.failure_count = 0
        self.last_request_time = 0.0
        self.min_request_interval = settings.YTDLP_MIN_REQUEST_INTERVAL
        self._lock = asyncio.Lock()

    def _get_config(self, extra: Optional[Dict] = None) -> Dict:
        config = {
            "quiet": True,
            "no_warnings": False,
            "logger": logger,
            "retries": settings.YTDLP_MAX_RETRIES,
            "socket_timeout": 30,
            "noplaylist": True,
        }
        if settings.YTDLP_COOKIE_FILE:
            config["cookiefile"] = settings.YTDLP_COOKIE_FILE
        config.update(extra or {})
        return config

    async def _enforce_rate_limit(self):
        async with self._lock:
            delay = self.min_request_interval - (time.monotonic() - self.last_request_time)
            if delay > 0:
                await asyncio.sleep(delay)
            self.last_request_time = time.monotonic()

    async def _run_with_retries(self, function, operation: str):
        for attempt in range(settings.YTDLP_MAX_RETRIES):
            await self._enforce_rate_limit()
            try:
                result = await asyncio.to_thread(function)
                self.failure_count = 0
                return result
            except Exception as error:
                self.failure_count += 1
                permanent = any(
                    text in str(error).lower()
                    for text in (
                        "private video",
                        "video unavailable",
                        "has been removed",
                        "unsupported url",
                        "not available in your country",
                        "sign in to confirm",
                    )
                )
                if permanent or attempt + 1 >= settings.YTDLP_MAX_RETRIES:
                    raise  # Preserve YouTube's actual error for the job and UI.
                delay = min(settings.YTDLP_MIN_BACKOFF * 2**attempt, settings.YTDLP_MAX_BACKOFF)
                logger.warning("%s failed; retrying in %.1fs: %s", operation, delay, error)
                await asyncio.sleep(delay)

    async def extract_info(self, url: str, extra_config: Optional[Dict] = None) -> Dict[str, Any]:
        def extract():
            with yt_dlp.YoutubeDL(self._get_config(extra_config)) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise ValueError("No metadata returned by yt-dlp")
                # Materialize lazy playlist entries inside the worker thread.
                return ydl.sanitize_info(info)

        return await self._run_with_retries(extract, "Metadata extraction")

    async def download_with_progress(
        self,
        url: str,
        output_path: Path,
        progress_callback=None,
        extra_config: Optional[Dict] = None,
    ) -> bool:
        def download():
            config = self._get_config(extra_config)
            config.setdefault("outtmpl", str(output_path / "video.%(ext)s"))
            if progress_callback and not config.get("progress_hooks"):
                config["progress_hooks"] = [progress_callback]
            with yt_dlp.YoutubeDL(config) as ydl:
                if ydl.download([url]) != 0:
                    raise RuntimeError("yt-dlp did not complete the download")
            return True

        return await self._run_with_retries(download, "Download")

    def get_status(self) -> Dict[str, Any]:
        delay = max(0, self.min_request_interval - (time.monotonic() - self.last_request_time))
        return {
            "failure_count": self.failure_count,
            "is_backing_off": delay > 0,
            "next_available_in": delay,
            "min_request_interval": self.min_request_interval,
            "cookies_enabled": bool(settings.YTDLP_COOKIE_FILE),
        }


_ytdlp_service = None


def get_ytdlp_service() -> YTDLPService:
    global _ytdlp_service
    if _ytdlp_service is None:
        _ytdlp_service = YTDLPService()
    return _ytdlp_service
