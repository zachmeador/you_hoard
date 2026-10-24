"""SQLite access with one short-lived connection per operation, versioned by PRAGMA user_version."""

import json
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

MIGRATIONS = Path(__file__).parent / "migrations"


class LegacyDatabaseError(RuntimeError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def now() -> str:
    return iso(utcnow())


def later(**delta: float) -> str:
    return iso(utcnow() + timedelta(**delta))


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def dumps(value: Any) -> str | None:
    return None if value is None else json.dumps(value, separators=(",", ":"))


def loads(value: str | None) -> Any:
    return None if value is None else json.loads(value)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self.path, isolation_level=None) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.execute("PRAGMA busy_timeout = 10000")
            yield conn

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self.connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                await conn.execute("ROLLBACK")
                raise
            await conn.execute("COMMIT")

    async def fetch_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        async with self.connect() as conn:
            return await fetch_all(conn, sql, params)

    async def fetch_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        async with self.connect() as conn:
            return await fetch_one(conn, sql, params)

    async def fetch_value(self, sql: str, params: Iterable[Any] = ()) -> Any:
        row = await self.fetch_one(sql, params)
        return next(iter(row.values())) if row else None

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        async with self.connect() as conn:
            cursor = await conn.execute(sql, tuple(params))
            return cursor.rowcount

    async def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as conn:
            await conn.execute("PRAGMA journal_mode = WAL")
            version = (await fetch_one(conn, "PRAGMA user_version"))["user_version"]
            if version == 0 and await fetch_one(conn, "SELECT 1 FROM sqlite_master LIMIT 1"):
                raise LegacyDatabaseError(
                    f"{self.path} was created by an older development version and cannot be "
                    "upgraded. Move it aside to start with a new database; your media files are "
                    "not affected and can be added back with a library rescan."
                )
            for path in sorted(MIGRATIONS.glob("*.sql")):
                number = int(path.name.split("_", 1)[0])
                if number > version:
                    await conn.executescript(
                        f"BEGIN IMMEDIATE;\n{path.read_text()}\nPRAGMA user_version = {number};\nCOMMIT;"
                    )


async def fetch_all(
    conn: aiosqlite.Connection, sql: str, params: Iterable[Any] = ()
) -> list[dict[str, Any]]:
    async with conn.execute(sql, tuple(params)) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


async def fetch_one(
    conn: aiosqlite.Connection, sql: str, params: Iterable[Any] = ()
) -> dict[str, Any] | None:
    async with conn.execute(sql, tuple(params)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None
