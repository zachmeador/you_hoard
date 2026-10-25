"""The library: list, add, download, remove and play videos."""

import asyncio
import shutil
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from app import layout, sidecar, trash
from app.api.deps import (
    clean_languages,
    get_db,
    get_runner,
    get_settings,
    get_youtube,
    load_video,
    not_found,
    video_out,
)
from app.db import Database, from_timestamp, loads, now
from app.jobs import JobRunner
from app.languages import language_name
from app.library import VIDEO_SELECT, archive_facts, published_at, record_archived, save_video_info
from app.settings import Settings
from app.tracks import AUTO, TRANSLATED, UPLOADED
from app.youtube import (
    QUALITIES,
    Inaccessible,
    NotReady,
    Unavailable,
    YouTube,
    YouTubeError,
    parse_video_url,
)

router = APIRouter()
Quality = Literal[tuple(QUALITIES)]
SORTS = {
    "published": "v.published_at",
    "archived": "v.archived_at",
    "added": "v.created_at",
    "title": "v.title COLLATE NOCASE",
    "duration": "v.duration",
    "views": "v.view_count",
}
STATUSES = ("archived", "downloading", "queued", "failed", "deleted", "missing")
SUBTITLE_SOURCES = (UPLOADED, AUTO, TRANSLATED)
# A resolved video's metadata is reused when it is added soon after, so YouTube is asked once.
RESOLVED_TTL = 600


class VideoOptions(BaseModel):
    """Download options for this video; anything left out follows the subscription or library."""

    quality: Quality | None = None
    subtitle_languages: list[str] | None = None
    auto_captions: bool | None = None
    download_comments: bool | None = None
    audio_languages: list[str] | None = None
    live_chat: bool | None = None
    sponsorblock: bool | None = None

    @field_validator("subtitle_languages", "audio_languages")
    @classmethod
    def languages(cls, value: list[str] | None) -> list[str] | None:
        return clean_languages(value)


class VideoUrl(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def video_id(cls, value: str) -> str:
        return parse_video_url(value)


class AddVideo(VideoOptions, VideoUrl):
    pass


def resolved_cache(request: Request) -> dict[str, tuple[float, dict[str, Any] | None]]:
    if not hasattr(request.app.state, "resolved_videos"):
        request.app.state.resolved_videos = {}
    return request.app.state.resolved_videos


async def fetch_info(
    youtube: YouTube, youtube_id: str, cache: dict[str, tuple[float, dict[str, Any] | None]]
) -> dict[str, Any] | None:
    """YouTube's metadata for a video, or None for one that has not aired yet."""
    cached = cache.pop(youtube_id, None)
    if cached and time.monotonic() - cached[0] < RESOLVED_TTL:
        return cached[1]
    try:
        return await youtube.fetch_video(youtube_id)
    except NotReady:
        return None
    except (Unavailable, Inaccessible) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except YouTubeError as error:
        raise HTTPException(status_code=502, detail=f"YouTube: {error}") from error


class Watched(BaseModel):
    watched: bool


def video_filters(
    q: str | None = None,
    video_type: Literal["video", "short", "live"] | None = None,
    channel_id: int | None = None,
    watched: bool | None = None,
    unavailable: bool | None = None,
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if q:
        clauses.append("(v.title LIKE ? OR v.description LIKE ? OR c.name LIKE ?)")
        params += [f"%{q.strip()}%"] * 3
    if video_type:
        clauses.append("v.video_type = ?")
        params.append(video_type)
    if channel_id is not None:
        clauses.append("v.channel_id = ?")
        params.append(channel_id)
    if watched is not None:
        clauses.append(f"v.watched_at IS {'NOT ' if watched else ''}NULL")
    if unavailable is not None:
        clauses.append(f"v.unavailable_at IS {'NOT ' if unavailable else ''}NULL")
    return clauses, params


@router.get("")
async def list_videos(
    status: Literal[STATUSES] | None = None,
    filters: tuple[list[str], list[Any]] = Depends(video_filters),
    sort: Literal[tuple(SORTS)] = "published",
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    per_page: int = Query(48, ge=1, le=200),
    db: Database = Depends(get_db),
):
    clauses, params = filters
    clauses = ["s.status = ?" if status else "s.status != 'deleted'", *clauses]
    params = [status, *params] if status else params
    where = " AND ".join(clauses)
    total = await db.fetch_value(
        "SELECT count(*) FROM videos v JOIN video_status s ON s.video_id = v.id "
        f"LEFT JOIN channels c ON c.id = v.channel_id WHERE {where}",
        params,
    )
    direction = order.upper()
    rows = await db.fetch_all(
        f"{VIDEO_SELECT} WHERE {where} "
        f"ORDER BY {SORTS[sort]} {direction} NULLS LAST, v.id {direction} LIMIT ? OFFSET ?",
        [*params, per_page, (page - 1) * per_page],
    )
    return {
        "items": [video_out(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/counts")
async def video_counts(
    filters: tuple[list[str], list[Any]] = Depends(video_filters),
    db: Database = Depends(get_db),
):
    """How many videos each status tab would show under the same filters."""
    clauses, params = filters
    where = " AND ".join(clauses) or "1"
    rows = await db.fetch_all(
        "SELECT s.status, count(*) AS n, count(v.unavailable_at) AS gone "
        "FROM videos v JOIN video_status s ON s.video_id = v.id "
        f"LEFT JOIN channels c ON c.id = v.channel_id WHERE {where} GROUP BY s.status",
        params,
    )
    counts = dict.fromkeys(STATUSES, 0)
    unavailable = 0
    for row in rows:
        counts[row["status"]] = row["n"]
        if row["status"] != "deleted":
            unavailable += row["gone"]
    return {
        "all": sum(n for status, n in counts.items() if status != "deleted"),
        "archived": counts["archived"],
        "downloading": counts["downloading"],
        "queued": counts["queued"],
        "failed": counts["failed"],
        "missing": counts["missing"],
        "deleted": counts["deleted"],
        "unavailable": unavailable,
    }


def subtitle_list(row: dict[str, Any], media: Path, info: dict[str, Any]) -> list[dict[str, Any]]:
    """The subtitle files with the language name and source recorded when they were saved."""
    saved = loads(row["subtitle_tracks"]) or (info.get("_youhoard") or {}).get("subtitles") or []
    recorded = {t["lang"]: t for t in saved if isinstance(t, dict) and t.get("lang")}
    found = layout.subtitles_for(media)
    languages = [lang for lang in recorded if lang in found]
    languages += sorted(lang for lang in found if lang not in recorded)
    tracks = []
    for lang in languages:
        track = recorded.get(lang, {})
        source = track.get("source")
        tracks.append(
            {
                "lang": lang,
                "name": track.get("name") or language_name(lang) or lang,
                "source": source if source in SUBTITLE_SOURCES else "unknown",
                "url": f"/api/videos/{row['id']}/subtitles/{lang}",
            }
        )
    return tracks


def video_details(row: dict[str, Any], media: Path | None) -> dict[str, Any]:
    info = sidecar.read_info(media) if media else {}
    comments = info.get("comments")
    video_id = row["id"]
    return {
        "tags": [str(tag) for tag in info.get("tags") or ()],
        "categories": [str(category) for category in info.get("categories") or ()],
        "chapters": sidecar.chapters(info),
        "heatmap": sidecar.heatmap(info),
        "sponsor_segments": sidecar.sponsor_segments(info),
        "subtitles": subtitle_list(row, media, info) if media else [],
        "files": sidecar.files(media) if media else [],
        "comments": {"saved": len(comments), "url": f"/api/videos/{video_id}/comments"}
        if isinstance(comments, list)
        else None,
        "chat_url": f"/api/videos/{video_id}/chat" if media and layout.chat_for(media) else None,
    }


@router.get("/{video_id}")
async def get_video(video_id: int, db: Database = Depends(get_db)):
    row = await load_video(db, video_id)
    media = None
    if row["media_path"]:
        try:
            media = layout.media_file(row["media_path"], row["youtube_id"])
        except layout.PathError:
            pass
    entry = None
    if row["deleted_at"] and not row["media_path"]:
        entry = await asyncio.to_thread(trash.latest, row["youtube_id"])
    return {
        **video_out(row),
        **await asyncio.to_thread(video_details, row, media),
        "trash": {"removed_at": entry.removed_at, "expires_at": entry.expires_at}
        if entry
        else None,
    }


@router.post("/resolve")
async def resolve_video(
    body: VideoUrl,
    request: Request,
    db: Database = Depends(get_db),
    youtube: YouTube = Depends(get_youtube),
):
    """Preview a video URL before adding it: what it is, and whether the library has it."""
    youtube_id = body.url
    existing = await db.fetch_one(f"{VIDEO_SELECT} WHERE v.youtube_id = ?", (youtube_id,))
    if existing:
        video = video_out(existing)
        return {
            "youtube_id": youtube_id,
            "title": video["title"],
            "channel_name": video["channel"]["name"] if video["channel"] else None,
            "duration": video["duration"],
            "published_at": video["published_at"],
            "live_status": None,
            "view_count": video["view_count"],
            "existing": {"video_id": video["id"], "status": video["status"]},
        }
    cache = resolved_cache(request)
    info = await fetch_info(youtube, youtube_id, cache)
    cache[youtube_id] = (time.monotonic(), info)
    info = info or {}
    return {
        "youtube_id": youtube_id,
        "title": info.get("title"),
        "channel_name": info.get("channel") or info.get("uploader"),
        "duration": info.get("duration"),
        "published_at": published_at(info) if info else None,
        "live_status": info.get("live_status") if info else "is_upcoming",
        "view_count": info.get("view_count"),
        "existing": None,
    }


@router.post("", status_code=201)
async def add_video(
    body: AddVideo,
    request: Request,
    db: Database = Depends(get_db),
    runner: JobRunner = Depends(get_runner),
    youtube: YouTube = Depends(get_youtube),
):
    youtube_id = body.url
    existing = await db.fetch_one(f"{VIDEO_SELECT} WHERE v.youtube_id = ?", (youtube_id,))
    if existing and existing["status"] in ("archived", "queued", "downloading"):
        state = "archived" if existing["status"] == "archived" else "queued"
        raise HTTPException(
            status_code=409, detail=f"Already {state} in your library: {existing['title']}"
        )
    info = None if existing else await fetch_info(youtube, youtube_id, resolved_cache(request))
    options = body.model_dump(exclude={"url"}, exclude_none=True)
    async with db.transaction() as conn:
        if existing:
            video_id = existing["id"]
        elif info and info.get("id") == youtube_id:
            video_id, _ = await save_video_info(conn, info)
        else:
            cursor = await conn.execute(
                "INSERT INTO videos (youtube_id, title) VALUES (?, ?)", (youtube_id, youtube_id)
            )
            video_id = cursor.lastrowid
        await conn.execute("UPDATE videos SET deleted_at = NULL WHERE id = ?", (video_id,))
        await runner.enqueue("download", video_id=video_id, options=options, priority=10, conn=conn)
    return video_out(await load_video(db, video_id))


@router.post("/{video_id}/download")
async def download_video(
    video_id: int,
    body: VideoOptions | None = None,
    db: Database = Depends(get_db),
    runner: JobRunner = Depends(get_runner),
):
    video = await load_video(db, video_id)
    if video["status"] == "archived":
        raise HTTPException(status_code=409, detail="This video is already archived")
    options = body.model_dump(exclude_none=True) if body else {}
    async with db.transaction() as conn:
        await conn.execute("UPDATE videos SET deleted_at = NULL WHERE id = ?", (video_id,))
        job_id = await runner.enqueue(
            "download", video_id=video_id, options=options, priority=10, conn=conn
        )
    return {"job_id": job_id}


@router.delete("/{video_id}")
async def delete_video(
    video_id: int, db: Database = Depends(get_db), settings: Settings = Depends(get_settings)
):
    """Remove a video's local files: into the trash, or for good when trash_days is 0."""
    video = await load_video(db, video_id)
    if video["status"] in ("queued", "downloading"):
        raise HTTPException(status_code=409, detail="Cancel the download in the queue first")
    entry = None
    if video["media_path"]:
        days = await settings.get("trash_days")
        try:
            if days > 0:
                entry = await asyncio.to_thread(
                    trash.move_to_trash,
                    video["media_path"],
                    video["youtube_id"],
                    video["title"],
                    days,
                )
            else:
                await asyncio.to_thread(
                    layout.remove_media, video["media_path"], video["youtube_id"]
                )
        except (layout.PathError, trash.TrashError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
    await asyncio.to_thread(shutil.rmtree, layout.incomplete_dir(video["youtube_id"]), True)
    await db.execute(
        "UPDATE videos SET media_path = NULL, media_size = NULL, width = NULL, height = NULL, "
        "fps = NULL, vcodec = NULL, acodec = NULL, dynamic_range = NULL, audio_languages = NULL, "
        "subtitle_tracks = NULL, deleted_at = ?, updated_at = ? WHERE id = ?",
        (now(), now(), video_id),
    )
    return {"ok": True, "trash": {"expires_at": entry.expires_at} if entry else None}


@router.post("/{video_id}/restore")
async def restore_video(video_id: int, db: Database = Depends(get_db)):
    """Move a removed video's files back from the trash."""
    video = await load_video(db, video_id)
    if video["media_path"]:
        raise HTTPException(status_code=409, detail="This video already has its files")
    entry = await asyncio.to_thread(trash.latest, video["youtube_id"])
    if entry is None:
        raise HTTPException(status_code=404, detail="Nothing in the trash for this video")
    try:
        media = await asyncio.to_thread(trash.restore, entry)
    except (layout.PathError, trash.TrashError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    info = await asyncio.to_thread(sidecar.read_info, media)
    stat = await asyncio.to_thread(media.stat)
    async with db.transaction() as conn:
        if info.get("id") == video["youtube_id"]:
            await save_video_info(conn, info)
        await record_archived(
            conn,
            video_id,
            layout.relative(media),
            stat.st_size,
            info.get("width"),
            info.get("height"),
            archived_at=video["archived_at"] or from_timestamp(stat.st_mtime),
            facts=archive_facts(info) if info else None,
        )
    return {"ok": True}


@router.post("/{video_id}/watched")
async def set_watched(video_id: int, body: Watched, db: Database = Depends(get_db)):
    await load_video(db, video_id)
    await db.execute(
        "UPDATE videos SET watched_at = ? WHERE id = ?", (now() if body.watched else None, video_id)
    )
    return video_out(await load_video(db, video_id))


async def archived_media(db: Database, video_id: int):
    video = await db.fetch_one(
        "SELECT youtube_id, media_path FROM videos WHERE id = ?", (video_id,)
    )
    if not video or not video["media_path"]:
        raise not_found("Local video")
    try:
        media = layout.media_file(video["media_path"], video["youtube_id"])
    except layout.PathError as error:
        raise not_found("Local video") from error
    if not media.is_file():
        raise not_found("Local video file")
    return media


@router.api_route("/{video_id}/media", methods=["GET", "HEAD"])
async def media(video_id: int, db: Database = Depends(get_db)):
    path = await archived_media(db, video_id)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{video_id}/thumbnail")
async def thumbnail(video_id: int, db: Database = Depends(get_db)):
    path = layout.thumbnail_for(await archived_media(db, video_id))
    if path is None:
        raise not_found("Thumbnail")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


@router.get("/{video_id}/subtitles/{lang}")
async def subtitles(video_id: int, lang: str, db: Database = Depends(get_db)):
    path = layout.subtitles_for(await archived_media(db, video_id)).get(lang)
    if path is None:
        raise not_found("Subtitles")
    return FileResponse(path, media_type="text/vtt", headers={"Cache-Control": "private"})


def comment_page(media: Path, sort: str, page: int, per_page: int) -> tuple[list[Any], int]:
    comments = sidecar.read_info(media).get("comments")
    threads = sidecar.comment_threads(comments if isinstance(comments, list) else [], sort)
    start = (page - 1) * per_page
    return threads[start : start + per_page], len(threads)


@router.get("/{video_id}/comments")
async def comments(
    video_id: int,
    sort: Literal["top", "new"] = "top",
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Database = Depends(get_db),
):
    media = await archived_media(db, video_id)
    items, total = await asyncio.to_thread(comment_page, media, sort, page, per_page)
    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/{video_id}/chat")
async def chat(
    video_id: int,
    since: float | None = Query(None, ge=0),
    until: float | None = Query(None, ge=0),
    db: Database = Depends(get_db),
):
    """The saved chat replay; `since` and `until` (seconds) limit it to a stretch of the video."""
    path = layout.chat_for(await archived_media(db, video_id))
    if path is None:
        raise not_found("Chat replay")
    return {"items": await asyncio.to_thread(sidecar.chat_window, path, since, until)}
