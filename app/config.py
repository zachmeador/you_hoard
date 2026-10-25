"""Deployment configuration from environment variables or `.env`.

Settings a user changes while the app runs live in the database (app/settings.py).
"""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATA_DIR: Path = Path("data")
    MEDIA_DIR: Path = Path("media")
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    YTDLP_COOKIE_FILE: Path | None = None
    YTDLP_JS_RUNTIME: str = "deno"
    YTDLP_JS_RUNTIME_PATH: str | None = None
    YTDLP_REQUEST_INTERVAL: float = 2.0

    SESSION_DAYS: int = 30

    # Octal mask for files and folders the app creates, e.g. 002 to keep them group-writable
    # in a shared media folder. Unset leaves the inherited mask alone.
    UMASK: str | None = None

    @property
    def database_path(self) -> Path:
        return self.DATA_DIR / "youhoard.db"

    @property
    def log_dir(self) -> Path:
        return self.DATA_DIR / "logs"

    @property
    def media_root(self) -> Path:
        return self.MEDIA_DIR.resolve()


config = Config()


def apply_umask() -> None:
    if config.UMASK:
        os.umask(int(config.UMASK, 8))
