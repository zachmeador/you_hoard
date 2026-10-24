"""TubeArchivist import against a synthetic TubeArchivist backup, media folder and cache.

Documents follow TubeArchivist's index mapping (backend/appsettings/index_mapping.json) and the
backup zip follows its backup writer (backend/appsettings/src/backup.py): es_<index>-<date>-<page>
.json files of Elasticsearch bulk lines.
"""

import argparse
import asyncio
import base64
import functools
import io
import json
import os
import struct
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from app import layout, tubearchivist
from app.config import config
from app.db import Database, iso
from app.library import ensure_video, record_archived, save_video_info, upsert_channel

CHANNEL_A = "UC" + "a" * 22
CHANNEL_B = "UC" + "b" * 22
CHANNEL_C = "UC" + "c" * 22  # known only from the channel nested in its video
CHANNEL_GONE = "UC" + "z" * 22
A1, A2, B1, B2, C1 = "aaaaaaaaaa1", "aaaaaaaaaa2", "bbbbbbbbbb1", "bbbbbbbbbb2", "cccccccccc1"
ORPHAN = "orphan00001"
PUBLISHED = 1699000000
DOWNLOADED = 1700000000
WATCHED = 1700100000


def ta_moment(epoch: int) -> str:
    return iso(datetime.fromtimestamp(epoch, UTC))


def ta_date(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).date().isoformat()


def ta_channel_doc(channel_id: str, name: str, **extra: Any) -> dict[str, Any]:
    return {
        "channel_active": True,
        "channel_description": f"About {name}",
        "channel_id": channel_id,
        "channel_last_refresh": DOWNLOADED,
        "channel_name": name,
        "channel_subs": 1234,
        "channel_subscribed": False,
        "channel_tags": [],
        "channel_tabs": ["videos", "shorts", "streams"],
        "channel_thumb_url": "https://yt3.example/thumb.jpg",
        **extra,
    }


def ta_video_doc(youtube_id: str, channel: dict[str, Any], title: str, **extra: Any) -> dict:
    return {
        "active": True,
        "category": ["Education"],
        "channel": channel,
        "date_downloaded": DOWNLOADED,
        "description": f"Description of {title}",
        "media_size": 4,
        "media_url": f"{channel['channel_id']}/{youtube_id}.mp4",
        "player": {"duration": 125, "duration_str": "2m 05s", "watched": False},
        "published": PUBLISHED,
        "stats": {"view_count": 1000, "like_count": 50, "dislike_count": 0, "average_rating": 0},
        "streams": [
            {"type": "video", "index": 0, "codec": "h264", "width": 1920, "height": 1080},
            {"type": "audio", "index": 1, "codec": "aac", "bitrate": 128000},
        ],
        "subtitles": [],
        "tags": ["tag one", "tag two"],
        "title": title,
        "vid_last_refresh": DOWNLOADED,
        "vid_thumb_url": f"https://i.ytimg.com/vi/{youtube_id}/maxresdefault.jpg",
        "vid_type": "videos",
        "youtube_id": youtube_id,
        **extra,
    }


def ta_comment(comment_id: str, text: str, parent: str = "root", **extra: Any) -> dict:
    return {
        "comment_author": "Viewer",
        "comment_author_id": "UC" + "v" * 22,
        "comment_author_is_uploader": False,
        "comment_author_thumbnail": "https://yt3.example/viewer.jpg",
        "comment_id": comment_id,
        "comment_is_favorited": False,
        "comment_likecount": 3,
        "comment_parent": parent,
        "comment_text": text,
        "comment_time_text": "2023-11-14 22:21",
        "comment_timestamp": DOWNLOADED + 500,
        **extra,
    }


def ta_bulk(index: str, documents: list[tuple[str, dict[str, Any]]]) -> str:
    """A backup file as TubeArchivist's BackupCallback writes it."""
    lines = []
    for document_id, source in documents:
        lines.append(json.dumps({"index": {"_index": f"ta_{index}", "_id": document_id}}))
        lines.append(json.dumps(source))
    lines.append("\n")
    return "\n".join(lines)


def ta_documents() -> dict[str, list[tuple[str, dict[str, Any]]]]:
    alpha = ta_channel_doc(CHANNEL_A, "Alpha Channel", channel_subscribed=True)
    beta = ta_channel_doc(CHANNEL_B, "Beta Channel", channel_subscribed=True)
    charlie = ta_channel_doc(CHANNEL_C, "Charlie Channel")
    videos = [
        ta_video_doc(
            A1,
            alpha,
            "Alpha video one",
            player={
                "duration": 125,
                "duration_str": "2m 05s",
                "watched": True,
                "watched_date": WATCHED,
            },
            subtitles=[
                {
                    "ext": "vtt",
                    "lang": "en",
                    "media_url": f"{CHANNEL_A}/{A1}.en.vtt",
                    "name": "English",
                    "source": "user",
                    "url": None,
                }
            ],
            comment_count=2,
            playlist=["PLsubscribed"],
        ),
        ta_video_doc(
            A2,
            alpha,
            "Alpha short",
            vid_type="shorts",
            active=False,
            streams=[{"type": "video", "index": 0, "codec": "vp9", "width": 1080, "height": 1920}],
        ),
        ta_video_doc(B1, beta, "Beta stream", vid_type="streams", published="2023-05-06"),
        ta_video_doc(B2, beta, "Beta lost video"),
        ta_video_doc(C1, charlie, "Charlie video"),
    ]
    playlists = [
        {
            "playlist_active": True,
            "playlist_channel": "Alpha Channel",
            "playlist_channel_id": CHANNEL_A,
            "playlist_description": "The good ones",
            "playlist_entries": [
                {"youtube_id": A1, "title": "Alpha video one", "uploader": "Alpha", "idx": 0},
                {"youtube_id": A2, "title": "Alpha short", "uploader": "Alpha", "idx": 1},
                {"youtube_id": "notarchived", "title": "Not here", "uploader": "Alpha", "idx": 2},
            ],
            "playlist_id": "PLsubscribed",
            "playlist_last_refresh": DOWNLOADED,
            "playlist_name": "Alpha picks",
            "playlist_sort_order": "top",
            "playlist_subscribed": True,
            "playlist_thumbnail": "https://i.ytimg.com/pl.jpg",
            "playlist_type": "regular",
        },
        {
            "playlist_active": True,
            "playlist_channel": "Beta Channel",
            "playlist_channel_id": CHANNEL_B,
            # TubeArchivist does not renumber entries after removing one (idx 1 here).
            "playlist_entries": [
                {"youtube_id": B1, "title": "Beta stream", "idx": 0, "downloaded": True},
                {"youtube_id": B2, "title": "Beta lost video", "idx": 2, "downloaded": False},
            ],
            "playlist_id": "PLbottom",
            "playlist_last_refresh": DOWNLOADED,
            "playlist_name": "Beta newest last",
            "playlist_sort_order": "bottom",
            "playlist_subscribed": True,
            "playlist_type": "regular",
        },
        {
            "playlist_active": False,
            "playlist_channel": None,
            "playlist_channel_id": None,
            "playlist_entries": [{"youtube_id": C1, "title": "Charlie video", "idx": 0}],
            "playlist_id": "PLcustomlist",
            "playlist_name": "Favourites",
            "playlist_subscribed": False,
            "playlist_type": "custom",
        },
        {
            "playlist_active": True,
            "playlist_channel": "Charlie Channel",
            "playlist_channel_id": CHANNEL_C,
            "playlist_entries": [],
            "playlist_id": "PLunsubscribed",
            "playlist_name": "Charlie extras",
            "playlist_subscribed": False,
            "playlist_type": "regular",
        },
    ]
    downloads = [
        {
            "channel_id": CHANNEL_B,
            "channel_indexed": True,
            "channel_name": "Beta Channel",
            "duration": "1h 02m 03s",
            "published": 1690000000,
            "status": "ignore",
            "timestamp": DOWNLOADED,
            "title": "Ignored one",
            "vid_thumb_url": "https://i.ytimg.com/vi/ignored0001/hq.jpg",
            "vid_type": "videos",
            "youtube_id": "ignored0001",
        },
        {
            "channel_id": CHANNEL_GONE,
            "channel_indexed": False,
            "channel_name": "Gone Channel",
            "duration": "NA",
            "published": None,
            "status": "ignore",
            "timestamp": DOWNLOADED,
            "title": "Ignored two",
            "vid_type": "shorts",
            "youtube_id": "ignored0002",
        },
        {
            "channel_id": CHANNEL_A,
            "channel_name": "Alpha Channel",
            "duration": "3m 00s",
            "status": "pending",
            "timestamp": DOWNLOADED,
            "title": "Waiting",
            "vid_type": "videos",
            "youtube_id": "pending0001",
        },
        {
            "channel_id": CHANNEL_B,
            "channel_name": "Beta Channel",
            "status": "ignore",
            "timestamp": DOWNLOADED,
            "title": "Beta stream",
            "vid_type": "streams",
            "youtube_id": B1,
        },
    ]
    comments = [
        {
            "comment_channel_id": CHANNEL_A,
            "comment_comments": [
                ta_comment("Ugx1", "First!"),
                ta_comment("Ugx1.r1", "Thanks", parent="Ugx1", comment_author_is_uploader=True),
            ],
            "comment_last_refresh": DOWNLOADED,
            "youtube_id": A1,
        },
        {
            "comment_channel_id": CHANNEL_B,
            "comment_comments": [ta_comment("Ugx2", "Where did it go?")],
            "comment_last_refresh": DOWNLOADED,
            "youtube_id": B2,
        },
    ]
    config_doc = {
        "subscriptions": {
            "channel_size": 50,
            "live_channel_size": 0,
            "shorts_channel_size": 50,
            "playlist_size": 50,
            "auto_start": False,
            "extract_flat": False,
        },
        "downloads": {"comment_max": "all", "subtitle": "en"},
        "application": {"enable_snapshot": True},
    }
    return {
        "config": [("appsettings", config_doc)],
        "channel": [(doc["channel_id"], doc) for doc in (alpha, beta)],
        "video": [(doc["youtube_id"], doc) for doc in videos],
        "playlist": [(doc["playlist_id"], doc) for doc in playlists],
        "download": [(doc["youtube_id"], doc) for doc in downloads],
        "comment": [(doc["youtube_id"], doc) for doc in comments],
        "subtitle": [
            (
                f"{A1}-en-1",
                {
                    "youtube_id": A1,
                    "subtitle_fragment_id": f"{A1}-en-1",
                    "subtitle_line": "hello",
                    "subtitle_lang": "en",
                },
            )
        ],
    }


def ta_write_backup(path: Path, documents: dict[str, list[tuple[str, dict]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, docs in documents.items():
            # Pages of two documents, like TubeArchivist's paginated writer.
            for page, start in enumerate(range(0, len(docs), 2)):
                name = f"es_{index}-20261001-{page}.json"
                archive.writestr(name, ta_bulk(index, docs[start : start + 2]))


@dataclass
class TaLibrary:
    root: Path
    media: Path
    ta_media: Path
    cache: Path
    backup: Path
    db: Database

    def run(self, *extra: str, ta_media: bool = True) -> tuple[int, str]:
        parser = argparse.ArgumentParser()
        tubearchivist.add_arguments(parser)
        argv = ["--backup", str(self.backup)]
        if ta_media:
            argv += ["--ta-media", str(self.ta_media)]
        args = parser.parse_args([*argv, *extra])
        out = io.StringIO()
        code = asyncio.run(tubearchivist.run(args, self.db, out))
        return code, out.getvalue()

    def rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        return asyncio.run(self.db.fetch_all(sql, params))

    def video(self, youtube_id: str) -> dict[str, Any]:
        rows = self.rows(
            """SELECT v.*, c.youtube_id AS channel_youtube_id, c.name AS channel_name, s.status
               FROM videos v JOIN video_status s ON s.video_id = v.id
               LEFT JOIN channels c ON c.id = v.channel_id WHERE v.youtube_id = ?""",
            (youtube_id,),
        )
        assert rows, f"{youtube_id} was not imported"
        return rows[0]

    def dump(self) -> dict[str, list[dict[str, Any]]]:
        tables = ("channels", "videos", "subscriptions", "source_entries", "jobs", "settings")
        return {table: self.rows(f"SELECT * FROM {table} ORDER BY 1, 2") for table in tables}


def ta_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ta_folder: str) -> TaLibrary:
    media = tmp_path / "media"
    data = tmp_path / "data"
    media.mkdir()
    monkeypatch.setattr(config, "MEDIA_DIR", media)
    monkeypatch.setattr(config, "DATA_DIR", data)
    ta_media = media / ta_folder if ta_folder else media
    files = {
        f"{CHANNEL_A}/{A1}.mp4": b"A1-video",
        f"{CHANNEL_A}/{A1}.en.vtt": b"WEBVTT\n",
        f"{CHANNEL_A}/{A2}.mp4": b"A2-video-short",
        f"{CHANNEL_A}/{ORPHAN}.mp4": b"orphan",
        f"{CHANNEL_B}/{B1}.mp4": b"B1-stream",
        f"{CHANNEL_C}/{C1}.mp4": b"C1-video",
    }
    for relative, content in files.items():
        path = ta_media / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    cache = tmp_path / "cache"
    for youtube_id in (A1, B1, ORPHAN):
        thumbnail = cache / "videos" / youtube_id[0].lower() / f"{youtube_id}.jpg"
        thumbnail.parent.mkdir(parents=True, exist_ok=True)
        thumbnail.write_bytes(b"jpeg " + youtube_id.encode())
    backup = cache / "backup" / "ta_backup-20261001-manual.zip"
    ta_write_backup(backup, ta_documents())
    db = Database(config.database_path)
    asyncio.run(db.migrate())
    return TaLibrary(tmp_path, media, ta_media.resolve(), cache, backup, db)


@pytest.fixture
def ta_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TaLibrary:
    return ta_build(tmp_path, monkeypatch, "tubearchivist")


def ta_snapshot(root: Path, skip: Path) -> dict[str, tuple[int, ...]]:
    found = {}
    for path in sorted(root.rglob("*")):
        if path == skip or skip in path.parents:
            continue
        stat = path.stat()
        found[path.relative_to(root).as_posix()] = (
            (0,) if path.is_dir() else (stat.st_size, stat.st_mtime_ns)
        )
    return found


def ta_info(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def test_dry_run_writes_nothing(ta_library: TaLibrary) -> None:
    before = ta_snapshot(ta_library.root, ta_library.root / "data")

    code, output = ta_library.run()

    assert code == 0, output
    assert ta_snapshot(ta_library.root, ta_library.root / "data") == before
    assert all(not rows for rows in ta_library.dump().values())
    assert "dry run: nothing was written" in output
    assert "Videos with files       4 " in output
    assert f"Videos missing files    1 ({B2} " in output
    assert f"Orphan files            1 (tubearchivist/{CHANNEL_A}/{ORPHAN}.mp4)" in output
    assert "Subscriptions           2 channels, 2 playlists" in output
    assert "Comments                2 on 1 videos" in output
    assert "Thumbnails              3 from the cache" in output
    assert f"{ta_library.cache} (found next to the backup)" in output
    command = output.rsplit("To apply:", 1)[1].strip()
    assert command == (
        f"python -m app import-tubearchivist --backup {ta_library.backup} "
        f"--ta-media {ta_library.ta_media} --apply"
    )


def test_apply_imports_in_place(ta_library: TaLibrary) -> None:
    code, output = ta_library.run("--apply")

    assert code == 0, output
    assert "TubeArchivist import (applied)" in output
    video = ta_library.video(A1)
    media = ta_library.ta_media / CHANNEL_A / f"{A1}.mp4"
    assert video["media_path"] == f"tubearchivist/{CHANNEL_A}/{A1}.mp4"
    assert video["media_size"] == media.stat().st_size
    assert video["status"] == "archived"
    assert video["title"] == "Alpha video one"
    assert video["description"] == "Description of Alpha video one"
    assert video["duration"] == 125
    assert video["published_at"] == ta_date(PUBLISHED)
    assert (video["view_count"], video["like_count"]) == (1000, 50)
    assert (video["width"], video["height"], video["video_type"]) == (1920, 1080, "video")
    assert video["archived_at"] == ta_moment(DOWNLOADED)
    assert (video["channel_youtube_id"], video["channel_name"]) == (CHANNEL_A, "Alpha Channel")

    info = ta_info(media.with_name(f"{A1}.info.json"))
    assert info["id"] == A1
    assert info["title"] == "Alpha video one"
    assert info["upload_date"] == ta_date(PUBLISHED).replace("-", "")
    assert info["timestamp"] == PUBLISHED
    assert info["channel_id"] == CHANNEL_A
    assert info["channel"] == "Alpha Channel"
    assert info["tags"] == ["tag one", "tag two"]
    assert info["categories"] == ["Education"]
    assert info["webpage_url"] == f"https://www.youtube.com/watch?v={A1}"
    assert info["_tubearchivist"]["media_url"] == f"{CHANNEL_A}/{A1}.mp4"
    assert media.with_name(f"{A1}.jpg").read_bytes() == f"jpeg {A1}".encode()
    assert media.with_name(f"{A1}.en.vtt").is_file()

    short = ta_library.video(A2)
    assert (short["video_type"], short["width"], short["height"]) == ("short", 1080, 1920)
    stream = ta_library.video(B1)
    assert (stream["video_type"], stream["published_at"]) == ("live", "2023-05-06")
    assert ta_info(ta_library.ta_media / CHANNEL_B / f"{B1}.info.json")["was_live"] is True

    channels = {row["youtube_id"]: row for row in ta_library.rows("SELECT * FROM channels")}
    assert channels[CHANNEL_A]["name"] == "Alpha Channel"
    assert channels[CHANNEL_A]["description"] == "About Alpha Channel"
    assert channels[CHANNEL_A]["subscriber_count"] == 1234
    assert channels[CHANNEL_C]["name"] == "Charlie Channel"
    assert channels[CHANNEL_C]["description"] == "About Charlie Channel"
    assert CHANNEL_GONE not in channels


def test_apply_with_organize_renames_into_the_library_layout(ta_library: TaLibrary) -> None:
    code, output = ta_library.run("--apply", "--organize")

    assert code == 0, output
    folder = ta_library.media / f"Alpha Channel [{CHANNEL_A}]"
    base = folder / f"{ta_date(PUBLISHED)} Alpha video one [{A1}]"
    assert base.with_suffix(".mp4").read_bytes() == b"A1-video"
    assert Path(f"{base}.en.vtt").read_text() == "WEBVTT\n"
    assert Path(f"{base}.jpg").read_bytes() == f"jpeg {A1}".encode()
    assert ta_info(Path(f"{base}.info.json"))["id"] == A1
    assert ta_library.video(A1)["media_path"] == (
        f"Alpha Channel [{CHANNEL_A}]/{ta_date(PUBLISHED)} Alpha video one [{A1}].mp4"
    )
    assert not (ta_library.ta_media / CHANNEL_A / f"{A1}.mp4").exists()
    assert not (ta_library.ta_media / CHANNEL_A / f"{A1}.en.vtt").exists()
    stream = ta_library.media / f"Beta Channel [{CHANNEL_B}]" / f"2023-05-06 Beta stream [{B1}].mp4"
    assert stream.is_file()
    assert ta_library.video(B1)["media_path"] == stream.relative_to(ta_library.media).as_posix()
    # Emptied TubeArchivist folders are removed; the orphan stays where it was.
    assert not (ta_library.ta_media / CHANNEL_C).exists()
    assert (ta_library.ta_media / CHANNEL_A / f"{ORPHAN}.mp4").is_file()
    assert "Moves                   4 videos with their sidecars" in output
    assert f"tubearchivist/{CHANNEL_A}/{A1}.mp4 -> Alpha Channel [{CHANNEL_A}]/" in output


def test_organize_from_the_default_media_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = ta_build(tmp_path, monkeypatch, "")

    code, output = library.run("--apply", "--organize", ta_media=False)

    assert code == 0, output
    expected = f"Charlie Channel [{CHANNEL_C}]/{ta_date(PUBLISHED)} Charlie video [{C1}].mp4"
    assert library.video(C1)["media_path"] == expected
    assert (library.media / expected).is_file()
    assert not (library.media / CHANNEL_C).exists()
    assert library.video(ORPHAN)["media_path"] == f"{CHANNEL_A}/{ORPHAN}.mp4"


def test_video_with_missing_file_is_imported_as_not_downloaded(ta_library: TaLibrary) -> None:
    code, output = ta_library.run("--apply")

    assert code == 0, output
    video = ta_library.video(B2)
    assert video["media_path"] is None
    assert video["status"] == "missing"
    assert video["title"] == "Beta lost video"
    assert video["published_at"] == ta_date(PUBLISHED)
    assert f'Videos missing files    1 ({B2} "Beta lost video")' in output


def test_orphan_file_is_imported_with_minimal_metadata(ta_library: TaLibrary) -> None:
    code, output = ta_library.run("--apply")

    assert code == 0, output
    orphan = ta_library.video(ORPHAN)
    assert orphan["title"] == ORPHAN
    assert orphan["media_path"] == f"tubearchivist/{CHANNEL_A}/{ORPHAN}.mp4"
    assert orphan["media_size"] == len(b"orphan")
    assert orphan["channel_youtube_id"] == CHANNEL_A
    assert (ta_library.ta_media / CHANNEL_A / f"{ORPHAN}.jpg").is_file()
    assert f"Orphan files            1 (tubearchivist/{CHANNEL_A}/{ORPHAN}.mp4)" in output


def test_unavailable_and_watched_state(ta_library: TaLibrary) -> None:
    code, output = ta_library.run("--apply")

    assert code == 0, output
    assert ta_library.video(A2)["unavailable_at"] is not None
    assert ta_library.video(A1)["unavailable_at"] is None
    assert ta_library.video(A1)["watched_at"] == ta_moment(WATCHED)
    assert ta_library.video(A2)["watched_at"] is None
    assert "Unavailable on YouTube  1" in output
    assert "Watched                 1" in output


def test_subscriptions_follow_tubearchivist(ta_library: TaLibrary) -> None:
    start = datetime.now(UTC).replace(microsecond=0)

    code, output = ta_library.run("--apply")

    assert code == 0, output
    subscriptions = {
        (row["kind"], row["youtube_id"]): row
        for row in ta_library.rows(
            """SELECT s.*, c.youtube_id AS channel_youtube_id FROM subscriptions s
               LEFT JOIN channels c ON c.id = s.channel_id"""
        )
    }
    assert set(subscriptions) == {
        ("channel", CHANNEL_A),
        ("channel", CHANNEL_B),
        ("playlist", "PLsubscribed"),
        ("playlist", "PLbottom"),
    }
    alpha = subscriptions[("channel", CHANNEL_A)]
    assert json.loads(alpha["content_types"]) == ["video", "short"]
    # TubeArchivist's live_channel_size of 0 means it never followed the streams tab.
    assert json.loads(subscriptions[("channel", CHANNEL_B)]["content_types"]) == ["video"]
    for row in subscriptions.values():
        assert row["download_policy"] == "new"
        assert row["enabled"] == 1
        next_check = datetime.fromisoformat(row["next_check_at"].replace("Z", "+00:00"))
        assert start <= next_check <= start + timedelta(hours=24, seconds=5)
    assert alpha["inventoried_types"] == "[]"
    assert (alpha["title"], alpha["channel_youtube_id"]) == ("Alpha Channel", CHANNEL_A)
    picks = subscriptions[("playlist", "PLsubscribed")]
    assert json.loads(picks["inventoried_types"]) == ["playlist"]
    assert (picks["title"], picks["owner_name"]) == ("Alpha picks", "Alpha Channel")
    assert picks["channel_youtube_id"] == CHANNEL_A

    entries = ta_library.rows(
        """SELECT e.youtube_id, e.position, e.baseline, e.video_type, e.title, s.youtube_id AS source
           FROM source_entries e JOIN subscriptions s ON s.id = e.subscription_id
           ORDER BY s.youtube_id, e.position"""
    )
    assert [
        (row["source"], row["youtube_id"], row["position"], row["video_type"]) for row in entries
    ] == [
        ("PLbottom", B2, 0, "video"),
        ("PLbottom", B1, 2, "live"),
        ("PLsubscribed", A1, 0, "video"),
        ("PLsubscribed", A2, 1, "short"),
        ("PLsubscribed", "notarchived", 2, "video"),
    ]
    assert all(row["baseline"] == 1 for row in entries)
    assert 'Custom playlists        1 ("Favourites") (not imported)' in output
    assert "Unsubscribed playlists  1 (not imported)" in output


def test_no_subscriptions_option(ta_library: TaLibrary) -> None:
    code, output = ta_library.run("--apply", "--no-subscriptions")

    assert code == 0, output
    assert not ta_library.rows("SELECT * FROM subscriptions")
    assert "not imported (--no-subscriptions): 2 channels, 2 playlists" in output


def test_ignore_list_becomes_removed_videos(ta_library: TaLibrary) -> None:
    code, output = ta_library.run("--apply")

    assert code == 0, output
    ignored = ta_library.video("ignored0001")
    assert ignored["deleted_at"] is not None
    assert ignored["status"] == "deleted"
    assert ignored["title"] == "Ignored one"
    assert ignored["duration"] == 3723
    assert ignored["published_at"] == ta_date(1690000000)
    assert ignored["channel_youtube_id"] == CHANNEL_B
    other = ta_library.video("ignored0002")
    assert (other["deleted_at"] is not None, other["channel_id"]) == (True, None)
    assert other["video_type"] == "short"
    assert not ta_library.rows("SELECT * FROM videos WHERE youtube_id = 'pending0001'")
    assert ta_library.video(B1)["deleted_at"] is None
    assert "Ignore list             2 videos marked as removed (1 more already in" in output
    assert "Pending downloads       1 (not imported)" in output


def test_comments_are_merged_into_info_json(ta_library: TaLibrary) -> None:
    code, output = ta_library.run("--apply")

    assert code == 0, output
    info = ta_info(ta_library.ta_media / CHANNEL_A / f"{A1}.info.json")
    assert info["comment_count"] == 2
    assert info["comments"] == [
        {
            "author": "Viewer",
            "author_id": "UC" + "v" * 22,
            "author_is_uploader": False,
            "author_thumbnail": "https://yt3.example/viewer.jpg",
            "id": "Ugx1",
            "is_favorited": False,
            "like_count": 3,
            "parent": "root",
            "text": "First!",
            "_time_text": "2023-11-14 22:21",
            "timestamp": DOWNLOADED + 500,
        },
        {
            "author": "Viewer",
            "author_id": "UC" + "v" * 22,
            "author_is_uploader": True,
            "author_thumbnail": "https://yt3.example/viewer.jpg",
            "id": "Ugx1.r1",
            "is_favorited": False,
            "like_count": 3,
            "parent": "Ugx1",
            "text": "Thanks",
            "_time_text": "2023-11-14 22:21",
            "timestamp": DOWNLOADED + 500,
        },
    ]
    assert info["_tubearchivist_comments"]["comment_last_refresh"] == DOWNLOADED
    assert "Comments                2 on 1 videos" in output
    # The video without a file has nowhere to keep its comments, and the report says so.
    warning = next(line for line in output.splitlines() if "comments on videos without" in line)
    assert warning.endswith(f": 1 ({B2})")


def test_running_apply_again_changes_nothing(
    ta_library: TaLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, output = ta_library.run("--apply", "--organize")
    assert code == 0, output
    database = ta_library.dump()
    files = ta_snapshot(ta_library.root, ta_library.root / "data")
    # Any write during the second run would carry this timestamp.
    monkeypatch.setattr("app.library.now", lambda: "2099-01-01T00:00:00Z")
    monkeypatch.setattr("app.tubearchivist.now", lambda: "2099-01-01T00:00:00Z")

    code, output = ta_library.run("--apply", "--organize")

    assert code == 0, output
    assert ta_library.dump() == database
    assert ta_snapshot(ta_library.root, ta_library.root / "data") == files
    assert "Already in library      5 (left unchanged)" in output
    assert "Channels                3 (0 new)" in output
    assert "Subscriptions           0 channels, 0 playlists (4 already existed)" in output
    assert "Orphan files            0" in output
    assert "Ignore list             0 videos marked as removed (3 more already in" in output


def test_interrupted_organize_resumes(ta_library: TaLibrary) -> None:
    async def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("database went away")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(tubearchivist, "record_archived", fail)
        with pytest.raises(RuntimeError):
            ta_library.run("--apply", "--organize")
    # The batch's files were renamed before its transaction rolled back.
    assert not ta_library.rows("SELECT * FROM videos")
    assert not (ta_library.ta_media / CHANNEL_A / f"{A1}.mp4").exists()

    code, output = ta_library.run("--apply", "--organize")

    assert code == 0, output
    expected = f"Alpha Channel [{CHANNEL_A}]/{ta_date(PUBLISHED)} Alpha video one [{A1}].mp4"
    video = ta_library.video(A1)
    assert (video["media_path"], video["title"]) == (expected, "Alpha video one")
    assert ta_info(ta_library.media / expected.replace(".mp4", ".info.json"))["comments"]
    assert ta_library.video(B1)["media_path"].startswith(f"Beta Channel [{CHANNEL_B}]/")
    assert "Videos with files       4 " in output
    assert "Moves                   0 videos" in output


def test_ta_media_outside_media_dir_fails(ta_library: TaLibrary) -> None:
    outside = ta_library.root / "elsewhere"
    outside.mkdir()

    code, output = ta_library.run("--apply", "--ta-media", str(outside), ta_media=False)

    assert code != 0
    assert "outside MEDIA_DIR" in output
    assert "relative to MEDIA_DIR" in output
    assert "same-filesystem renames" in output
    assert all(not rows for rows in ta_library.dump().values())


def ta_rescan_row(library: TaLibrary, youtube_id: str, media_path: str) -> None:
    """A row as YouHoard's library rescan creates it for a file without an .info.json."""

    async def insert() -> None:
        async with library.db.transaction() as conn:
            video_id = await ensure_video(conn, youtube_id, youtube_id)
            await record_archived(conn, video_id, media_path, 8)

    asyncio.run(insert())


def test_rescanned_video_gets_tubearchivist_metadata(ta_library: TaLibrary) -> None:
    ta_rescan_row(ta_library, A1, f"tubearchivist/{CHANNEL_A}/{A1}.mp4")

    code, output = ta_library.run("--apply")

    assert code == 0, output
    video = ta_library.video(A1)
    assert (video["title"], video["published_at"]) == ("Alpha video one", ta_date(PUBLISHED))
    assert video["watched_at"] == ta_moment(WATCHED)
    assert video["archived_at"] == ta_moment(DOWNLOADED)
    assert (ta_library.ta_media / CHANNEL_A / f"{A1}.info.json").is_file()
    assert "Filled in               1 videos listed without metadata" in output


def test_interrupted_fill_in_resumes(ta_library: TaLibrary) -> None:
    ta_rescan_row(ta_library, A1, f"tubearchivist/{CHANNEL_A}/{A1}.mp4")

    async def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("database is locked")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(tubearchivist, "record_archived", fail)
        with pytest.raises(RuntimeError):
            ta_library.run("--apply")
    # The sidecar was written before the transaction rolled back.
    assert (ta_library.ta_media / CHANNEL_A / f"{A1}.info.json").is_file()
    assert ta_library.video(A1)["title"] == A1

    code, output = ta_library.run("--apply")

    assert code == 0, output
    video = ta_library.video(A1)
    assert (video["title"], video["watched_at"]) == ("Alpha video one", ta_moment(WATCHED))
    assert "Filled in               1 videos listed without metadata" in output


def test_existing_library_rows_are_kept(ta_library: TaLibrary) -> None:
    async def seed() -> None:
        async with ta_library.db.transaction() as conn:
            await upsert_channel(conn, CHANNEL_A, "Alpha Renamed", None, "Newer words", 999)
            info = {"id": A2, "title": "YouHoard title", "upload_date": "20231103", "view_count": 7}
            video_id, _ = await save_video_info(conn, {**info, "channel_id": CHANNEL_A}, "short")
            await record_archived(conn, video_id, f"tubearchivist/{CHANNEL_A}/{A2}.mp4", 14)

    asyncio.run(seed())

    code, output = ta_library.run("--apply")

    assert code == 0, output
    channel = ta_library.rows("SELECT * FROM channels WHERE youtube_id = ?", (CHANNEL_A,))[0]
    assert (channel["name"], channel["description"], channel["subscriber_count"]) == (
        "Alpha Renamed",
        "Newer words",
        999,
    )
    assert ta_library.video(A1)["channel_name"] == "Alpha Renamed"
    kept = ta_library.video(A2)
    assert (kept["title"], kept["view_count"], kept["unavailable_at"]) == (
        "YouHoard title",
        7,
        None,
    )
    assert f"marks unavailable (not applied): 1 ({A2})" in output
    # The sidecar it lacked is written from TubeArchivist's data; the row stays as it was.
    assert ta_info(ta_library.ta_media / CHANNEL_A / f"{A2}.info.json")["title"] == "Alpha short"
    assert "Already in library      1 (left unchanged)" in output
    assert "Repaired                1 of them" in output


def test_older_backup_variants(ta_library: TaLibrary) -> None:
    documents = ta_documents()
    plain_channels = "\n".join(json.dumps(doc) for _, doc in documents["channel"])
    with zipfile.ZipFile(ta_library.backup, "w") as archive:
        # Very old backups carry every index twice: bulk files and JSON arrays.
        archive.writestr("es_video-20200101.json", ta_bulk("video", documents["video"]))
        archive.writestr(
            "ta_video-20200101.json", json.dumps([doc for _, doc in documents["video"]])
        )
        archive.writestr("channels.ndjson", plain_channels)
        archive.writestr(
            "ta_download-20200101.json",
            json.dumps([doc for _, doc in documents["download"]], indent=2),
        )
        # An Elasticsearch dump of search hits, with a versioned index name.
        archive.writestr(
            "export.json",
            "\n".join(
                json.dumps({"_index": "ta_playlist_v2", "_id": doc_id, "_source": doc})
                for doc_id, doc in documents["playlist"]
            ),
        )

    code, output = ta_library.run()

    assert code == 0, output
    assert "1 duplicate copies skipped" in output
    assert "Documents: 2 channel, 5 video, 4 playlist, 4 download" in output
    assert "duplicate documents" not in output
    assert "Videos with files       4 " in output
    assert "Subscriptions           2 channels, 2 playlists" in output
    assert "Ignore list             2 videos marked as removed" in output


def test_truncated_backup_file_is_reported(ta_library: TaLibrary) -> None:
    documents = ta_documents()
    truncated = ta_bulk("video", documents["video"]).rstrip()[:-40]
    with zipfile.ZipFile(ta_library.backup, "w") as archive:
        archive.writestr("es_channel-20261001-0.json", ta_bulk("channel", documents["channel"]))
        archive.writestr("es_video-20261001-0.json", truncated)

    code, output = ta_library.run("--apply")

    assert code == 0, output
    assert "backup files that could not be read to the end (rest skipped): 1" in output
    assert "es_video-20261001-0.json after 4 documents" in output
    titles = {row["youtube_id"]: row["title"] for row in ta_library.rows("SELECT * FROM videos")}
    # The cut-off document's file is still imported, as an orphan.
    assert titles == {
        A1: "Alpha video one",
        A2: "Alpha short",
        B1: "Beta stream",
        B2: "Beta lost video",
        C1: C1,
        ORPHAN: ORPHAN,
    }


def test_damaged_backup_member_is_reported(ta_library: TaLibrary) -> None:
    name = "es_video-20261001-0.json"
    with zipfile.ZipFile(ta_library.backup, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "es_channel-20261001-0.json", ta_bulk("channel", ta_documents()["channel"])
        )
        archive.writestr(name, ta_bulk("video", ta_documents()["video"]))
        member = archive.getinfo(name)
    data = bytearray(ta_library.backup.read_bytes())
    name_length, extra_length = struct.unpack_from("<HH", data, member.header_offset + 26)
    start = member.header_offset + 30 + name_length + extra_length
    middle = start + member.compress_size // 2
    data[middle : middle + 16] = bytes(16)
    ta_library.backup.write_bytes(bytes(data))

    code, output = ta_library.run()

    assert code == 0, output
    assert f"could not be read to the end (rest skipped): 1 ({name} after" in output
    assert "Orphan files" in output


def test_leftovers_of_an_unfinished_backup_are_skipped(ta_library: TaLibrary) -> None:
    documents = ta_documents()
    stale = [(doc_id, {**doc, "title": "Stale title"}) for doc_id, doc in documents["video"]]
    alpha = documents["channel"][0][1]
    stale.append(("deleted0001", ta_video_doc("deleted0001", alpha, "Deleted since")))
    with zipfile.ZipFile(ta_library.backup, "a") as archive:
        archive.writestr("es_video-20250101-0.json", ta_bulk("video", stale))

    code, output = ta_library.run("--apply")

    assert code == 0, output
    assert ta_library.video(A1)["title"] == "Alpha video one"
    assert not ta_library.rows("SELECT * FROM videos WHERE youtube_id = 'deleted0001'")
    assert "unfinished earlier backup (skipped; the newest backup's files were read): 1" in output
    assert "duplicate documents" not in output


def test_organize_never_replaces_existing_files(ta_library: TaLibrary) -> None:
    folder = ta_library.media / f"Alpha Channel [{CHANNEL_A}]"
    folder.mkdir()
    taken = folder / f"{ta_date(PUBLISHED)} Alpha video one [{A1}].en.vtt"
    taken.write_text("someone else's subtitles")

    code, output = ta_library.run("--apply", "--organize")

    assert code == 0, output
    assert taken.read_text() == "someone else's subtitles"
    assert ta_library.video(A1)["media_path"] == f"tubearchivist/{CHANNEL_A}/{A1}.mp4"
    assert (ta_library.ta_media / CHANNEL_A / f"{A1}.en.vtt").read_text() == "WEBVTT\n"
    assert (ta_library.ta_media / CHANNEL_A / f"{A1}.info.json").is_file()
    assert "videos whose new name is already taken, left in place: 1" in output
    assert ta_library.video(A2)["media_path"].startswith(f"Alpha Channel [{CHANNEL_A}]/")


def test_failed_rename_moves_sidecars_back(
    ta_library: TaLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    replace = os.replace

    def full_disk(source: Any, target: Any) -> None:
        if str(source).endswith(f"{A1}.mp4"):
            raise OSError(28, "No space left on device")
        replace(source, target)

    monkeypatch.setattr(os, "replace", full_disk)

    code, output = ta_library.run("--apply", "--organize")

    assert code == 0, output
    folder = ta_library.ta_media / CHANNEL_A
    assert (folder / f"{A1}.en.vtt").read_text() == "WEBVTT\n"
    assert (folder / f"{A1}.info.json").is_file()
    assert (folder / f"{A1}.jpg").is_file()
    assert ta_library.video(A1)["media_path"] == f"tubearchivist/{CHANNEL_A}/{A1}.mp4"
    assert not list((ta_library.media / f"Alpha Channel [{CHANNEL_A}]").glob(f"*{A1}*"))
    assert "files that could not be moved (left in place): 1" in output


def test_bracketed_folder_names_are_not_channel_ids(ta_library: TaLibrary) -> None:
    folder = ta_library.ta_media / "Foo [Official]"
    folder.mkdir()
    (folder / "orphan00002.mp4").write_bytes(b"x")

    code, output = ta_library.run("--apply")

    assert code == 0, output
    assert ta_library.video("orphan00002")["channel_id"] is None
    assert not ta_library.rows("SELECT * FROM channels WHERE youtube_id = 'Official'")


def ta_use_legacy_name(ta_library: TaLibrary) -> Path:
    """Rename A1 to TubeArchivist's pre-0.4 naming and point its document at it."""
    legacy = ta_library.ta_media / "Alpha Channel" / f"20231103_{A1}_Alpha video one.mp4"
    legacy.parent.mkdir()
    (ta_library.ta_media / CHANNEL_A / f"{A1}.mp4").rename(legacy)
    (ta_library.ta_media / CHANNEL_A / f"{A1}.en.vtt").rename(f"{legacy.with_suffix('')}.en.vtt")
    documents = ta_documents()
    documents["video"][0][1]["media_url"] = legacy.relative_to(ta_library.ta_media).as_posix()
    ta_write_backup(ta_library.backup, documents)
    return legacy


def test_legacy_names_work_in_place(ta_library: TaLibrary) -> None:
    legacy = ta_use_legacy_name(ta_library)

    code, output = ta_library.run("--apply")

    assert code == 0, output
    stored = ta_library.video(A1)["media_path"]
    assert stored == f"tubearchivist/Alpha Channel/20231103_{A1}_Alpha video one.mp4"
    assert layout.video_id_from_media(legacy) == A1
    assert set(layout.subtitles_for(legacy)) == {"en"}
    assert "names without their video ID" not in output


def test_legacy_names_are_renamed_by_organize(ta_library: TaLibrary) -> None:
    ta_use_legacy_name(ta_library)

    code, output = ta_library.run("--apply", "--organize")

    assert code == 0, output
    base = f"Alpha Channel [{CHANNEL_A}]/{ta_date(PUBLISHED)} Alpha video one [{A1}]"
    assert ta_library.video(A1)["media_path"] == f"{base}.mp4"
    assert (ta_library.media / f"{base}.en.vtt").read_text() == "WEBVTT\n"
    assert ta_info(ta_library.media / f"{base}.info.json")["id"] == A1


def test_files_that_cannot_be_imported_are_reported(ta_library: TaLibrary) -> None:
    folder = ta_library.ta_media / CHANNEL_A
    (folder / "holiday clip.mp4").write_bytes(b"x")
    (ta_library.ta_media / "loose.mp4").write_bytes(b"x")
    outside = ta_library.root / "elsewhere.mp4"
    outside.write_bytes(b"x")
    (folder / "linked00001.mp4").symlink_to(outside)

    code, output = ta_library.run()

    assert code == 0, output
    assert "video files without a video ID in their name (not imported): 1" in output
    assert "video files outside any channel folder (not imported): 1 (tubearchivist/loose" in output
    assert (
        f"(not imported; YouHoard needs the files themselves): 1 (tubearchivist/{CHANNEL_A}/"
        in output
    )


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 64, 1 << 20])
def test_json_reader_handles_every_layout(chunk_size: int) -> None:
    values: list[Any] = [{"a": "x" * (n % 50), "n": n * 7919**3} for n in range(120)]
    values += [12345678901234567890, "str]ing[", [1, [2, 3]], None, True, 1.5e10, {"é": "ü"}]
    layouts = {
        "nd-json": "\n".join(json.dumps(value) for value in values),
        "array": json.dumps(values, indent=2),
        "concatenated": " ".join(json.dumps(value) for value in values),
    }
    for name, text in layouts.items():
        stream = io.StringIO(text)
        assert list(tubearchivist.iter_json_values(stream, chunk_size)) == values, name


def test_elasticsearch_source(ta_library: TaLibrary, monkeypatch: pytest.MonkeyPatch) -> None:
    documents = ta_documents()
    requests: list[tuple[str, str]] = []

    def hits(index: str, page: int) -> list[dict[str, Any]]:
        docs = documents[index][page * 2 : page * 2 + 2]
        return [{"_index": f"ta_{index}_v1", "_id": i, "_source": doc} for i, doc in docs]

    def respond(index: str, page: int) -> httpx.Response:
        # The download index counts one document more than it returns, as after a shard failure.
        total = len(documents[index]) + (index == "download")
        return httpx.Response(
            200,
            json={
                "_scroll_id": f"{index}:{page + 1}",
                "_shards": {"total": 1, "successful": 1, "failed": 0},
                "hits": {"total": {"value": total, "relation": "eq"}, "hits": hits(index, page)},
            },
        )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        expected = "Basic " + base64.b64encode(b"elastic:secret").decode()
        assert request.headers["authorization"] == expected
        if request.method == "DELETE":
            return httpx.Response(200, json={"succeeded": True})
        body = json.loads(request.content)
        if request.url.path == "/_search/scroll":
            index, page = body["scroll_id"].split(":")
            return respond(index, int(page))
        assert request.url.params["scroll"] == "5m"
        index = request.url.path.split("/")[1].removeprefix("ta_")
        if index not in ("channel", "video", "download"):
            return httpx.Response(404, json={"error": {"type": "index_not_found_exception"}})
        return respond(index, 0)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        tubearchivist,
        "ElasticSource",
        functools.partial(tubearchivist.ElasticSource, transport=transport),
    )
    monkeypatch.setenv("TA_ES_PASSWORD", "secret")
    parser = argparse.ArgumentParser()
    tubearchivist.add_arguments(parser)
    args = parser.parse_args(
        ["--es-url", "http://es.test:9200", "--ta-media", str(ta_library.ta_media)]
    )
    out = io.StringIO()

    code = asyncio.run(tubearchivist.run(args, ta_library.db, out))

    output = out.getvalue()
    assert code == 0, output
    assert "Elasticsearch at http://es.test:9200" in output
    assert "Documents: 2 channel, 5 video, 4 download" in output
    assert "Videos with files       4 " in output
    assert ("POST", "/_search/scroll") in requests
    assert requests.count(("DELETE", "/_search/scroll")) == 3
    assert "Elasticsearch indexes not found: 2 (ta_playlist, ta_comment)" in output
    assert "Elasticsearch returned incomplete results" in output
    assert "run the import again: 1 (ta_download: 4 of 5)" in output
    assert "--es-url http://es.test:9200 --ta-media" in output
