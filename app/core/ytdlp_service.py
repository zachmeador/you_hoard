"""
Centralized yt-dlp service with improved reliability
"""
import asyncio
import time
import random
import logging
import json
import traceback
from typing import Dict, Any, Optional
from pathlib import Path
import yt_dlp
from .config import settings

logger = logging.getLogger(__name__)

class YTDLPService:
    def __init__(self):
        self.failure_count = 0
        self.last_request_time = 0
        self.min_request_interval = settings.YTDLP_MIN_REQUEST_INTERVAL
        self._lock = asyncio.Lock()
        self.user_agents = [  # Rotate these for better evasion
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
            settings.YTDLP_USER_AGENT  # Keep original as fallback
        ]
        self.cookies_setup = self._setup_cookies()
        logger.info("YTDLPService initialized with UA rotation and cookies")

    def _setup_cookies(self) -> Optional[tuple]:
        if not settings.YTDLP_USE_BROWSER_COOKIES:
            return None
        for browser in ['chrome', 'firefox', 'safari', 'edge']:
            try:
                return (browser, None, None, None)
            except:
                pass
        logger.warning("No browser cookies available")
        return None

    def _get_config(self, extra: Dict = {}) -> Dict:
        config = {
            'quiet': not settings.YTDLP_VERBOSE,
            'verbose': settings.YTDLP_VERBOSE,
            'user_agent': random.choice(self.user_agents),  # Rotate UA
            'cookiesfrombrowser': self.cookies_setup,
            'retries': settings.YTDLP_MAX_RETRIES,
            'sleep_interval': settings.YTDLP_SLEEP_INTERVAL,
            'geo_bypass': True,
        }
        if hasattr(settings, 'YTDLP_PROXY_URL') and settings.YTDLP_PROXY_URL:
            config['proxy'] = settings.YTDLP_PROXY_URL
        config.update(extra)
        logger.debug(f"Using config: {json.dumps(config, indent=2)}")
        return config

    async def _run_with_retries(self, func, op_name: str, url: str, max_retries: int = settings.YTDLP_MAX_RETRIES):
        for attempt in range(1, max_retries + 1):
            try:
                await self._enforce_rate_limit()
                return await func()
            except Exception as e:
                self.failure_count += 1
                error_type = type(e).__name__
                backoff = min(settings.YTDLP_MIN_BACKOFF * (2 ** (attempt - 1)), settings.YTDLP_MAX_BACKOFF)
                if '403' in str(e) or '429' in str(e):
                    backoff *= random.uniform(5, 10)  # Longer for blocking
                logger.error(f"{op_name} failed (attempt {attempt}): {error_type} - {str(e)} | Traceback: {traceback.format_exc()} | Retrying in {backoff}s")
                await asyncio.sleep(backoff)
        raise Exception(f"{op_name} failed after {max_retries} retries")

    async def _enforce_rate_limit(self):
        time_since_last = time.time() - self.last_request_time
        if time_since_last < self.min_request_interval:
            await asyncio.sleep(self.min_request_interval - time_since_last)
        self.last_request_time = time.time()

    async def extract_info(self, url: str, extra_config: Optional[Dict] = None) -> Dict[str, Any]:
        async def _extract():
            config = self._get_config(extra_config or {})
            try:
                with yt_dlp.YoutubeDL(config) as ydl:
                    return ydl.extract_info(url, download=False)
            except Exception as e:
                raise
        return await self._run_with_retries(_extract, 'INFO_EXTRACT', url)

    async def download_with_progress(self, url: str, output_path: Path, progress_callback=None, extra_config: Optional[Dict] = None) -> bool:
        async def _download():
            config = self._get_config(extra_config or {})
            config['outtmpl'] = str(output_path / '%(title)s.%(ext)s')
            with yt_dlp.YoutubeDL(config) as ydl:
                ydl.download([url])
                return True
        return await self._run_with_retries(_download, 'DOWNLOAD', url)

# Global instance (unchanged)
_ytdlp_service = None
def get_ytdlp_service() -> YTDLPService:
    global _ytdlp_service
    if _ytdlp_service is None:
        _ytdlp_service = YTDLPService()
    return _ytdlp_service 