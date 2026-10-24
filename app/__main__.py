"""Command line maintenance: `python -m app <command>`."""

import argparse
import asyncio
import getpass
import sqlite3
import sys
import threading
from pathlib import Path

from app import tubearchivist
from app.auth import hash_password
from app.config import config
from app.db import Database
from app.jobs import JobRunner
from app.scanner import run_scan
from app.settings import Settings
from app.youtube import YouTube


async def rescan(args: argparse.Namespace, db: Database) -> int:
    runner = JobRunner(db, YouTube(), Settings(db))
    result = await run_scan(runner, {"id": 0}, threading.Event())
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


async def reset_password(args: argparse.Namespace, db: Database) -> int:
    password = getpass.getpass("New password: ")
    if len(password) < 8:
        print("Use at least 8 characters.", file=sys.stderr)
        return 1
    if password != getpass.getpass("Repeat: "):
        print("The passwords differ.", file=sys.stderr)
        return 1
    password_hash = hash_password(password)
    async with db.transaction() as conn:
        cursor = await conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?", (password_hash, args.username)
        )
        if not cursor.rowcount:
            print(f"No user named {args.username}.", file=sys.stderr)
            return 1
        await conn.execute("DELETE FROM sessions")
    print("Password changed; existing sessions were signed out.")
    return 0


async def backup(args: argparse.Namespace, db: Database) -> int:
    target = Path(args.path)
    if target.exists():
        print(f"{target} already exists.", file=sys.stderr)
        return 1

    def copy() -> None:
        with sqlite3.connect(db.path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)

    await asyncio.to_thread(copy)
    print(f"Database copied to {target}. Media files are not included.")
    return 0


async def import_tubearchivist(args: argparse.Namespace, db: Database) -> int:
    return await tubearchivist.run(args, db, sys.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app", description="YouHoard maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("rescan", help="Reconcile the database with the media folder").set_defaults(
        func=rescan
    )
    copy = commands.add_parser("backup", help="Copy the database safely while the app runs")
    copy.add_argument("path")
    copy.set_defaults(func=backup)
    reset = commands.add_parser("reset-password", help="Set a new password for a user")
    reset.add_argument("username")
    reset.set_defaults(func=reset_password)
    importer = commands.add_parser(
        "import-tubearchivist", help="Import a TubeArchivist library (dry run unless --apply)"
    )
    tubearchivist.add_arguments(importer)
    importer.set_defaults(func=import_tubearchivist)
    args = parser.parse_args()

    async def run() -> int:
        config.media_root.mkdir(parents=True, exist_ok=True)
        db = Database(config.database_path)
        await db.migrate()
        return await args.func(args, db)

    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
