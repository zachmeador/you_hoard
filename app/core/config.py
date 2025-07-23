"""
Configuration management for You Hoard
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
    DATABASE_PATH: str = "you_hoard.db"
    
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
    
    # Security settings
    SECRET_KEY: str = "your-secret-key-here-change-in-production"
    SESSION_EXPIRE_MINUTES: int = 43200  # 30 days
    
    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = False
    
    def get_storage_path(self) -> Path:
        """Get storage path as Path object"""
        path = Path(self.STORAGE_PATH)
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def get_temp_path(self) -> Path:
        """Get temp path as Path object"""
        path = Path(self.TEMP_PATH)
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def get_channel_path(self, channel_youtube_id: str, channel_name: str) -> Path:
        """Get channel directory path"""
        # Sanitize channel name
        safe_name = "".join(c for c in channel_name if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_name = safe_name.replace(' ', '_')[:50]
        
        channel_dir = self.get_storage_path() / "channels" / f"{channel_youtube_id}_{safe_name}"
        channel_dir.mkdir(parents=True, exist_ok=True)
        return channel_dir
        safe_name = "".join(c for c in channel_name if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_name = safe_name.replace(' ', '_')
        channel_dir = f"{channel_id}_{safe_name}"
        path = self.get_storage_path() / "channels" / channel_dir
        path.mkdir(parents=True, exist_ok=True)
        return path


# Create global settings instance
settings = Settings() 