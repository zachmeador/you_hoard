"""A small, persistent SQLite job queue shared by the API and scheduler."""

import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings
from app.core.database import Database
from app.core.library import save_video
from app.core.metadata import MetadataManager, classify_video_type
from app.core.quality import QualityService
from app.core.storage import VIDEO_EXTENSIONS, video_directory
from app.core.ytdlp_service import get_ytdlp_service

logger = logging.getLogger(__name__)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DownloadProgress:
    def __init__(self, video_id: int) -> None:
        self.video_id = video_id
        self.progress = 0.0
        self.speed = None
        self.eta = None
        self.status = "downloading"

    def update(self, data: dict[str, Any]) -> None:
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        if total:
            self.progress = min(100, data.get("downloaded_bytes", 0) / total * 100)
        self.speed = data.get("speed")
        self.eta = data.get("eta")
        # A finished stream is not a completed archive: merging may still fail.
        if data["status"] == "finished":
            self.status = "processing"


class Downloader:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.active_downloads: dict[int, DownloadProgress] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._wake = asyncio.Event()
        self._stopping = False

    async def start(self) -> None:
        if self._workers:
            return
        # Interrupted transfers retain their .part files for yt-dlp to resume.
        async with self.db.get_db() as conn:
            await conn.execute(
                "UPDATE job_queue SET status = 'queued', progress = 0, started_at = NULL "
                "WHERE status IN ('downloading', 'processing')"
            )
            await conn.execute(
                "UPDATE videos SET download_status = 'pending' WHERE download_status = 'downloading'"
            )
            await conn.execute(
                """UPDATE job_queue SET status = 'failed',
                   error_message = 'Superseded by an earlier job for the same source', completed_at = ?
                   WHERE id IN (
                       SELECT id FROM (
                           SELECT id, ROW_NUMBER() OVER (
                               PARTITION BY job_type, video_id, subscription_id ORDER BY id
                           ) AS sequence
                           FROM job_queue
                           WHERE status IN ('queued', 'paused')
                           AND job_type IN ('download', 'subscription_discovery')
                       ) WHERE sequence > 1
                   )""",
                (now(),),
            )
            await conn.execute(
                "UPDATE scheduler_events SET event_type = 'check_failed', status = 'failed', "
                "error_message = 'Server stopped before this check finished', completed_at = ? "
                "WHERE event_type = 'check_started'",
                (now(),),
            )
            await conn.commit()
        self._stopping = False
        self._workers = [
            asyncio.create_task(self._worker())
            for _ in range(max(1, settings.MAX_CONCURRENT_DOWNLOADS))
        ]

    async def stop(self) -> None:
        # Cancelling an asyncio task cannot stop a yt-dlp thread writing to disk.
        self._stopping = True
        self._wake.set()
        await asyncio.gather(*self._workers)
        self._workers = []

    async def _enqueue(
        self,
        job_type: str,
        *,
        video_id=None,
        subscription_id=None,
        video_url=None,
        priority=0,
        quality=None,
        options=None,
    ) -> int:
        async with self.db.get_db() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            if video_id is not None or subscription_id is not None:
                key, value = (
                    ("video_id", video_id)
                    if video_id is not None
                    else ("subscription_id", subscription_id)
                )
                cursor = await conn.execute(
                    f"SELECT id FROM job_queue WHERE job_type = ? AND {key} = ? "
                    "AND status IN ('queued', 'downloading', 'processing', 'paused') ORDER BY id LIMIT 1",
                    (job_type, value),
                )
                existing = await cursor.fetchone()
                if existing:
                    return existing["id"]
            if video_id is not None:
                cursor = await conn.execute(
                    "SELECT download_status FROM videos WHERE id = ?", (video_id,)
                )
                video = await cursor.fetchone()
                if not video:
                    raise ValueError("Video not found")
                if video["download_status"] == "completed":
                    raise ValueError("Video is already downloaded")
                await conn.execute(
                    "UPDATE videos SET download_status = 'pending' WHERE id = ?", (video_id,)
                )
            cursor = await conn.execute(
                """INSERT INTO job_queue (job_type, video_id, subscription_id, video_url,
                   priority, quality, result_data) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_type,
                    video_id,
                    subscription_id,
                    video_url,
                    priority,
                    quality,
                    json.dumps(options) if options is not None else None,
                ),
            )
            await conn.commit()
            queue_id = cursor.lastrowid
        self._wake.set()
        return queue_id

    async def queue_download(
        self,
        video_id: int,
        priority: int = 0,
        quality: Optional[str] = None,
        options: Optional[dict] = None,
    ) -> int:
        if quality is not None and not QualityService.validate_quality(quality):
            raise ValueError(f"Unsupported quality: {quality}")
        quality = await QualityService.resolve_quality_preference(self.db, video_quality=quality)
        return await self._enqueue(
            "download", video_id=video_id, priority=priority, quality=quality, options=options
        )

    async def queue_subscription_discovery(self, subscription_id: int, priority: int = 0) -> int:
        return await self._enqueue(
            "subscription_discovery", subscription_id=subscription_id, priority=priority
        )

    async def queue_video_metadata_extraction(self, video_url: str, priority: int = 0) -> int:
        return await self._enqueue(
            "video_metadata_extraction", video_url=video_url, priority=priority
        )

    def notify_queue_changed(self) -> None:
        self._wake.set()

    async def _claim_job(self) -> dict[str, Any] | None:
        async with self.db.get_db() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cursor = await conn.execute(
                "SELECT * FROM job_queue WHERE status = 'queued' ORDER BY priority DESC, id LIMIT 1"
            )
            row = await cursor.fetchone()
            if not row:
                return None
            job = dict(row)
            state = "downloading" if job["job_type"] == "download" else "processing"
            await conn.execute(
                "UPDATE job_queue SET status = ?, started_at = ? WHERE id = ?",
                (state, now(), job["id"]),
            )
            await conn.commit()
            return job

    async def _worker(self) -> None:
        while not self._stopping:
            try:
                job = await self._claim_job()
                if job:
                    await self._process_job(job)
                else:
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), timeout=1)
                    except asyncio.TimeoutError:
                        pass
            except Exception:
                logger.exception("Queue worker error")
                await asyncio.sleep(1)

    async def _process_job(self, job: dict[str, Any]) -> None:
        event_id = None
        started = datetime.now(timezone.utc)
        try:
            if job["job_type"] == "subscription_discovery":
                event_id = await self.db.insert(
                    "scheduler_events",
                    {
                        "subscription_id": job["subscription_id"],
                        "event_type": "check_started",
                    },
                )
                result = await self._discover(job)
            elif job["job_type"] == "download":
                result = await self._download(job)
            elif job["job_type"] == "video_metadata_extraction":
                result = {"video_info": await self.extract_info(job["video_url"])}
            else:
                raise ValueError(f"Unknown job type: {job['job_type']}")
            await self.db.update(
                "job_queue",
                {
                    "status": "completed",
                    "progress": 100,
                    "completed_at": now(),
                    "error_message": None,
                    "result_data": json.dumps(result),
                },
                "id = ?",
                (job["id"],),
            )
            if event_id:
                await self.db.update(
                    "scheduler_events",
                    {
                        "event_type": "check_completed",
                        "status": "partial_success" if result["errors"] else "success",
                        "videos_found": result["videos_found"],
                        "videos_added": result["videos_added"],
                        "videos_queued": result["videos_queued"],
                        "videos_filtered": result["videos_filtered"],
                        "error_count": len(result["errors"]),
                        "error_message": "\n".join(result["errors"]) or None,
                        "completed_at": now(),
                        "duration_ms": int(
                            (datetime.now(timezone.utc) - started).total_seconds() * 1000
                        ),
                    },
                    "id = ?",
                    (event_id,),
                )
        except Exception as error:
            logger.exception("Job %s failed", job["id"])
            await self.db.update(
                "job_queue",
                {
                    "status": "failed",
                    "error_message": str(error),
                    "completed_at": now(),
                },
                "id = ?",
                (job["id"],),
            )
            if job["job_type"] == "download":
                await self.db.update(
                    "videos", {"download_status": "failed"}, "id = ?", (job["video_id"],)
                )
            if event_id:
                await self.db.update(
                    "scheduler_events",
                    {
                        "event_type": "check_failed",
                        "status": "failed",
                        "error_message": str(error),
                        "completed_at": now(),
                    },
                    "id = ?",
                    (event_id,),
                )

    async def extract_info(self, url: str) -> dict:
        return await get_ytdlp_service().extract_info(url, {"noplaylist": True, "playlistend": 1})

    def get_ydl_opts(
        self,
        output_path: Path,
        quality: str,
        progress_hook=None,
        preferences: Optional[dict] = None,
    ) -> dict:
        preferences = preferences or {}
        languages = preferences.get("subtitle_languages")
        if languages is None:
            languages = settings.SUBTITLE_LANGUAGES
        opts = {
            "format": QualityService.get_format_selector(quality),
            "outtmpl": {
                "default": str(output_path / "video.%(ext)s"),
                "thumbnail": str(output_path / "thumbnail.%(ext)s"),
            },
            "writeinfojson": True,
            "writethumbnail": settings.WRITE_THUMBNAIL,
            "writesubtitles": bool(languages),
            "writeautomaticsub": bool(languages),
            "subtitleslangs": languages,
            "getcomments": preferences.get("download_comments", False),
            "merge_output_format": settings.MERGE_OUTPUT_FORMAT,
            "format_sort": settings.FORMAT_SORT,
            "postprocessors": [
                {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"},
                {"key": "FFmpegVideoRemuxer", "preferedformat": settings.REMUX_VIDEO},
            ],
        }
        if settings.EMBED_SUBS and languages:
            opts["postprocessors"].append({"key": "FFmpegEmbedSubtitle"})
        if progress_hook:
            opts["progress_hooks"] = [progress_hook]
        return opts

    async def _download(self, job: dict) -> dict:
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg is required. Install it and retry this download.")
        video = await self.db.execute_one(
            """SELECT v.*, c.youtube_id AS channel_youtube_id, c.name AS channel_name
               FROM videos v JOIN channels c ON c.id = v.channel_id WHERE v.id = ?""",
            (job["video_id"],),
        )
        if not video:
            raise ValueError("Video not found")
        if video["download_status"] == "completed":
            return {"message": "Already downloaded; skipped duplicate job"}
        directory = video_directory(
            video["channel_youtube_id"], video["channel_name"], video["youtube_id"], video["title"]
        )
        progress = DownloadProgress(video["id"])
        self.active_downloads[video["id"]] = progress
        await self.db.update("videos", {"download_status": "downloading"}, "id = ?", (video["id"],))
        try:
            quality = job.get("quality") or settings.DEFAULT_QUALITY
            preferences = Database.json_decode(job.get("result_data")) or {}
            await get_ytdlp_service().download_with_progress(
                f"https://www.youtube.com/watch?v={video['youtube_id']}",
                directory,
                progress.update,
                self.get_ydl_opts(directory, quality, progress.update, preferences),
            )
            media = next(
                (
                    p
                    for p in sorted(directory.iterdir())
                    if p.is_file() and p.stem == "video" and p.suffix in VIDEO_EXTENSIONS
                ),
                None,
            )
            if not media or not media.stat().st_size:
                raise RuntimeError("yt-dlp finished without producing a video file")
            info_path = directory / "video.info.json"
            info = json.loads(info_path.read_text()) if info_path.exists() else {}
            thumbnail = MetadataManager._find_thumbnail_file(directory)
            root = settings.get_storage_path()
            await self.db.update(
                "videos",
                {
                    "download_status": "completed",
                    "file_path": str(media.relative_to(root)),
                    "file_size": media.stat().st_size,
                    "quality": QualityService.extract_quality_from_metadata(info),
                    "thumbnail_path": str(thumbnail.relative_to(root)) if thumbnail else None,
                    "thumbnail_generated": False,
                },
                "id = ?",
                (video["id"],),
            )
            if info:
                MetadataManager.save_metadata(
                    MetadataManager.parse_from_ytdlp(info, directory, root), directory
                )
            return {"file_path": str(media.relative_to(root)), "file_size": media.stat().st_size}
        finally:
            self.active_downloads.pop(video["id"], None)

    async def _discover(self, job: dict) -> dict:
        sub = await self.db.execute_one(
            "SELECT * FROM subscriptions WHERE id = ?", (job["subscription_id"],)
        )
        if not sub:
            raise ValueError("Subscription not found")
        wanted = Database.json_decode(sub["content_types"]) or ["video"]
        limit = sub["latest_n_videos"]
        source = sub["source_url"].rstrip("/")
        if sub["subscription_type"] == "channel":
            # Explicit tabs avoid a channel root yielding playlists of playlists.
            source = source.removesuffix("/videos").removesuffix("/shorts").removesuffix("/streams")
            tabs = {"video": "videos", "short": "shorts", "live": "streams"}
            sources = [(f"{source}/{tabs[kind]}", kind) for kind in wanted]
        else:
            sources = [(source, None)]
        result = {
            "videos_found": 0,
            "videos_added": 0,
            "videos_queued": 0,
            "videos_filtered": 0,
            "new_videos": [],
            "errors": [],
        }
        seen = set()
        for url, kind in sources:
            info = await get_ytdlp_service().extract_info(
                url,
                {
                    "extract_flat": "in_playlist",
                    "playlistend": limit,
                    "noplaylist": False,
                    "ignoreerrors": True,
                },
            )
            for entry in (info.get("entries") or [])[:limit]:
                if not entry or not entry.get("id") or entry["id"] in seen:
                    continue
                youtube_id = entry["id"]
                seen.add(youtube_id)
                result["videos_found"] += 1
                try:
                    existing = await self.db.execute_one(
                        "SELECT * FROM videos WHERE youtube_id = ?", (youtube_id,)
                    )
                    if existing:
                        video_id = existing["id"]
                        video_type = kind or existing["video_type"]
                        if video_type != existing["video_type"]:
                            await self.db.update(
                                "videos", {"video_type": video_type}, "id = ?", (video_id,)
                            )
                    else:
                        # Playlists may contain many uploaders. Resolve each video's own channel.
                        full = await self.extract_info(
                            f"https://www.youtube.com/watch?v={youtube_id}"
                        )
                        if full.get("live_status") in ("is_live", "is_upcoming", "post_live"):
                            result["videos_filtered"] += 1
                            continue
                        if kind == "short":
                            full["webpage_url"] = f"https://www.youtube.com/shorts/{youtube_id}"
                        video_type = kind or classify_video_type(full)
                        if video_type not in wanted:
                            result["videos_filtered"] += 1
                            continue
                        video_id, created = await save_video(self.db, full, video_type=video_type)
                        if created:
                            result["videos_added"] += 1
                            result["new_videos"].append(
                                {"youtube_id": youtube_id, "title": full.get("title")}
                            )
                    if video_type not in wanted:
                        result["videos_filtered"] += 1
                        continue
                    if sub["auto_download"] and (
                        not existing or existing["download_status"] == "pending"
                    ):
                        await self.queue_download(
                            video_id,
                            priority=1,
                            quality=sub["quality_preference"],
                            options={
                                "download_comments": bool(sub["download_comments"]),
                                "subtitle_languages": Database.json_decode(
                                    sub["subtitle_languages"]
                                ),
                            },
                        )
                        result["videos_queued"] += 1
                except Exception as error:
                    result["errors"].append(f"{youtube_id}: {error}")
                await self.db.update(
                    "job_queue",
                    {
                        "videos_found": result["videos_found"],
                        "videos_processed": result["videos_added"],
                    },
                    "id = ?",
                    (job["id"],),
                )
        await self.db.update(
            "subscriptions",
            {
                "last_check": now(),
                "new_videos_count": result["videos_added"],
            },
            "id = ?",
            (sub["id"],),
        )
        return result

    def get_active_downloads(self) -> dict[int, DownloadProgress]:
        return self.active_downloads.copy()
