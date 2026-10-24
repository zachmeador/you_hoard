"""TubeArchivist import: adopt a TubeArchivist library without re-downloading anything.

TubeArchivist (TA) keeps its metadata only in Elasticsearch. Its media folder holds
<channel id>/<video id>.mp4 with <video id>.<lang>.vtt subtitles, and its cache holds video
thumbnails at videos/<first id character, lowercased>/<video id>.jpg. This module reads TA's
documents from a backup or a live Elasticsearch, maps them onto YouHoard's tables and writes
each video's metadata (comments included) to an .info.json sidecar, so it outlives both apps.
With --organize it also renames the files into YouHoard's layout.

A backup is <cache>/backup/ta_backup-<date>-<reason>.zip holding es_<index>-<date>-<page>.json
files in Elasticsearch bulk format: an action line ({"index": {"_index": "ta_video", "_id": …}})
followed by the document. Files without action lines, JSON arrays (the ta_<index>-<date>.json
copies in very old backups) and dumps of search hits are read too.

Without --apply nothing is written: the run only reports what an import would do. Running the
import again leaves videos already in the library alone, apart from writing sidecars they lack
and, with --organize, renaming files whose names YouHoard cannot match to their video.
"""

import argparse
import io
import json
import os
import random
import re
import shlex
import shutil
import zipfile
import zlib
from collections import Counter, defaultdict
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple, TextIO

import aiosqlite
import httpx

from app import layout
from app.config import config
from app.db import Database, dumps, fetch_one, iso, later, now
from app.library import (
    classify,
    ensure_video,
    published_at,
    record_archived,
    save_video_info,
    upsert_channel,
    write_info_json,
)

# Indexes in the order they are read: channels before videos, videos before everything that
# refers to them.
READ_ORDER = ("config", "channel", "video", "playlist", "download", "comment")
KNOWN_INDEXES = {*READ_ORDER, "subtitle"}
INDEX_ALIASES = {
    "videos": "video",
    "channels": "channel",
    "playlists": "playlist",
    "downloads": "download",
    "comments": "comment",
    "subtitles": "subtitle",
}
JSON_SUFFIXES = (".json", ".ndjson", ".jsonl")
BULK_ACTIONS = ("index", "create", "update", "delete")
VIDEO_TYPES = {"videos": "video", "shorts": "short", "streams": "live"}
TYPE_ORDER = ("video", "short", "live")
# Per-channel overwrite and global setting for each channel tab's subscription size; TA skips a
# tab whose size is 0.
SIZE_SETTINGS = {
    "video": ("subscriptions_channel_size", "channel_size"),
    "short": ("subscriptions_shorts_channel_size", "shorts_channel_size"),
    "live": ("subscriptions_live_channel_size", "live_channel_size"),
}
TA_CHANNEL_FOLDER = re.compile(r"UC[A-Za-z0-9_-]{22}")
# Media names before TubeArchivist 0.4: <YYYYMMDD>_<video id>_<title>.mp4 in a channel-name folder.
LEGACY_NAME = re.compile(r"\d{8}_([A-Za-z0-9_-]{11})_")
# Folder names TubeArchivist's own scanner skips (besides dot-folders).
IGNORED_FOLDERS = {"@eaDir", "Icon\r\r", "Network Trash Folder", "Temporary Items"}
BATCH = 500
EXAMPLES = 5
PROGRESS_EVERY = 2000
# Comment documents can hold thousands of comments each, so they are fetched in small pages.
COMMENT_PAGE = 25
# Elasticsearch refuses requests over 100 MB by default, so no real document comes close.
MAX_DOCUMENT = 128 << 20
MAX_EPOCH = 253402300799  # 9999-12-31
BACKUP_DATE = re.compile(r"[-_](\d{8})(?=[-.])")

UNRECOGNIZED_NAME = (
    "files kept under names YouHoard cannot match to their video (pre-0.4 TubeArchivist naming); "
    "a library rescan will mark them missing, so import or re-run with --organize to rename them"
)
LEGACY_ORPHAN = (
    "orphan files under pre-0.4 TubeArchivist names, which YouHoard cannot match to their video; "
    "rename them to <video id>.mp4, otherwise a library rescan will mark them missing"
)
EXTRA_COPY = "extra copies of videos that already have a file (left alone)"
SYMLINK = "symbolic links to video files (not imported; YouHoard needs the files themselves)"
TAKEN = "videos whose new name is already taken, left in place"
# Info keys about the channel, which save_video_info would otherwise write to the channel row.
VIDEO_ONLY = {"channel", "uploader", "channel_follower_count"}


class ImportProblem(Exception):
    """Stops the import: bad options or an unreadable source."""


class Document(NamedTuple):
    index: str | None
    id: str | None
    source: dict[str, Any]


class Existing(NamedTuple):
    id: int
    media_path: str | None
    # Known only from a file or a listing: no metadata has ever been saved for it.
    placeholder: bool
    watched: bool
    unavailable: bool


@dataclass
class ChannelInfo:
    youtube_id: str
    name: str | None = None
    description: str | None = None
    subscribers: int | None = None
    subscribed: bool = False
    active: bool = True
    overwrites: dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoPlan:
    youtube_id: str
    info: dict[str, Any]
    video_type: str
    channel: ChannelInfo | None
    media: Path | None = None
    size: int = 0
    archived_at: str | None = None
    unavailable_at: str | None = None
    watched_at: str | None = None
    move: tuple[Path, str] | None = None
    write_info: bool = False
    thumbnail: Path | None = None
    moved: bool = False
    # A video already in the library: only its missing sidecars or unusable file name are fixed.
    repair_of: int | None = None


class OrphanPlan(NamedTuple):
    youtube_id: str
    path: Path
    channel: ChannelInfo | None
    thumbnail: Path | None


class Tombstone(NamedTuple):
    youtube_id: str
    title: str | None
    video_type: str
    channel_id: str | None
    duration: int | None
    published_at: str | None


# Values


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _epoch(value: Any) -> int | None:
    """Seconds since the epoch from TA's epoch_second fields (int, float or digit string)."""
    number = _number(value)
    if number is None or number <= 0:
        return None
    number = number // 1000 if number > 10**11 else number  # milliseconds
    return number if number <= MAX_EPOCH else None


def _moment(value: Any) -> str | None:
    epoch = _epoch(value)
    return iso(datetime.fromtimestamp(epoch, UTC)) if epoch else None


def _published(value: Any) -> tuple[str | None, int | None]:
    """(upload_date as YYYYMMDD, timestamp) from TA's `published`: epoch seconds or a date."""
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 8 and text.isdigit():
            try:
                return datetime.strptime(text, "%Y%m%d").strftime("%Y%m%d"), None
            except ValueError:
                return None, None
        if not text.isdigit():
            try:
                moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None, None
            if len(text) == 10:
                return moment.strftime("%Y%m%d"), None
            value = int((moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp())
    epoch = _epoch(value)
    if epoch is None:
        return None, None
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y%m%d"), epoch


def _duration(value: Any) -> int | None:
    """Seconds from a number, "HH:MM:SS" or TA's "1h 02m 03s"."""
    number = _number(value)
    if number is not None:
        return number if number > 0 else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if re.fullmatch(r"\d+(:\d{1,2}){1,2}", text):
        seconds = 0
        for part in text.split(":"):
            seconds = seconds * 60 + int(part)
        return seconds or None
    units = {"y": 31536000, "d": 86400, "h": 3600, "m": 60, "s": 1}
    parts = re.findall(r"(\d+)\s*([ydhms])", text)
    return sum(int(count) * units[unit] for count, unit in parts) or None


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return []


def _dimensions(streams: Any) -> tuple[int | None, int | None]:
    """Width and height of the largest video stream in TA's ffprobe summary."""
    best: tuple[int | None, int | None] = (None, None)
    for stream in streams if isinstance(streams, list) else ():
        if not isinstance(stream, dict) or stream.get("type", "video") != "video":
            continue
        width, height = _number(stream.get("width")), _number(stream.get("height"))
        if width and height and width * height > (best[0] or 0) * (best[1] or 0):
            best = (width, height)
    return best


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _short(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def human_size(size: float) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    unit = 0
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024
        unit += 1
    return f"{size:.0f} B" if unit == 0 else f"{size:.1f} {units[unit]}"


def _is_video_name(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in layout.VIDEO_EXTENSIONS


def _shown(path: Path) -> str:
    """A path for the report: relative to MEDIA_DIR when inside it, without following links."""
    try:
        return path.relative_to(config.media_root).as_posix()
    except ValueError:
        return str(path)


def media_id(path: Path) -> str | None:
    """The video ID a media file's name carries, including TA's pre-0.4 names."""
    if path.suffix.lower() not in layout.VIDEO_EXTENSIONS:
        return None
    if youtube_id := layout.video_id_from_media(path):
        return youtube_id
    match = LEGACY_NAME.match(path.stem)
    return match.group(1) if match else None


def folder_channel(folder: str) -> ChannelInfo | None:
    """The channel of TA's "<channel id>" or YouHoard's "<name> [<channel id>]" folders."""
    if TA_CHANNEL_FOLDER.fullmatch(folder):
        return ChannelInfo(folder)
    if folder.endswith("]") and " [" in folder:
        name, _, channel_id = folder[:-1].rpartition(" [")
        if TA_CHANNEL_FOLDER.fullmatch(channel_id):
            return ChannelInfo(channel_id, name or None)
    return None


def cached_thumbnail(cache: Path | None, youtube_id: str) -> Path | None:
    if cache is None:
        return None
    path = cache / "videos" / youtube_id[0].lower() / f"{youtube_id}.jpg"
    return path if path.is_file() else None


def info_owner(path: Path) -> str:
    """Who wrote an .info.json: "missing", "ours" (this import) or "foreign"."""
    if not path.exists():
        return "missing"
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "foreign"
    return "ours" if isinstance(info, dict) and "_tubearchivist" in info else "foreign"


def copy_file(source: Path, target: Path) -> None:
    temporary = target.with_name(target.name + ".tmp")
    shutil.copyfile(source, temporary)
    os.replace(temporary, target)


# Mapping


def channel_info(doc: dict[str, Any], fallback_id: Any = None) -> ChannelInfo | None:
    """A channel from a ta_channel document or the `channel` nested in a video document."""
    youtube_id = doc.get("channel_id") or fallback_id
    if not isinstance(youtube_id, str) or not layout.CHANNEL_ID.fullmatch(youtube_id):
        return None
    return ChannelInfo(
        youtube_id=youtube_id,
        name=_text(doc.get("channel_name")),
        description=_text(doc.get("channel_description")),
        subscribers=_number(doc.get("channel_subs")),
        subscribed=doc.get("channel_subscribed") is True,
        active=doc.get("channel_active") is not False,
        overwrites=_dict(doc.get("channel_overwrites")),
    )


def video_info(doc: dict[str, Any], youtube_id: str, channel: ChannelInfo | None) -> dict[str, Any]:
    """A yt-dlp-style info dict for a ta_video document, keeping the document itself."""
    upload_date, timestamp = _published(doc.get("published"))
    player, stats = _dict(doc.get("player")), _dict(doc.get("stats"))
    width, height = _dimensions(doc.get("streams"))
    info: dict[str, Any] = {
        "id": youtube_id,
        "title": _text(doc.get("title")) or youtube_id,
        "description": _text(doc.get("description")),
        "upload_date": upload_date,
        "timestamp": timestamp,
        "duration": _duration(player.get("duration")),
        "view_count": _number(stats.get("view_count")),
        "like_count": _number(stats.get("like_count")),
        "tags": _strings(doc.get("tags")),
        "categories": _strings(doc.get("category")),
        "webpage_url": f"https://www.youtube.com/watch?v={youtube_id}",
        "thumbnail": _text(doc.get("vid_thumb_url")),
        "width": width,
        "height": height,
        "comment_count": _number(doc.get("comment_count")),
        "extractor": "youtube",
        "extractor_key": "Youtube",
    }
    if channel is not None:
        info |= {
            "channel_id": channel.youtube_id,
            "channel": channel.name,
            "uploader": channel.name,
            "channel_url": f"https://www.youtube.com/channel/{channel.youtube_id}",
            "channel_follower_count": channel.subscribers,
        }
    if doc.get("vid_type") == "streams":
        info |= {"was_live": True, "live_status": "was_live"}
    info = {key: value for key, value in info.items() if value is not None}
    info["_tubearchivist"] = doc
    return info


COMMENT_FIELDS = {
    "comment_id": "id",
    "comment_parent": "parent",
    "comment_text": "text",
    "comment_likecount": "like_count",
    "comment_author": "author",
    "comment_author_id": "author_id",
    "comment_author_thumbnail": "author_thumbnail",
    "comment_author_is_uploader": "author_is_uploader",
    "comment_is_favorited": "is_favorited",
    "comment_timestamp": "timestamp",
    "comment_time_text": "_time_text",
}


def ytdlp_comment(comment: dict[str, Any]) -> dict[str, Any]:
    """TA's comment fields renamed to yt-dlp's; unknown fields are kept as they are."""
    converted = {COMMENT_FIELDS.get(key, key): value for key, value in comment.items()}
    converted["parent"] = converted.get("parent") or "root"
    return {key: value for key, value in converted.items() if value is not None}


# Reading documents


def iter_json_values(stream: TextIO, chunk_size: int = 1 << 20) -> Iterator[Any]:
    """The JSON values in a stream: nd-json, concatenated JSON, or the items of an array that
    is the whole file."""
    decoder = json.JSONDecoder()
    buffer, position, at_end, in_array, started = "", 0, False, False, False

    def refill(wanted: int) -> None:
        nonlocal buffer, position, at_end
        if wanted > MAX_DOCUMENT:
            raise ValueError("a document is larger than 128 MiB, or the file is malformed")
        chunk = stream.read(max(chunk_size, wanted))
        at_end = not chunk
        buffer, position = buffer[position:] + chunk, 0

    while True:
        while True:
            while position < len(buffer) and (
                buffer[position] in " \t\r\n" or (in_array and buffer[position] == ",")
            ):
                position += 1
            if position < len(buffer) or at_end:
                break
            refill(0)
        if position >= len(buffer):
            return
        if buffer[position] == "[" and not started:
            in_array, started, position = True, True, position + 1
            continue
        if buffer[position] == "]" and in_array:
            in_array, position = False, position + 1
            continue
        try:
            value, end = decoder.raw_decode(buffer, position)
        except json.JSONDecodeError:
            if at_end:
                raise
            refill(len(buffer) - position)
            continue
        # A number near the end of the buffer may continue in the next chunk.
        near_end = end == len(buffer) or (isinstance(value, int | float) and len(buffer) - end < 64)
        if near_end and not at_end:
            refill(len(buffer) - position)
            continue
        position, started = end, True
        yield value


def normalize_index(name: Any) -> str | None:
    """The index for an Elasticsearch name: "video" for "ta_video", "ta_video_v2" or "videos"."""
    if not isinstance(name, str):
        return None
    name = re.sub(r"_v\d+$", "", name.strip().lower()).removeprefix("ta_")
    name = INDEX_ALIASES.get(name, name)
    return name if name in KNOWN_INDEXES else None


def index_from_name(name: str) -> str | None:
    """The index a backup file holds, from es_<index>-<date>-<page>.json or ta_<index>-….json."""
    base = PurePosixPath(name).name.lower()
    for prefix in ("es_", "ta_"):
        base = base.removeprefix(prefix)
    return normalize_index(re.split(r"[-.]", base, maxsplit=1)[0])


def infer_index(source: dict[str, Any]) -> str | None:
    """The index a document belongs to, from its fields."""
    keys = source.keys()
    if "comment_comments" in keys:
        return "comment"
    if "subtitle_line" in keys or "subtitle_fragment_id" in keys:
        return "subtitle"
    if "playlist_id" in keys and ("playlist_entries" in keys or "playlist_name" in keys):
        return "playlist"
    if "youtube_id" in keys and (
        "media_url" in keys or "player" in keys or isinstance(source.get("channel"), dict)
    ):
        return "video"
    if "youtube_id" in keys and "status" in keys:
        return "download"
    if "channel_id" in keys and "channel_name" in keys:
        return "channel"
    if "subscriptions" in keys and "downloads" in keys:
        return "config"
    return None


def iter_documents(stream: TextIO, name_index: str | None) -> Iterator[Document]:
    """Documents from bulk nd-json (action line + source), plain documents or search hits."""
    action: tuple[str, dict[str, Any]] | None = None
    for value in iter_json_values(stream):
        if not isinstance(value, dict):
            continue
        if len(value) == 1:
            kind, meta = next(iter(value.items()))
            if (
                kind in BULK_ACTIONS
                and isinstance(meta, dict)
                and ("_index" in meta or "_id" in meta)
            ):
                action = None if kind == "delete" else (kind, meta)
                continue
        if action is not None:
            (kind, meta), action = action, None
            source = value.get("doc", value) if kind == "update" else value
            if isinstance(source, dict):
                index = normalize_index(meta.get("_index")) or name_index or infer_index(source)
                yield Document(index, _id_text(meta.get("_id")), source)
            continue
        hit = value.get("_source")
        if isinstance(hit, dict) and ("_id" in value or "_index" in value):
            index = normalize_index(value.get("_index")) or name_index or infer_index(hit)
            yield Document(index, _id_text(value.get("_id")), hit)
            continue
        yield Document(name_index or infer_index(value), None, value)


def _id_text(value: Any) -> str | None:
    return None if value is None else str(value)


def document_key(index: str, document: Document) -> str | None:
    key_field = {"channel": "channel_id", "playlist": "playlist_id"}.get(index, "youtube_id")
    key = document.source.get(key_field) if index != "config" else None
    return str(key) if isinstance(key, str) and key else document.id


class BackupSource:
    """A backup zip, a folder of its extracted files, or a single JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.archive = (
            zipfile.ZipFile(path) if path.is_file() and zipfile.is_zipfile(path) else None
        )
        if self.archive is not None:
            names = [item.filename for item in self.archive.infolist() if not item.is_dir()]
        elif path.is_dir():
            names = [child.name for child in path.iterdir() if child.is_file()]
        else:
            names = [path.name]
        if self.archive is not None or path.is_dir():
            names = [name for name in names if name.lower().endswith(JSON_SUFFIXES)]
        self.problems: list[tuple[str, str]] = []
        self.unrecognized = 0
        self.copies = 0
        self.members = self._select(names)
        self._counted: set[str] = set()
        self._broken: set[str] = set()

    def _select(self, names: list[str]) -> list[tuple[str, str | None]]:
        """The files to read, as (name, index from the name).

        Very old backups hold every index twice, as bulk es_<index> files and ta_<index> arrays:
        the bulk files are read. TubeArchivist's backup also zips whatever an unfinished earlier
        backup left in its folder, so only the newest date's files of an index are read.
        """
        found = sorted((name, index_from_name(name), _backup_date(name)) for name in names)
        bulk = {index for name, index, _ in found if index and _is_bulk_file(name)}
        newest: dict[str, str] = {}
        for name, index, date in found:
            if index and date and (index not in bulk or _is_bulk_file(name)):
                newest[index] = max(newest.get(index, date), date)
        members = []
        for name, index, date in found:
            if index in bulk and not _is_bulk_file(name):
                self.copies += 1
            elif index and date and date < newest[index]:
                self.problems.append(
                    (
                        "backup files left from an unfinished earlier backup (skipped; the "
                        "newest backup's files were read)",
                        name,
                    )
                )
            else:
                members.append((name, index))
        return members

    def describe(self) -> str:
        files = f"{len(self.members)} file{'s' if len(self.members) != 1 else ''}"
        note = f", {self.copies} duplicate copies skipped" if self.copies else ""
        return f"backup {self.path} ({files}{note})"

    def _open(self, name: str) -> TextIO:
        if self.archive is not None:
            raw = self.archive.open(name)
        else:
            raw = (self.path / name if self.path.is_dir() else self.path).open("rb")
        return io.TextIOWrapper(raw, encoding="utf-8-sig")

    async def documents(self, index: str) -> AsyncIterator[Document]:
        for name, name_index in self.members:
            if name_index not in (index, None):
                continue
            count_unknown = name_index is None and name not in self._counted
            self._counted.add(name)
            read = 0
            try:
                with self._open(name) as stream:
                    for document in iter_documents(stream, name_index):
                        read += 1
                        if document.index == index:
                            yield document
                        elif document.index is None and count_unknown:
                            self.unrecognized += 1
            except (ValueError, OSError, EOFError, zipfile.BadZipFile, zlib.error) as error:
                if name not in self._broken:
                    self._broken.add(name)
                    message = "backup files that could not be read to the end (rest skipped)"
                    self.problems.append((message, f"{name} after {read} documents: {error}"))

    async def close(self) -> None:
        if self.archive is not None:
            self.archive.close()


def _is_bulk_file(name: str) -> bool:
    return PurePosixPath(name).name.lower().startswith("es_")


def _backup_date(name: str) -> str | None:
    match = BACKUP_DATE.search(PurePosixPath(name).name)
    return match.group(1) if match else None


class ElasticSource:
    """TubeArchivist's Elasticsearch, read with the scroll API."""

    def __init__(
        self,
        url: str,
        user: str,
        password: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = (url if "://" in url else f"http://{url}").rstrip("/")
        self.problems: list[tuple[str, str]] = []
        self.unrecognized = 0
        self.client = httpx.AsyncClient(
            base_url=self.url,
            auth=(user, password) if password else None,
            timeout=httpx.Timeout(120.0),
            transport=transport,
        )

    def describe(self) -> str:
        return f"Elasticsearch at {self.url}"

    async def documents(self, index: str) -> AsyncIterator[Document]:
        size = COMMENT_PAGE if index == "comment" else 500
        body = {"size": size, "sort": ["_doc"], "track_total_hits": True}
        data = await self._post(f"/ta_{index}/_search", body, {"scroll": "5m"}, index)
        if data is None:
            return
        total = _dict(data.get("hits")).get("total")
        total = _number(total.get("value") if isinstance(total, dict) else total)
        scroll_id = data.get("_scroll_id")
        returned, incomplete = 0, False
        try:
            while data and (hits := _dict(data.get("hits")).get("hits")):
                shards = _dict(data.get("_shards"))
                incomplete = incomplete or bool(data.get("timed_out") or shards.get("failed"))
                for hit in hits:
                    if isinstance(hit, dict) and isinstance(hit.get("_source"), dict):
                        returned += 1
                        found = normalize_index(hit.get("_index")) or index
                        yield Document(found, _id_text(hit.get("_id")), hit["_source"])
                if not scroll_id:
                    break
                data = await self._post("/_search/scroll", {"scroll": "5m", "scroll_id": scroll_id})
                scroll_id = (data or {}).get("_scroll_id") or scroll_id
        finally:
            if scroll_id:
                # Best effort: an abandoned scroll expires on its own after five minutes.
                with suppress(Exception):
                    await self.client.request(
                        "DELETE", "/_search/scroll", json={"scroll_id": scroll_id}
                    )
        if incomplete or (total is not None and returned < total):
            counted = f"{returned:,} of {total:,}" if total is not None else f"{returned:,}"
            self.problems.append(
                (
                    "Elasticsearch returned incomplete results (timeouts, failed shards or "
                    "missing documents); run the import again",
                    f"ta_{index}: {counted}",
                )
            )

    async def _post(
        self,
        path: str,
        body: dict[str, Any],
        params: dict[str, str] | None = None,
        index: str | None = None,
    ) -> dict[str, Any] | None:
        """The JSON response, or None when the index does not exist."""
        try:
            response = await self.client.post(path, json=body, params=params)
        except httpx.HTTPError as error:
            raise ImportProblem(f"Could not reach Elasticsearch at {self.url}: {error}") from error
        if response.status_code == 404 and index is not None:
            if index != "config":
                self.problems.append(("Elasticsearch indexes not found", f"ta_{index}"))
            return None
        if response.status_code == 401:
            raise ImportProblem(
                "Elasticsearch rejected the login (HTTP 401). Pass --es-user and --es-password, "
                "or set TA_ES_PASSWORD (TubeArchivist's ELASTIC_PASSWORD)."
            )
        if response.is_error:
            raise ImportProblem(
                f"Elasticsearch answered HTTP {response.status_code} to {path}: "
                f"{response.text[:300]}"
            )
        return response.json()

    async def close(self) -> None:
        await self.client.aclose()


# Report


class Tally:
    def __init__(self) -> None:
        self.count = 0
        self.examples: list[str] = []

    def add(self, example: str | None = None, amount: int = 1) -> None:
        self.count += amount
        if example is not None and len(self.examples) < EXAMPLES:
            self.examples.append(example)

    def __str__(self) -> str:
        if not self.examples:
            return f"{self.count:,}"
        more = ", …" if self.count > len(self.examples) else ""
        return f"{self.count:,} ({', '.join(self.examples)}{more})"


@dataclass
class Report:
    documents: Counter[str] = field(default_factory=Counter)
    channels: int = 0
    channels_new: int = 0
    with_files: int = 0
    size: int = 0
    missing: Tally = field(default_factory=Tally)
    already: int = 0
    repaired: int = 0
    rescanned: int = 0
    orphans: Tally = field(default_factory=Tally)
    unavailable: int = 0
    watched: int = 0
    subscriptions: Counter[str] = field(default_factory=Counter)
    ignored: int = 0
    ignored_known: int = 0
    pending: int = 0
    custom: Tally = field(default_factory=Tally)
    unsubscribed: int = 0
    comments: int = 0
    comment_videos: int = 0
    thumbnails: int = 0
    moves: Tally = field(default_factory=Tally)
    warnings: dict[str, Tally] = field(default_factory=dict)

    def warn(self, message: str, example: str | None = None, amount: int = 1) -> None:
        self.warnings.setdefault(message, Tally()).add(example, amount)

    def write(self, out: TextIO, importer: "Importer", error: str | None = None) -> None:
        options = importer.options
        if error:
            mode = "stopped by an error"
        elif options.apply:
            mode = "applied"
        else:
            mode = "dry run: nothing was written"
        if options.ta_cache is None:
            cache = "not given, so no thumbnails are copied (use --ta-cache)"
        else:
            found = " (found next to the backup)" if options.cache_detected else ""
            cache = f"{options.ta_cache}{found}"
        documents = ", ".join(
            f"{self.documents[index]:,} {index}" for index in READ_ORDER if self.documents[index]
        )
        subscriptions = self.subscriptions
        if options.subscriptions:
            subscribed = (
                f"{subscriptions['channel']:,} channels, {subscriptions['playlist']:,} playlists"
            )
            if subscriptions["existing"]:
                subscribed += f" ({subscriptions['existing']:,} already existed)"
        else:
            subscribed = (
                f"not imported (--no-subscriptions): {subscriptions['channel skipped']:,} "
                f"channels, {subscriptions['playlist skipped']:,} playlists"
            )
        ignored = f"{self.ignored:,} videos marked as removed"
        if self.ignored_known:
            ignored += f" ({self.ignored_known:,} more already in the library)"
        rows = [
            ("Channels", f"{self.channels:,} ({self.channels_new:,} new)"),
            ("Videos with files", f"{self.with_files:,} ({human_size(self.size)})"),
            ("Videos missing files", f"{self.missing}"),
            ("Orphan files", f"{self.orphans}"),
            ("Unavailable on YouTube", f"{self.unavailable:,}"),
            ("Watched", f"{self.watched:,}"),
            ("Subscriptions", subscribed),
            ("Ignore list", ignored),
            ("Pending downloads", f"{self.pending:,} (not imported)"),
            ("Custom playlists", f"{self.custom} (not imported)"),
            ("Unsubscribed playlists", f"{self.unsubscribed:,} (not imported)"),
            ("Comments", f"{self.comments:,} on {self.comment_videos:,} videos"),
            ("Thumbnails", f"{self.thumbnails:,} from the cache"),
        ]
        if self.already:
            rows.append(("Already in library", f"{self.already:,} (left unchanged)"))
        if self.repaired:
            rows.append(("Repaired", f"{self.repaired:,} of them (missing sidecars or file name)"))
        if self.rescanned:
            rows.append(("Filled in", f"{self.rescanned:,} videos listed without metadata"))
        if options.organize:
            rows.append(("Moves", f"{self.moves.count:,} videos with their sidecars"))
        width = max(len(label) for label, _ in rows) + 2
        lines = [
            "",
            f"TubeArchivist import ({mode})",
            f"  Source:    {importer.source.describe()}",
            f"  Media:     {options.ta_media}",
            f"  Cache:     {cache}",
            f"  Documents: {documents or 'none'}",
            "",
            *(f"{label:<{width}}{value}" for label, value in rows),
            *(f"{'':<{width}}{example}" for example in self.moves.examples),
        ]
        if self.missing.count:
            lines.append("Videos missing files are imported as not downloaded.")
        if self.orphans.count:
            lines.append(
                "Orphan files are imported with their video ID as title"
                + (" and stay where they are." if options.organize else ".")
            )
        if self.already and options.organize:
            lines.append("--organize leaves videos that were already in the library in place.")
        if self.warnings:
            lines += ["", "Warnings:"]
            lines += [f"  - {message}: {tally}" for message, tally in self.warnings.items()]
        if error:
            lines += ["", f"error: {error}"]
            if options.apply:
                lines.append(
                    "What was imported before the error is kept; "
                    "running the import again continues where it stopped."
                )
        elif not options.apply:
            lines += ["", "To apply:", f"  {options.command}"]
            if options.password_note:
                lines.append(f"  ({options.password_note})")
        print("\n".join(lines), file=out)


# Import


@dataclass
class Options:
    apply: bool
    organize: bool
    subscriptions: bool
    ta_media: Path
    ta_cache: Path | None
    cache_detected: bool
    command: str
    password_note: str | None


class Importer:
    def __init__(
        self,
        db: Database,
        source: BackupSource | ElasticSource,
        options: Options,
        out: TextIO,
    ) -> None:
        self.db = db
        self.source = source
        self.options = options
        self.apply = options.apply
        self.out = out
        self.report = Report()
        self.sizes: dict[str, Any] = {}
        self.channels: dict[str, ChannelInfo] = {}
        self.channel_rows: dict[str, int] = {}
        self.channel_names: dict[str, str] = {}
        self.channels_before: set[str] = set()
        self.counted_channels: set[str] = set()
        self.existing: dict[str, Existing] = {}
        self.known_paths: set[str] = set()
        self.subscribed: set[tuple[str, str]] = set()
        self.files: dict[str, list[Path]] = {}
        self.claimed: set[Path] = set()
        self.videos: dict[str, tuple[str, int | None]] = {}
        self.channel_types: dict[str, set[str]] = defaultdict(set)
        self.orphan_ids: set[str] = set()
        self.media: dict[str, Path] = {}
        self.fresh_info: set[str] = set()
        self.dirs: dict[str, Path] | None = None

    def progress(self, message: str) -> None:
        print(message, file=self.out, flush=True)

    async def run(self) -> None:
        await self.load_state()
        self.progress("Scanning media folders…")
        self.scan_media()
        await self.read_config()
        await self.import_channels()
        await self.import_videos()
        await self.import_orphans()
        await self.import_channel_subscriptions()
        await self.import_playlists()
        await self.import_downloads()
        await self.merge_comments()
        self.source_warnings()

    def source_warnings(self) -> None:
        for message, example in self.source.problems:
            self.report.warn(message, example)
        if self.source.unrecognized:
            self.report.warn(
                "documents of unknown type in the backup (skipped)",
                amount=self.source.unrecognized,
            )
        if not self.report.documents["video"]:
            self.report.warn("no video documents were found; is this a TubeArchivist backup?")

    async def load_state(self) -> None:
        # A row from a library rescan or a source listing has no metadata yet: TA's fills it in.
        # TA documents always carry view counts, so imported rows never look like this.
        rows = await self.db.fetch_all(
            """SELECT id, youtube_id, media_path,
                      published_at IS NULL AND description IS NULL AND view_count IS NULL
                          AND deleted_at IS NULL AS placeholder,
                      watched_at IS NOT NULL AS watched, unavailable_at IS NOT NULL AS unavailable
               FROM videos"""
        )
        for row in rows:
            self.existing[row["youtube_id"]] = Existing(
                row["id"],
                row["media_path"],
                bool(row["placeholder"]),
                bool(row["watched"]),
                bool(row["unavailable"]),
            )
            if row["media_path"]:
                self.known_paths.add(row["media_path"])
        for row in await self.db.fetch_all("SELECT id, youtube_id, name FROM channels"):
            self.channel_rows[row["youtube_id"]] = row["id"]
            self.channel_names[row["youtube_id"]] = row["name"]
        self.channels_before = set(self.channel_rows)
        self.subscribed = {
            (row["kind"], row["youtube_id"])
            for row in await self.db.fetch_all("SELECT kind, youtube_id FROM subscriptions")
        }

    def scan_media(self) -> None:
        """Index video files by ID: TA's folder, plus YouHoard's channel folders when separate."""
        found: dict[str, list[Path]] = {}
        self._scan(self.options.ta_media, False, found)
        if self.options.ta_media != config.media_root:
            self._scan(config.media_root, True, found)
        self.files = found

    def _scan(self, root: Path, youhoard_only: bool, found: dict[str, list[Path]]) -> None:
        """Index <folder>/<video file> under root. Paths stay canonical: root is resolved and
        links are reported instead of followed."""
        report = not youhoard_only
        try:
            folders = sorted(os.scandir(root), key=lambda entry: entry.name)
        except OSError as error:
            self.report.warn("folders that could not be read", f"{root}: {error}")
            return
        for folder in folders:
            if folder.name.startswith(".") or folder.name in IGNORED_FOLDERS:
                continue
            if youhoard_only and not folder.name.endswith("]"):
                continue
            if folder.is_symlink():
                if report:
                    self.report.warn(
                        "symbolic links to folders in TubeArchivist's folder (not scanned)",
                        _shown(Path(folder.path)),
                    )
                continue
            if not folder.is_dir():
                if report and _is_video_name(folder.name):
                    self.report.warn(
                        "video files outside any channel folder (not imported)",
                        _shown(Path(folder.path)),
                    )
                continue
            try:
                entries = sorted(os.scandir(folder.path), key=lambda entry: entry.name)
            except OSError as error:
                self.report.warn("folders that could not be read", f"{folder.path}: {error}")
                continue
            for entry in entries:
                if entry.name.startswith(".") or not _is_video_name(entry.name):
                    continue
                path = Path(entry.path)
                if entry.is_symlink():
                    if report:
                        self.report.warn(SYMLINK, _shown(path))
                    continue
                if not entry.is_file():
                    continue
                if youtube_id := media_id(path):
                    found.setdefault(youtube_id, []).append(path)
                elif report:
                    self.report.warn(
                        "video files without a video ID in their name (not imported)", _shown(path)
                    )

    async def documents(self, index: str) -> AsyncIterator[Document]:
        seen: set[str] = set()
        async for document in self.source.documents(index):
            key = document_key(index, document)
            if key is not None:
                if key in seen:
                    self.report.warn(
                        "duplicate documents (the first copy was used)", f"{index} {key}"
                    )
                    continue
                seen.add(key)
            self.report.documents[index] += 1
            yield document

    # Channels

    async def read_config(self) -> None:
        async for document in self.documents("config"):
            subscriptions = document.source.get("subscriptions")
            if isinstance(subscriptions, dict):
                self.sizes = subscriptions

    async def import_channels(self) -> None:
        self.progress("Reading channels…")
        async for document in self.documents("channel"):
            channel = channel_info(document.source, document.id)
            if channel is None:
                self.report.warn(
                    "channel documents without a valid channel ID (skipped)", str(document.id)
                )
                continue
            self.channels[channel.youtube_id] = channel
            self.note_channel(channel)
        if not self.apply:
            return
        channels = list(self.channels.values())
        for start in range(0, len(channels), BATCH):
            async with self.db.transaction() as conn:
                for channel in channels[start : start + BATCH]:
                    await self.save_channel(conn, channel)

    def note_channel(self, channel: ChannelInfo) -> None:
        if channel.youtube_id in self.counted_channels:
            return
        self.counted_channels.add(channel.youtube_id)
        self.report.channels += 1
        if channel.youtube_id not in self.channels_before:
            self.report.channels_new += 1

    async def save_channel(
        self, conn: aiosqlite.Connection, channel: ChannelInfo | None
    ) -> int | None:
        """The channel's row, inserting it, or naming one a rescan created with its ID as name."""
        if channel is None:
            return None
        youtube_id = channel.youtube_id
        row = self.channel_rows.get(youtube_id)
        placeholder = self.channel_names.get(youtube_id) == youtube_id
        if row is None or (placeholder and channel.name not in (None, youtube_id)):
            row = await upsert_channel(
                conn, youtube_id, channel.name, None, channel.description, channel.subscribers
            )
            self.channel_rows[youtube_id] = row
            self.channel_names[youtube_id] = channel.name or youtube_id
        return row

    def channel_for(self, source: dict[str, Any]) -> ChannelInfo | None:
        nested = _dict(source.get("channel"))
        youtube_id = nested.get("channel_id") or source.get("channel_id")
        channel = self.channels.get(youtube_id) if isinstance(youtube_id, str) else None
        if channel is None:
            channel = channel_info(nested, youtube_id)
            if channel is None:
                return None
            self.channels[channel.youtube_id] = channel
            self.note_channel(channel)
        elif channel.name is None and _text(nested.get("channel_name")):
            channel.name = nested["channel_name"]
        return channel

    def channel_dir(self, channel: ChannelInfo) -> Path:
        """layout.channel_dir's answer from a single listing of MEDIA_DIR: that helper lists the
        whole folder for every call, which is slow on network storage with many channels."""
        if self.dirs is None:
            self.dirs = {}
            with suppress(OSError):
                for entry in sorted(os.scandir(config.media_root), key=lambda entry: entry.name):
                    name = entry.name
                    if name.endswith("]") and "[" in name and entry.is_dir():
                        self.dirs.setdefault(name[name.rfind("[") + 1 : -1], Path(entry.path))
        youtube_id = channel.youtube_id
        if youtube_id not in self.dirs:
            folder = f"{layout.clean(channel.name, 120)} [{youtube_id}]"
            self.dirs[youtube_id] = config.media_root / folder
        return self.dirs[youtube_id]

    # Videos

    async def import_videos(self) -> None:
        self.progress("Reading videos…")
        batch: list[VideoPlan] = []
        read = 0
        async for document in self.documents("video"):
            read += 1
            if read % PROGRESS_EVERY == 0:
                self.progress(f"  {read:,} videos…")
            if plan := self.plan_video(document):
                batch.append(plan)
            if len(batch) >= BATCH:
                await self.save_videos(batch)
                batch = []
        if batch:
            await self.save_videos(batch)

    def plan_video(self, document: Document) -> VideoPlan | None:
        source = document.source
        youtube_id = source.get("youtube_id") or document.id
        if not isinstance(youtube_id, str) or not layout.VIDEO_ID.fullmatch(youtube_id):
            self.report.warn("video documents without a valid video ID (skipped)", repr(youtube_id))
            return None
        channel = self.channel_for(source)
        info = video_info(source, youtube_id, channel)
        video_type = VIDEO_TYPES.get(str(source.get("vid_type"))) or classify(info)
        self.videos[youtube_id] = (video_type, info.get("duration"))
        if channel is not None:
            self.channel_types[channel.youtube_id].add(video_type)
        player = _dict(source.get("player"))
        watched, unavailable = player.get("watched") is True, source.get("active") is False
        existing = self.existing.get(youtube_id)
        if existing is not None and not existing.placeholder:
            return self.plan_repair(existing, source, info, channel, watched, unavailable)
        if existing is not None:
            self.report.rescanned += 1

        plan = VideoPlan(youtube_id, info, video_type, channel)
        if unavailable:
            plan.unavailable_at = now()
            self.report.unavailable += 1
        if watched:
            plan.watched_at = _moment(player.get("watched_date")) or now()
            self.report.watched += 1
        media = self.find_media(source, youtube_id, channel, existing)
        if media is None:
            self.report.missing.add(f'{youtube_id} "{_short(info["title"])}"')
            return plan
        stat = media.stat()
        plan.media, plan.size = media, stat.st_size
        plan.archived_at = _moment(source.get("date_downloaded")) or _moment(stat.st_mtime)
        self.report.with_files += 1
        self.report.size += stat.st_size
        self.check_subtitles(source, media)
        self.plan_files(plan, source)
        return plan

    def plan_repair(
        self,
        existing: Existing,
        source: dict[str, Any],
        info: dict[str, Any],
        channel: ChannelInfo | None,
        watched: bool,
        unavailable: bool,
    ) -> VideoPlan | None:
        """A video already in the library keeps its row. Only sidecars it lacks are written and,
        with --organize, a file name YouHoard cannot match to the video is fixed."""
        youtube_id = info["id"]
        self.report.already += 1
        if watched and not existing.watched:
            self.report.warn(
                "videos already in the library that TubeArchivist marks watched (not applied)",
                youtube_id,
            )
        if unavailable and not existing.unavailable:
            self.report.warn(
                "videos already in the library that TubeArchivist marks unavailable (not applied)",
                youtube_id,
            )
        if not existing.media_path:
            return None
        try:
            media = layout.resolve(existing.media_path)
        except layout.PathError:
            return None
        if not media.is_file():
            return None
        self.claimed.add(media)
        plan = VideoPlan(youtube_id, info, "video", channel, media=media, repair_of=existing.id)
        self.plan_files(plan, source)
        if plan.move is None and not plan.write_info and plan.thumbnail is None:
            return None
        self.report.repaired += 1
        return plan

    def plan_files(self, plan: VideoPlan, source: dict[str, Any]) -> None:
        """Where the file goes and which sidecars are written: all of them for a new import,
        only missing ones for a video already in the library."""
        assert plan.media is not None
        media, repair = plan.media, plan.repair_of is not None
        unusable = layout.video_id_from_media(media) != plan.youtube_id
        if self.options.organize and (unusable or not repair):
            plan.move = self.organize_target(media, plan, source)
        if plan.move is None and unusable:
            self.report.warn(UNRECOGNIZED_NAME, _shown(media))
        info_path = media.with_name(media.stem + ".info.json")
        if repair:
            plan.write_info = not info_path.exists()
        elif info_owner(info_path) == "foreign":
            self.report.warn(
                "existing .info.json files kept (TubeArchivist's metadata is only in the database)",
                _shown(info_path),
            )
        else:
            plan.write_info = True
        if plan.write_info:
            self.fresh_info.add(plan.youtube_id)
        if layout.thumbnail_for(media) is None:
            plan.thumbnail = cached_thumbnail(self.options.ta_cache, plan.youtube_id)
            if plan.thumbnail is not None:
                self.report.thumbnails += 1
        directory, basename = plan.move or (media.parent, media.stem)
        self.media[plan.youtube_id] = directory / f"{basename}{media.suffix}"

    def find_media(
        self,
        source: dict[str, Any],
        youtube_id: str,
        channel: ChannelInfo | None,
        existing: Existing | None,
    ) -> Path | None:
        """The video's file: the database's path, TA's media_url, <channel id>/<id>.<ext>, or
        any file named for the video that the scan found."""
        candidates: list[Path] = []
        if existing is not None and existing.media_path:
            with suppress(layout.PathError):
                candidates.append(layout.resolve(existing.media_path))
        media_url = _text(source.get("media_url"))
        if media_url:
            candidates.append(self.options.ta_media / media_url.strip())
        if channel is not None:
            folder = self.options.ta_media / channel.youtube_id
            candidates += [folder / f"{youtube_id}{suffix}" for suffix in layout.VIDEO_EXTENSIONS]
        candidates += self.files.get(youtube_id, [])
        for candidate in candidates:
            if candidate.is_symlink():  # reported by the scan
                continue
            path = candidate.resolve()
            if path in self.claimed or not path.is_file():
                continue
            if not path.is_relative_to(config.media_root):
                self.report.warn("media files outside MEDIA_DIR (not imported)", str(path))
                continue
            if not _is_video_name(path.name):
                self.report.warn("media_url entries that are not video files", _shown(path))
                continue
            found = media_id(path)
            if found is not None and found != youtube_id:
                self.report.warn(
                    "media_url entries naming another video's file (ignored)",
                    f"{youtube_id}: {_shown(path)}",
                )
                continue
            self.claimed.add(path)
            return path
        return None

    def check_subtitles(self, source: dict[str, Any], media: Path) -> None:
        for subtitle in source.get("subtitles") or []:
            if not isinstance(subtitle, dict) or not _text(subtitle.get("media_url")):
                continue
            listed = self.options.ta_media / subtitle["media_url"]
            beside = media.with_name(f"{media.stem}.{subtitle.get('lang')}.vtt")
            if not listed.is_file() and not beside.is_file():
                self.report.warn(
                    "subtitle files TubeArchivist lists that are missing", subtitle["media_url"]
                )

    def organize_target(
        self, media: Path, plan: VideoPlan, source: dict[str, Any]
    ) -> tuple[Path, str] | None:
        """The (folder, basename) to rename a video to, or None to leave it where it is. A name
        that any of its files would collide with is refused, so nothing is ever replaced."""
        if plan.channel is None:
            self.report.warn("videos without a channel, left in place", _shown(media))
            return None
        directory = self.channel_dir(plan.channel)
        if media.parent == directory and layout.BRACKETED_ID.search(media.stem):
            return None
        info = plan.info
        basename = layout.video_basename(plan.youtube_id, info.get("title"), published_at(info))
        if directory / f"{basename}{media.suffix}" == media:
            return None
        languages = [
            subtitle["lang"]
            for subtitle in source.get("subtitles") or []
            if isinstance(subtitle, dict) and _text(subtitle.get("lang"))
        ]
        suffixes = [media.suffix, ".info.json", *layout.THUMBNAIL_EXTENSIONS]
        suffixes += [f".{language}.vtt" for language in languages]
        for suffix in suffixes:
            if (directory / f"{basename}{suffix}").exists():
                self.report.warn(TAKEN, _shown(directory / f"{basename}{suffix}"))
                return None
        return directory, basename

    async def save_videos(self, batch: list[VideoPlan]) -> None:
        for plan in batch:
            if plan.media is None:
                continue
            if not self.apply:
                if plan.move:
                    self.note_move(plan.media, plan.move)
            elif plan.move:
                self.place(plan)
            else:
                self.write_sidecars(plan)
        if not self.apply:
            return
        async with self.db.transaction() as conn:
            for plan in batch:
                if plan.repair_of is not None:
                    if plan.moved:
                        await conn.execute(
                            "UPDATE videos SET media_path = ?, updated_at = ? WHERE id = ?",
                            (layout.relative(plan.media), now(), plan.repair_of),
                        )
                    continue
                await self.save_channel(conn, plan.channel)
                # The channel row came from TA's channel document or was already there: the
                # video does not overwrite its name or subscriber count.
                row_info = {key: value for key, value in plan.info.items() if key not in VIDEO_ONLY}
                video_id, _ = await save_video_info(conn, row_info, plan.video_type)
                await conn.execute(
                    """UPDATE videos SET unavailable_at = coalesce(unavailable_at, ?),
                           watched_at = coalesce(watched_at, ?)
                       WHERE id = ?""",
                    (plan.unavailable_at, plan.watched_at, video_id),
                )
                if plan.media is not None:
                    await record_archived(
                        conn,
                        video_id,
                        layout.relative(plan.media),
                        plan.size,
                        plan.info.get("width"),
                        plan.info.get("height"),
                        plan.archived_at,
                    )

    def note_move(self, media: Path, move: tuple[Path, str]) -> None:
        directory, basename = move
        target = directory / f"{basename}{media.suffix}"
        self.report.moves.add(f"{layout.relative(media)} -> {layout.relative(target)}")

    def place(self, plan: VideoPlan) -> None:
        """Rename the media and its sidecars into the library layout, then write sidecars. If
        the rename fails part way, the sidecars already renamed are moved back."""
        assert plan.media is not None and plan.move is not None
        original = plan.media
        directory, basename = plan.move
        renames = [
            (path, directory / f"{basename}.{path.name[len(original.stem) + 1 :]}")
            for path in layout.sidecars(original)
        ]
        taken = next((target for _, target in renames if target.exists()), None)
        if taken is not None:
            self.report.warn(TAKEN, _shown(taken))
        else:
            try:
                plan.media = layout.move_media(original, directory, basename)
            except OSError as error:
                for path, target in renames:
                    if target.exists() and not path.exists():
                        with suppress(OSError):
                            os.replace(target, path)
                with suppress(OSError):
                    directory.rmdir()  # only if this created it and it is still empty
                self.report.warn(
                    "files that could not be moved (left in place)", f"{_shown(original)}: {error}"
                )
            else:
                plan.moved = True
                self.note_move(original, plan.move)
        if not plan.moved and layout.video_id_from_media(original) != plan.youtube_id:
            self.report.warn(UNRECOGNIZED_NAME, _shown(original))
        self.media[plan.youtube_id] = plan.media
        self.write_sidecars(plan)

    def write_sidecars(self, plan: VideoPlan) -> None:
        assert plan.media is not None
        media = plan.media
        if plan.write_info:
            try:
                write_info_json(media.with_name(media.stem + ".info.json"), plan.info)
            except (OSError, ValueError) as error:  # ValueError: text the locale cannot encode
                self.fresh_info.discard(plan.youtube_id)
                self.report.warn(
                    ".info.json files that could not be written (a later run retries)",
                    f"{_shown(media)}: {error}",
                )
        if plan.thumbnail is not None and layout.thumbnail_for(media) is None:
            try:
                copy_file(plan.thumbnail, media.with_name(media.stem + ".jpg"))
            except OSError as error:
                self.report.thumbnails -= 1
                self.report.warn("thumbnails that could not be copied", f"{_shown(media)}: {error}")

    # Orphans

    async def import_orphans(self) -> None:
        plans: list[OrphanPlan] = []
        for youtube_id, paths in self.files.items():
            for path in paths:
                if path in self.claimed or not path.is_relative_to(self.options.ta_media):
                    continue
                relative = layout.relative(path)
                if relative in self.known_paths:
                    continue
                existing = self.existing.get(youtube_id)
                # A row without metadata or file (e.g. from a listing) may still take the file.
                if existing is not None and (existing.media_path or not existing.placeholder):
                    if existing.media_path:
                        self.report.warn(EXTRA_COPY, relative)
                    else:
                        self.report.warn(
                            "files for videos the library has without a file "
                            "(left alone; a library rescan links them)",
                            relative,
                        )
                    continue
                if youtube_id in self.videos or youtube_id in self.orphan_ids:
                    self.report.warn(EXTRA_COPY, relative)
                    continue
                if not (layout.VIDEO_ID.fullmatch(path.stem) or LEGACY_NAME.match(path.stem)):
                    self.report.warn(
                        "video files that are neither TubeArchivist's nor in the database "
                        "(left alone; a library rescan adds them)",
                        relative,
                    )
                    continue
                if layout.video_id_from_media(path) != youtube_id:
                    self.report.warn(LEGACY_ORPHAN, relative)
                channel = self.orphan_channel(path.parent.name)
                thumbnail = None
                if layout.thumbnail_for(path) is None:
                    thumbnail = cached_thumbnail(self.options.ta_cache, youtube_id)
                    if thumbnail is not None:
                        self.report.thumbnails += 1
                plans.append(OrphanPlan(youtube_id, path, channel, thumbnail))
                self.orphan_ids.add(youtube_id)
                self.report.orphans.add(relative)
        if not self.apply:
            return
        for start in range(0, len(plans), BATCH):
            batch = plans[start : start + BATCH]
            for plan in batch:
                if plan.thumbnail is not None:
                    try:
                        copy_file(plan.thumbnail, plan.path.with_name(plan.path.stem + ".jpg"))
                    except OSError as error:
                        self.report.thumbnails -= 1
                        self.report.warn(
                            "thumbnails that could not be copied", f"{_shown(plan.path)}: {error}"
                        )
            async with self.db.transaction() as conn:
                for plan in batch:
                    channel_row = await self.save_channel(conn, plan.channel)
                    video_id = await ensure_video(
                        conn, plan.youtube_id, plan.youtube_id, "video", channel_row
                    )
                    stat = plan.path.stat()
                    await record_archived(
                        conn,
                        video_id,
                        layout.relative(plan.path),
                        stat.st_size,
                        archived_at=_moment(stat.st_mtime),
                    )

    def orphan_channel(self, folder: str) -> ChannelInfo | None:
        channel = folder_channel(folder)
        if channel is None:
            return None
        if channel.youtube_id not in self.channels:
            self.channels[channel.youtube_id] = channel
            self.note_channel(channel)
        return self.channels[channel.youtube_id]

    # Subscriptions

    def tab_disabled(self, channel: ChannelInfo, video_type: str) -> bool:
        overwrite_key, setting_key = SIZE_SETTINGS[video_type]
        size = channel.overwrites.get(overwrite_key)
        if size is None:
            size = self.sizes.get(setting_key)
        return size is not None and size == 0

    def content_types(self, channel: ChannelInfo) -> tuple[list[str], str]:
        """The tabs to follow: types among the channel's videos that TA's limits did not turn
        off. If every one is off, keep them and only track the inventory."""
        present = self.channel_types.get(channel.youtube_id) or {"video"}
        types = [video_type for video_type in TYPE_ORDER if video_type in present]
        enabled = [video_type for video_type in types if not self.tab_disabled(channel, video_type)]
        if enabled:
            return enabled, "new"
        self.report.warn(
            "subscribed channels whose TubeArchivist download limits are all 0 "
            "(imported with download policy 'none')",
            channel.name or channel.youtube_id,
        )
        return types, "none"

    async def add_subscription(
        self,
        conn: aiosqlite.Connection,
        kind: str,
        youtube_id: str,
        title: str,
        channel_row: int | None,
        owner_name: str | None,
        content_types: list[str],
        policy: str,
        inventoried: list[str],
    ) -> int | None:
        row = await fetch_one(
            conn,
            """INSERT INTO subscriptions (kind, youtube_id, title, channel_id, owner_name,
                   content_types, download_policy, inventoried_types, next_check_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (kind, youtube_id) DO NOTHING
               RETURNING id""",
            (
                kind,
                youtube_id,
                title,
                channel_row,
                owner_name,
                dumps(content_types),
                policy,
                dumps(inventoried),
                later(seconds=random.uniform(0, 24 * 3600)),
            ),
        )
        return row["id"] if row else None

    async def import_channel_subscriptions(self) -> None:
        planned: list[tuple[ChannelInfo, list[str], str]] = []
        for channel in self.channels.values():
            if not channel.subscribed:
                continue
            if not self.options.subscriptions:
                self.report.subscriptions["channel skipped"] += 1
                continue
            if ("channel", channel.youtube_id) in self.subscribed:
                self.report.subscriptions["existing"] += 1
                continue
            if not channel.active:
                self.report.warn(
                    "subscribed channels TubeArchivist marks inactive (imported; checks may fail)",
                    channel.name or channel.youtube_id,
                )
            content_types, policy = self.content_types(channel)
            planned.append((channel, content_types, policy))
            self.report.subscriptions["channel"] += 1
        if not self.apply or not planned:
            return
        async with self.db.transaction() as conn:
            for channel, content_types, policy in planned:
                channel_row = await self.save_channel(conn, channel)
                await self.add_subscription(
                    conn,
                    "channel",
                    channel.youtube_id,
                    channel.name or channel.youtube_id,
                    channel_row,
                    None,
                    content_types,
                    policy,
                    [],
                )

    async def import_playlists(self) -> None:
        self.progress("Reading playlists…")
        async for document in self.documents("playlist"):
            source = document.source
            playlist_id = source.get("playlist_id") or document.id
            name = _text(source.get("playlist_name")) or str(playlist_id)
            if source.get("playlist_type") == "custom":
                self.report.custom.add(f'"{_short(name, 40)}"')
                continue
            if source.get("playlist_subscribed") is not True:
                self.report.unsubscribed += 1
                continue
            if not isinstance(playlist_id, str) or not layout.CHANNEL_ID.fullmatch(playlist_id):
                self.report.warn(
                    "playlist documents without a valid ID (skipped)", repr(playlist_id)
                )
                continue
            if not self.options.subscriptions:
                self.report.subscriptions["playlist skipped"] += 1
                continue
            if ("playlist", playlist_id) in self.subscribed:
                self.report.subscriptions["existing"] += 1
                continue
            if source.get("playlist_active") is False:
                self.report.warn(
                    "subscribed playlists TubeArchivist marks inactive (imported; checks may fail)",
                    name,
                )
            self.report.subscriptions["playlist"] += 1
            owner = self.playlist_owner(source)
            if self.apply:
                await self.save_playlist(source, playlist_id, name, owner)

    def playlist_owner(self, source: dict[str, Any]) -> ChannelInfo | None:
        owner_id = source.get("playlist_channel_id")
        if not isinstance(owner_id, str) or not layout.CHANNEL_ID.fullmatch(owner_id):
            return None
        if owner_id not in self.channels:
            self.channels[owner_id] = ChannelInfo(owner_id, _text(source.get("playlist_channel")))
            self.note_channel(self.channels[owner_id])
        return self.channels[owner_id]

    def playlist_entries(self, source: dict[str, Any]) -> list[tuple[Any, ...]]:
        """(video ID, type, title, duration, position) in YouTube's order.

        TA stores a playlist sorted "bottom" reversed, numbering entries in that order, and does
        not renumber them when it removes one.
        """
        entries = [
            entry for entry in source.get("playlist_entries") or [] if isinstance(entry, dict)
        ]
        indexes = [_number(entry.get("idx")) for entry in entries]
        indexes = [number if index is None else index for number, index in enumerate(indexes)]
        last = max(indexes, default=0)
        reverse = source.get("playlist_sort_order") == "bottom"
        rows = []
        for entry, index in zip(entries, indexes, strict=True):
            youtube_id = entry.get("youtube_id")
            if not isinstance(youtube_id, str) or not layout.VIDEO_ID.fullmatch(youtube_id):
                continue
            position = max(last - index, 0) if reverse else index
            video_type, duration = self.videos.get(youtube_id, ("video", None))
            rows.append((youtube_id, video_type, _text(entry.get("title")), duration, position))
        return rows

    async def save_playlist(
        self, source: dict[str, Any], playlist_id: str, name: str, owner: ChannelInfo | None
    ) -> None:
        seen = _moment(source.get("playlist_last_refresh")) or now()
        entries = self.playlist_entries(source)
        async with self.db.transaction() as conn:
            channel_row = await self.save_channel(conn, owner)
            subscription_id = await self.add_subscription(
                conn,
                "playlist",
                playlist_id,
                name,
                channel_row,
                _text(source.get("playlist_channel")) or (owner.name if owner else None),
                ["video"],
                "new",
                ["playlist"],
            )
            if subscription_id is None:
                return
            await conn.executemany(
                """INSERT OR IGNORE INTO source_entries (subscription_id, youtube_id, video_type,
                       title, duration, position, baseline, first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                [(subscription_id, *entry, seen, seen) for entry in entries],
            )

    # Download queue

    async def import_downloads(self) -> None:
        self.progress("Reading the download queue…")
        batch: list[Tombstone] = []
        planned: set[str] = set()
        async for document in self.documents("download"):
            source = document.source
            status = source.get("status")
            youtube_id = source.get("youtube_id") or document.id
            if status == "pending":
                self.report.pending += 1
                continue
            if status != "ignore":
                self.report.warn(
                    "download queue entries with an unknown status (not imported)", repr(status)
                )
                continue
            if not isinstance(youtube_id, str) or not layout.VIDEO_ID.fullmatch(youtube_id):
                self.report.warn("ignore list entries without a valid video ID", repr(youtube_id))
                continue
            if (
                youtube_id in self.existing
                or youtube_id in self.videos
                or youtube_id in self.orphan_ids
                or youtube_id in planned
            ):
                self.report.ignored_known += 1
                continue
            planned.add(youtube_id)
            self.report.ignored += 1
            channel_id = source.get("channel_id")
            upload_date, _ = _published(source.get("published"))
            batch.append(
                Tombstone(
                    youtube_id,
                    _text(source.get("title")),
                    VIDEO_TYPES.get(str(source.get("vid_type")), "video"),
                    channel_id if isinstance(channel_id, str) else None,
                    _duration(source.get("duration")),
                    published_at({"upload_date": upload_date}),
                )
            )
            if len(batch) >= BATCH:
                await self.save_tombstones(batch)
                batch = []
        if batch:
            await self.save_tombstones(batch)

    async def save_tombstones(self, batch: list[Tombstone]) -> None:
        if not self.apply:
            return
        stamp = now()
        async with self.db.transaction() as conn:
            for item in batch:
                video_id = await ensure_video(
                    conn,
                    item.youtube_id,
                    item.title,
                    item.video_type,
                    self.channel_rows.get(item.channel_id or ""),
                    item.duration,
                )
                await conn.execute(
                    """UPDATE videos SET deleted_at = coalesce(deleted_at, ?),
                           published_at = coalesce(published_at, ?), updated_at = ?
                       WHERE id = ?""",
                    (stamp, item.published_at, stamp, video_id),
                )

    # Comments

    async def merge_comments(self) -> None:
        """Add each video's comments to its .info.json, one document at a time."""
        self.progress("Reading comments…")
        read = 0
        async for document in self.documents("comment"):
            read += 1
            if read % PROGRESS_EVERY == 0:
                self.progress(f"  {read:,} comment threads…")
            youtube_id = document.source.get("youtube_id") or document.id
            comments = [
                comment
                for comment in document.source.get("comment_comments") or []
                if isinstance(comment, dict)
            ]
            if not comments or not isinstance(youtube_id, str):
                continue
            media = self.media.get(youtube_id)
            if youtube_id in self.fresh_info and not self.apply:
                status = "merged"
            elif media is not None:
                info_path = media.with_name(media.stem + ".info.json")
                status = self.merge_into(info_path, comments, document.source)
            else:
                status = "nowhere"
            if status == "merged":
                self.report.comments += len(comments)
                self.report.comment_videos += 1
            elif status == "nowhere":
                self.report.warn(
                    "comments on videos without an .info.json from this import "
                    "(they stay only in TubeArchivist's data)",
                    youtube_id,
                    len(comments),
                )

    def merge_into(
        self, path: Path, comments: list[dict[str, Any]], document: dict[str, Any]
    ) -> str:
        """Add comments to an .info.json this import wrote.

        Returns "merged", "present" (it has comments already), "nowhere" (no such .info.json)
        or "failed".
        """
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "nowhere"
        if not isinstance(info, dict) or "_tubearchivist" not in info:
            return "nowhere"
        if info.get("comments"):
            return "present"
        if self.apply:
            info["comments"] = [ytdlp_comment(comment) for comment in comments]
            info["comment_count"] = info.get("comment_count") or len(comments)
            info["_tubearchivist_comments"] = {
                key: value for key, value in document.items() if key != "comment_comments"
            }
            try:
                write_info_json(path, info)
            except (OSError, ValueError) as error:
                self.report.warn(
                    "comments that could not be written (a later run retries)",
                    f"{_shown(path)}: {error}",
                )
                return "failed"
        return "merged"


# Command line


def add_arguments(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--backup",
        type=Path,
        metavar="PATH",
        help="a TubeArchivist backup zip (in its cache folder under backup/)",
    )
    source.add_argument(
        "--es-url", metavar="URL", help="TubeArchivist's Elasticsearch, e.g. http://localhost:9200"
    )
    parser.add_argument(
        "--es-user", default="elastic", help="Elasticsearch user (default: elastic)"
    )
    parser.add_argument(
        "--es-password", help="Elasticsearch password (default: the TA_ES_PASSWORD variable)"
    )
    parser.add_argument(
        "--ta-media",
        type=Path,
        metavar="DIR",
        help="TubeArchivist's media folder, inside MEDIA_DIR (default: MEDIA_DIR)",
    )
    parser.add_argument(
        "--ta-cache",
        type=Path,
        metavar="DIR",
        help="TubeArchivist's cache folder, for thumbnails (default: the backup's cache folder)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="write the import (without it: a dry run)"
    )
    parser.add_argument(
        "--organize", action="store_true", help="rename files into YouHoard's library layout"
    )
    parser.add_argument(
        "--no-subscriptions", action="store_true", help="do not import subscriptions"
    )


def apply_command(args: argparse.Namespace) -> str:
    parts = ["python", "-m", "app", "import-tubearchivist"]
    if args.backup is not None:
        parts += ["--backup", str(args.backup)]
    else:
        parts += ["--es-url", args.es_url]
        if args.es_user != "elastic":
            parts += ["--es-user", args.es_user]
    for flag, value in (("--ta-media", args.ta_media), ("--ta-cache", args.ta_cache)):
        if value is not None:
            parts += [flag, str(value)]
    for flag, enabled in (
        ("--organize", args.organize),
        ("--no-subscriptions", args.no_subscriptions),
    ):
        if enabled:
            parts.append(flag)
    return shlex.join([*parts, "--apply"])


def parse_options(args: argparse.Namespace) -> Options:
    media_root = config.media_root
    ta_media = Path(args.ta_media or config.MEDIA_DIR).expanduser().resolve()
    if not ta_media.is_relative_to(media_root):
        raise ImportProblem(
            f"TubeArchivist's media folder {ta_media} is outside MEDIA_DIR ({media_root}). "
            "YouHoard stores every media path relative to MEDIA_DIR, and --organize moves files "
            "with same-filesystem renames instead of copying terabytes, so TubeArchivist's "
            "folder must be MEDIA_DIR itself or a folder inside it. Set MEDIA_DIR to it (or to "
            "a parent folder on the same filesystem) and run the import again."
        )
    if not ta_media.is_dir():
        raise ImportProblem(f"TubeArchivist's media folder {ta_media} does not exist.")
    if args.organize and ta_media.stat().st_dev != media_root.stat().st_dev:
        raise ImportProblem(
            f"--organize renames files, but {ta_media} is on a different filesystem than "
            f"MEDIA_DIR ({media_root}). Import without --organize, or make MEDIA_DIR a folder "
            "on that filesystem."
        )
    cache, detected = None, False
    if args.ta_cache is not None:
        cache = Path(args.ta_cache).expanduser().resolve()
        if not cache.is_dir():
            raise ImportProblem(f"TubeArchivist's cache folder {cache} does not exist.")
    elif args.backup is not None:
        backup = Path(args.backup).expanduser().resolve()
        if backup.parent.name == "backup" and (backup.parent.parent / "videos").is_dir():
            cache, detected = backup.parent.parent, True
    note = None
    if args.es_url and args.es_password:
        note = "add --es-password again, or set TA_ES_PASSWORD"
    return Options(
        apply=args.apply,
        organize=args.organize,
        subscriptions=not args.no_subscriptions,
        ta_media=ta_media,
        ta_cache=cache,
        cache_detected=detected,
        command=apply_command(args),
        password_note=note,
    )


def open_source(args: argparse.Namespace) -> BackupSource | ElasticSource:
    if args.backup is not None:
        path = Path(args.backup).expanduser().resolve()
        if not path.exists():
            raise ImportProblem(f"Backup {path} does not exist.")
        try:
            return BackupSource(path)
        except (OSError, zipfile.BadZipFile) as error:
            raise ImportProblem(f"Could not open the backup {path}: {error}") from error
    password = args.es_password or os.environ.get("TA_ES_PASSWORD")
    return ElasticSource(args.es_url, args.es_user, password)


async def run(args: argparse.Namespace, db: Database, out: TextIO) -> int:
    try:
        options = parse_options(args)
        source = open_source(args)
    except ImportProblem as problem:
        print(f"error: {problem}", file=out)
        return 2
    importer = Importer(db, source, options, out)
    try:
        await importer.run()
    except ImportProblem as problem:
        importer.report.write(out, importer, str(problem))
        return 1
    finally:
        await source.close()
    importer.report.write(out, importer)
    return 0
