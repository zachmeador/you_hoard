"""
Centralized yt-dlp service with improved reliability
"""
import asyncio
import time
import random
import logging
import json
import traceback
import re
import sys
import io
import contextlib
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

    def _get_ytdlp_logger(self):
        """Create a custom logger for yt-dlp that redirects output to our logging system"""
        class YTDLPLogger:
            def debug(self, msg):
                if settings.YTDLP_VERBOSE:
                    logger.debug(f"[yt-dlp] {msg}")
            
            def info(self, msg):
                if settings.YTDLP_VERBOSE:
                    logger.info(f"[yt-dlp] {msg}")
            
            def warning(self, msg):
                logger.warning(f"[yt-dlp] {msg}")
            
            def error(self, msg):
                logger.error(f"[yt-dlp] {msg}")
        
        return YTDLPLogger()

    @contextlib.contextmanager
    def _redirect_stdout_stderr(self):
        """Redirect stdout/stderr during yt-dlp operations to prevent HTTP response corruption"""
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        
        try:
            sys.stdout = stdout_buffer
            sys.stderr = stderr_buffer
            yield
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            
            # Log any captured output if verbose is enabled
            if settings.YTDLP_VERBOSE:
                stdout_content = stdout_buffer.getvalue()
                stderr_content = stderr_buffer.getvalue()
                
                if stdout_content.strip():
                    logger.info(f"[yt-dlp stdout] {stdout_content.strip()}")
                if stderr_content.strip():
                    logger.warning(f"[yt-dlp stderr] {stderr_content.strip()}")

    def _is_permanent_error(self, error: Exception) -> bool:
        """
        Detect permanent errors that should not be retried.
        
        Returns True if the error indicates a permanent failure that won't
        be resolved by retrying (e.g., deleted videos, terminated accounts).
        """
        error_str = str(error).lower()
        
        # Patterns that indicate permanent failures
        permanent_patterns = [
            # Terminated/suspended accounts
            r'youtube account.*terminated',
            r'youtube account.*suspended',
            r'channel.*terminated',
            r'channel.*suspended',
            
            # Deleted/unavailable content
            r'video.*deleted',
            r'video.*removed',
            r'video.*no longer available',
            r'video.*unavailable',
            r'this video has been removed',
            r'private video',
            r'video.*private',
            
            # Geo-restrictions (permanent for this location)
            r'video.*not available in your country',
            r'geo.*restrict',
            r'blocked in your country',
            
            # Age restrictions without auth
            r'sign in to confirm your age',
            r'age.*restrict.*sign in',
            
            # Playlist/channel not found
            r'playlist.*does not exist',
            r'channel.*does not exist',
            r'playlist.*not found',
            r'channel.*not found',
            
            # Copyright/legal issues
            r'copyright.*claim',
            r'dmca.*takedown',
            
            # Invalid format/URL
            r'unsupported url',
            r'invalid.*url',
            r'unable to extract.*id',
        ]
        
        for pattern in permanent_patterns:
            if re.search(pattern, error_str):
                logger.info(f"Detected permanent error pattern '{pattern}': {error_str[:200]}")
                return True
                
        return False

    def _get_config(self, extra: Dict = {}) -> Dict:
        config = {
            'quiet': False,  # Always quiet to prevent stdout interference
            'verbose': False,  # Disable verbose to prevent stdout interference
            'user_agent': random.choice(self.user_agents),  # Rotate UA
            'cookiesfrombrowser': self.cookies_setup,
            'retries': settings.YTDLP_MAX_RETRIES,
            'sleep_interval': settings.YTDLP_SLEEP_INTERVAL,
            'geo_bypass': True,
            'logger': self._get_ytdlp_logger(),  # Use custom logger instead of stdout
        }
        if hasattr(settings, 'YTDLP_PROXY_URL') and settings.YTDLP_PROXY_URL:
            config['proxy'] = settings.YTDLP_PROXY_URL
        config.update(extra)
        
        # Log config excluding non-serializable objects like logger
        debug_config = {k: v for k, v in config.items() if k != 'logger'}
        logger.debug(f"Using config: {json.dumps(debug_config, indent=2)}")
        return config

    async def _run_with_retries(self, func, op_name: str, url: str, max_retries: int = settings.YTDLP_MAX_RETRIES):
        for attempt in range(1, max_retries + 1):
            try:
                await self._enforce_rate_limit()
                return await func()
            except Exception as e:
                self.failure_count += 1
                error_type = type(e).__name__
                
                # Check if this is a permanent error that shouldn't be retried
                if self._is_permanent_error(e):
                    logger.error(f"{op_name} failed permanently: {error_type} - {str(e)} | No retries will be attempted")
                    raise e  # Re-raise the original exception
                
                # If this is the last attempt, don't bother with backoff
                if attempt >= max_retries:
                    logger.error(f"{op_name} failed after {max_retries} retries: {error_type} - {str(e)} | Traceback: {traceback.format_exc()}")
                    break
                
                backoff = min(settings.YTDLP_MIN_BACKOFF * (2 ** (attempt - 1)), settings.YTDLP_MAX_BACKOFF)
                if '403' in str(e) or '429' in str(e):
                    backoff *= random.uniform(5, 10)  # Longer for blocking
                logger.error(f"{op_name} failed (attempt {attempt}/{max_retries}): {error_type} - {str(e)} | Retrying in {backoff}s")
                await asyncio.sleep(backoff)
        raise Exception(f"{op_name} failed after {max_retries} retries")

    async def _enforce_rate_limit(self):
        time_since_last = time.time() - self.last_request_time
        if time_since_last < self.min_request_interval:
            await asyncio.sleep(self.min_request_interval - time_since_last)
        self.last_request_time = time.time()

    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the YT-DLP service for monitoring
        
        Returns:
            Dict containing:
            - failure_count: Number of recent failures
            - is_backing_off: Whether service is in rate limit backoff
            - next_available_in: Seconds until next request is allowed
            - last_request_time: Timestamp of last request
            - min_request_interval: Minimum interval between requests
        """
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        next_available_in = max(0, self.min_request_interval - time_since_last)
        
        return {
            'failure_count': self.failure_count,
            'is_backing_off': next_available_in > 0,
            'next_available_in': next_available_in,
            'last_request_time': self.last_request_time,
            'min_request_interval': self.min_request_interval,
            'user_agent_count': len(self.user_agents),
            'cookies_enabled': self.cookies_setup is not None
        }

    async def extract_info(self, url: str, extra_config: Optional[Dict] = None) -> Dict[str, Any]:
        async def _extract():
            config = self._get_config(extra_config or {})
            try:
                with self._redirect_stdout_stderr():
                    with yt_dlp.YoutubeDL(config) as ydl:
                        return ydl.extract_info(url, download=False)
            except Exception as e:
                raise
        return await self._run_with_retries(_extract, 'INFO_EXTRACT', url)

    async def download_with_progress(self, url: str, output_path: Path, progress_callback=None, extra_config: Optional[Dict] = None) -> bool:
        async def _download():
            config = self._get_config(extra_config or {})
            config['outtmpl'] = str(output_path / '%(title)s.%(ext)s')
            with self._redirect_stdout_stderr():
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