"""
Configuration management for YouHoard
"""
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings"""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    # Database settings
    DATABASE_PATH: str = "youhoard.db"
    
    # Storage settings
    STORAGE_PATH: str = "./storage"
    TEMP_PATH: str = "./storage/temp"
    
    # Download settings
    DEFAULT_QUALITY: str = "1080p"
    MAX_CONCURRENT_DOWNLOADS: int = 2
    DEFAULT_CHECK_CRON: str = "0 * * * *"  # Hourly by default
    
    # YouTube settings
    YOUTUBE_API_KEY: Optional[str] = None
    DEFAULT_AUDIO_TRACKS: list[str] = ["en", "original"]
    
    # Cleanup settings
    CLEANUP_ENABLED: bool = False
    CLEANUP_DAYS: int = 365
    
    # Download format settings
    FORMAT_SELECTOR: str = "bestvideo[height<=?1080]+bestaudio/best"
    AUDIO_QUALITY: str = "0"  # Best quality
    SUBTITLE_LANGUAGES: list[str] = ["en", "auto"]
    EMBED_SUBS: bool = True
    WRITE_INFO_JSON: bool = True
    WRITE_THUMBNAIL: bool = True
    
    # Format compatibility settings (prioritize compatibility over quality)
    MERGE_OUTPUT_FORMAT: str = "mp4"  # Always merge to MP4 container
    REMUX_VIDEO: str = "mp4"  # Force MP4 output format
    FORMAT_SORT: list[str] = [
        "vcodec:h264",    # Prefer H.264 (most compatible)
        "lang",           # Language preference
        "quality",        # Quality preference  
        "res",            # Resolution preference
        "fps",            # Frame rate preference
        "hdr:12",         # Prefer non-HDR for compatibility
        "acodec:aac"      # Prefer AAC audio (most compatible)
    ]
    
    # Security settings
    SECRET_KEY: str = "your-secret-key-here-change-in-production"
    SESSION_EXPIRE_MINUTES: int = 43200  # 30 days
    
    # Logging settings
    LOG_LEVEL: str = "DEBUG"
    LOG_DIR: str = "./logs"
    LOG_FILE: str = "youhoard.log"
    YTDLP_LOG_LEVEL: str = "DEBUG"  # More verbose for yt-dlp operations
    LOG_ROTATION_SIZE: str = "10MB"
    LOG_RETENTION_COUNT: int = 5
    LOG_FORMAT: str = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    
    # YT-DLP Anti-blocking settings
    YTDLP_MIN_REQUEST_INTERVAL: float = 3.0  # Minimum seconds between requests
    YTDLP_MIN_BACKOFF: float = 2.0  # Starting backoff time in seconds
    YTDLP_MAX_BACKOFF: float = 600.0  # Maximum backoff time in seconds
    YTDLP_USE_BROWSER_COOKIES: bool = False  # Try to use browser cookies
    YTDLP_USER_AGENT: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    YTDLP_TIMEOUT_EXTRACT: int = 90  # Timeout for info extraction (seconds)
    YTDLP_TIMEOUT_PLAYLIST: int = 120  # Timeout for playlist extraction (seconds)
    YTDLP_TIMEOUT_DOWNLOAD: int = 900  # Timeout for downloads (seconds)
    YTDLP_MAX_RETRIES: int = 5  # Maximum retries for failed operations
    YTDLP_BACKOFF_FACTOR: float = 2.0
    YTDLP_SLEEP_INTERVAL: int = 2  # Base sleep interval between operations
    YTDLP_PLAYLIST_LIMIT: int = 50  # Maximum playlist items to process at once
    PLAYLIST_BATCH_SIZE: int = 50  # Process playlists in batches to avoid overload
    YTDLP_VERBOSE: bool = True  # Enable verbose output from yt-dlp for debugging
    
    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    def get_storage_path(self) -> Path:
        """Get storage path as Path object"""
        return Path(self.STORAGE_PATH)
    
    def get_temp_path(self) -> Path:
        """Get temp path as Path object"""
        return Path(self.TEMP_PATH)

    def get_log_dir(self) -> Path:
        """Get log directory as Path object"""
        return Path(self.LOG_DIR)

    def get_log_file_path(self) -> Path:
        """Get full log file path"""
        return self.get_log_dir() / self.LOG_FILE


# Global settings instance
settings = Settings() 