"""Runtime settings the user changes in the UI, stored as JSON values."""

from typing import Any

from app.db import Database, dumps, loads

DEFAULTS: dict[str, Any] = {
    "default_quality": "1080p",
    "subtitle_languages": ["en"],
    "download_comments": False,
    "max_concurrent_downloads": 2,
    "check_interval_hours": 6,
}


class Settings:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._cache: dict[str, Any] | None = None

    async def all(self) -> dict[str, Any]:
        if self._cache is None:
            rows = await self.db.fetch_all("SELECT key, value FROM settings")
            stored = {row["key"]: loads(row["value"]) for row in rows}
            self._cache = {key: stored.get(key, default) for key, default in DEFAULTS.items()}
        return dict(self._cache)

    async def get(self, key: str) -> Any:
        return (await self.all())[key]

    async def update(self, values: dict[str, Any]) -> dict[str, Any]:
        async with self.db.transaction() as conn:
            for key, value in values.items():
                if key not in DEFAULTS:
                    raise KeyError(key)
                await conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                    (key, dumps(value)),
                )
        self._cache = None
        return await self.all()
