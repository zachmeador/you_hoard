"""Removed videos' files, kept for a while so a removal can be undone.

Removing a video's local files moves its media and sidecars into

    <MEDIA_DIR>/.youhoard/trash/<removed at> <video id>/

next to a trashed.json manifest that records where they came from and when they expire (the
trash_days setting; 0 skips the trash). The trash sits on the media folder's filesystem, so moving
in and out is a rename. Expiry deletes only the files an entry's manifest names, directly inside
that entry; anything it doesn't recognize is left alone.
"""

import errno
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from app import layout
from app.config import config
from app.db import iso, parse_time, utcnow

MANIFEST = "trashed.json"
ENTRY_NAME = re.compile(r"\d{8}T\d{6}Z ([A-Za-z0-9_-]{11})")


class TrashError(OSError):
    pass


@dataclass
class Entry:
    path: Path
    youtube_id: str
    title: str | None
    media_path: str  # where the media file was, relative to MEDIA_DIR
    files: list[str]
    removed_at: str
    expires_at: str
    size: int


def trash_dir() -> Path:
    return config.media_root / layout.APP_DIR / "trash"


def _move(source: Path, target: Path) -> None:
    if target.exists():
        raise TrashError(f"{target.name} is already there")
    try:
        os.rename(source, target)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        shutil.move(source, target)


def move_to_trash(media_path: str, youtube_id: str, title: str | None, days: int) -> Entry:
    """Move a video's media file and sidecars into a new trash entry."""
    media = layout.media_file(media_path, youtube_id)
    files = [media, *layout.sidecars(media)]
    removed = utcnow()
    entry = trash_dir() / f"{removed:%Y%m%dT%H%M%SZ} {youtube_id}"
    entry.mkdir(parents=True)
    manifest = {
        "youtube_id": youtube_id,
        "title": title,
        "media_path": layout.relative(media),
        "files": [path.name for path in files],
        "removed_at": iso(removed),
        "expires_at": iso(removed + timedelta(days=days)),
    }
    (entry / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    moved: list[Path] = []
    try:
        for path in files:
            _move(path, entry / path.name)
            moved.append(path)
    except OSError as error:
        for path in reversed(moved):
            _move(entry / path.name, path)
        (entry / MANIFEST).unlink()
        entry.rmdir()
        raise TrashError(f"Couldn't move the files to the trash: {error}") from error
    layout.remove_if_empty(media.parent)
    return read_entry(entry)


def read_entry(path: Path) -> Entry | None:
    match = ENTRY_NAME.fullmatch(path.name)
    if not match or not path.is_dir():
        return None
    try:
        manifest = json.loads((path / MANIFEST).read_text("utf-8"))
        files = [str(name) for name in manifest["files"]]
        if manifest["youtube_id"] != match.group(1) or not files:
            return None
        if any("/" in name or name in ("", ".", "..", MANIFEST) for name in files):
            return None
        if parse_time(manifest["expires_at"]) is None:
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    size = sum((path / name).stat().st_size for name in files if (path / name).is_file())
    return Entry(
        path=path,
        youtube_id=match.group(1),
        title=manifest.get("title"),
        media_path=str(manifest["media_path"]),
        files=files,
        removed_at=str(manifest["removed_at"]),
        expires_at=str(manifest["expires_at"]),
        size=size,
    )


def entries() -> list[Entry]:
    root = trash_dir()
    if not root.is_dir():
        return []
    found = (read_entry(path) for path in sorted(root.iterdir()))
    return [entry for entry in found if entry is not None]


def latest(youtube_id: str) -> Entry | None:
    """The most recent trash entry for a video, if it still has its media file."""
    for entry in reversed(entries()):
        if entry.youtube_id == youtube_id and (entry.path / entry.files[0]).is_file():
            return entry
    return None


def restore(entry: Entry) -> Path:
    """Move an entry's files back where they came from; refuse if anything is in the way."""
    media = layout.resolve(entry.media_path)
    if layout.video_id_from_media(media) != entry.youtube_id:
        raise TrashError("The trash entry doesn't belong to this video")
    present = [name for name in entry.files if (entry.path / name).is_file()]
    taken = [name for name in present if (media.parent / name).exists()]
    if taken:
        raise TrashError(f"{taken[0]} already exists in {media.parent.name}")
    media.parent.mkdir(parents=True, exist_ok=True)
    for name in present:
        _move(entry.path / name, media.parent / name)
    (entry.path / MANIFEST).unlink()
    entry.path.rmdir()
    return media


def delete(entry: Entry) -> None:
    for name in entry.files:
        path = entry.path / name
        if path.is_file():
            path.unlink()
    (entry.path / MANIFEST).unlink(missing_ok=True)
    try:
        entry.path.rmdir()
    except OSError:
        pass  # something else is in there; leave it


def purge() -> int:
    """Delete entries past their expiry. Returns how many went."""
    current = utcnow()
    expired = [entry for entry in entries() if parse_time(entry.expires_at) <= current]
    for entry in expired:
        delete(entry)
    return len(expired)


def summary() -> dict[str, int]:
    found = entries()
    return {"videos": len(found), "size": sum(entry.size for entry in found)}
