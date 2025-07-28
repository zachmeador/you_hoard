"""
Centralized logging setup for YouHoard
"""
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Dict, Any
from .config import settings


def setup_logging() -> None:
    """Set up comprehensive logging configuration for the application"""
    
    # Ensure log directory exists
    log_dir = settings.get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))
    
    # Clear any existing handlers
    root_logger.handlers.clear()
    
    # Create formatter
    formatter = logging.Formatter(settings.LOG_FORMAT)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler with rotation
    file_handler = logging.handlers.RotatingFileHandler(
        settings.get_log_file_path(),
        maxBytes=_parse_size(settings.LOG_ROTATION_SIZE),
        backupCount=settings.LOG_RETENTION_COUNT,
        encoding='utf-8'
    )
    file_handler.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # Configure specific loggers for better debugging
    configure_module_loggers()
    
    # Log startup message
    logger = logging.getLogger(__name__)
    logger.info("Logging system initialized")
    logger.info(f"Log level: {settings.LOG_LEVEL}")
    logger.info(f"Log file: {settings.get_log_file_path()}")


def configure_module_loggers() -> None:
    """Configure specific loggers for different modules"""
    
    # yt-dlp service logger - most verbose for debugging
    ytdlp_logger = logging.getLogger('app.core.ytdlp_service')
    ytdlp_logger.setLevel(getattr(logging, settings.YTDLP_LOG_LEVEL.upper()))
    
    # Downloader logger
    downloader_logger = logging.getLogger('app.core.downloader')
    downloader_logger.setLevel(logging.DEBUG)
    
    # Database logger
    db_logger = logging.getLogger('app.core.database')
    db_logger.setLevel(logging.INFO)
    
    # API endpoint loggers
    api_logger = logging.getLogger('app.api')
    api_logger.setLevel(logging.INFO)
    
    # External library loggers - reduce noise
    logging.getLogger('uvicorn').setLevel(logging.WARNING)
    logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
    logging.getLogger('fastapi').setLevel(logging.WARNING)
    logging.getLogger('aiosqlite').setLevel(logging.WARNING)
    logging.getLogger('watchfiles').setLevel(logging.WARNING)
    logging.getLogger('watchfiles.main').setLevel(logging.WARNING)


def _parse_size(size_str: str) -> int:
    """Parse size string like '10MB' to bytes"""
    size_str = size_str.upper()
    if size_str.endswith('KB'):
        return int(size_str[:-2]) * 1024
    elif size_str.endswith('MB'):
        return int(size_str[:-2]) * 1024 * 1024
    elif size_str.endswith('GB'):
        return int(size_str[:-2]) * 1024 * 1024 * 1024
    else:
        return int(size_str)


def get_ytdlp_logger() -> logging.Logger:
    """Get the yt-dlp specific logger"""
    return logging.getLogger('app.core.ytdlp_service')


def log_ytdlp_operation(operation: str, url: str, extra_data: Dict[str, Any] = None) -> None:
    """Helper function to log yt-dlp operations with consistent format"""
    logger = get_ytdlp_logger()
    
    # Sanitize URL for logging (remove tokens, etc.)
    sanitized_url = _sanitize_url_for_logging(url)
    
    base_msg = f"YT-DLP {operation} | URL: {sanitized_url}"
    
    if extra_data:
        details = " | ".join([f"{k}: {v}" for k, v in extra_data.items()])
        base_msg += f" | {details}"
    
    logger.info(base_msg)


def _sanitize_url_for_logging(url: str) -> str:
    """Sanitize URL for safe logging (remove sensitive tokens, truncate if too long)"""
    # Remove potential tokens or sensitive parameters
    if '?' in url:
        base_url, params = url.split('?', 1)
        # Keep only safe parameters for logging
        safe_params = []
        for param in params.split('&'):
            if '=' in param:
                key, _ = param.split('=', 1)
                if key.lower() in ['v', 'list', 'channel', 'user', 'c']:
                    safe_params.append(param)
        
        if safe_params:
            url = f"{base_url}?{'&'.join(safe_params)}"
        else:
            url = base_url
    
    # Truncate if too long
    if len(url) > 100:
        url = url[:97] + "..."
    
    return url 