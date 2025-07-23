"""
YouTube downloader using yt-dlp
"""
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, Callable
import json
import yt_dlp
from datetime import datetime

from app.core.config import settings
from app.core.database import Database


class DownloadProgress:
    """Track download progress"""
    def __init__(self, video_id: int, callback: Optional[Callable] = None):
        self.video_id = video_id
        self.callback = callback
        self.status = "pending"
        self.progress = 0.0
        self.speed = None
        self.eta = None
        self.error = None
    
    def update(self, d: dict):
        """Update progress from yt-dlp hook"""
        if d['status'] == 'downloading':
            self.status = 'downloading'
            if d.get('total_bytes'):
                self.progress = (d.get('downloaded_bytes', 0) / d['total_bytes']) * 100
            elif d.get('total_bytes_estimate'):
                self.progress = (d.get('downloaded_bytes', 0) / d['total_bytes_estimate']) * 100
            self.speed = d.get('speed')
            self.eta = d.get('eta')
        elif d['status'] == 'finished':
            self.status = 'completed'
            self.progress = 100.0
        elif d['status'] == 'error':
            self.status = 'failed'
            self.error = str(d.get('error', 'Unknown error'))
        
        if self.callback:
            self.callback(self)


class Downloader:
    """YouTube video downloader"""
    
    def __init__(self, db: Database):
        self.db = db
        self.active_downloads = {}
        self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_DOWNLOADS)
    
    def get_ydl_opts(self, output_path: Path, progress_hook: Optional[Callable] = None) -> dict:
        """Get yt-dlp options"""
        opts = {
            'format': settings.FORMAT_SELECTOR,
            'outtmpl': str(output_path / 'video.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'writeinfojson': settings.WRITE_INFO_JSON,
            'writethumbnail': settings.WRITE_THUMBNAIL,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': settings.SUBTITLE_LANGUAGES,
            'postprocessors': []
        }
        
        if settings.EMBED_SUBS:
            opts['postprocessors'].append({
                'key': 'FFmpegEmbedSubtitle',
                'already_have_subtitle': False
            })
        
        if progress_hook:
            opts['progress_hooks'] = [progress_hook]
        
        return opts
    
    async def extract_info(self, url: str) -> Dict[str, Any]:
        """Extract video/channel info without downloading"""
        loop = asyncio.get_event_loop()
        
        def _extract():
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': False}) as ydl:
                return ydl.extract_info(url, download=False)
        
        return await loop.run_in_executor(None, _extract)
    
    async def download_video(self, video_id: int, url: str, output_dir: Path) -> bool:
        """Download a video"""
        async with self._semaphore:
            progress = DownloadProgress(video_id, self._update_progress_db)
            self.active_downloads[video_id] = progress
            
            try:
                # Update status to downloading
                await self.db.update(
                    "download_queue",
                    {"status": "downloading", "started_at": datetime.utcnow().isoformat()},
                    "video_id = ?",
                    (video_id,)
                )
                
                # Create progress hook
                def progress_hook(d):
                    progress.update(d)
                
                # Download in thread pool
                loop = asyncio.get_event_loop()
                opts = self.get_ydl_opts(output_dir, progress_hook)
                
                def _download():
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                
                await loop.run_in_executor(None, _download)
                
                # Update video record
                await self.db.update(
                    "videos",
                    {
                        "download_status": "completed",
                        "file_path": str(output_dir.relative_to(settings.get_storage_path())),
                        "updated_at": datetime.utcnow().isoformat()
                    },
                    "id = ?",
                    (video_id,)
                )
                
                # Update queue
                await self.db.update(
                    "download_queue",
                    {
                        "status": "completed",
                        "progress": 100.0,
                        "completed_at": datetime.utcnow().isoformat()
                    },
                    "video_id = ?",
                    (video_id,)
                )
                
                return True
                
            except Exception as e:
                # Update error status
                await self.db.update(
                    "videos",
                    {"download_status": "failed"},
                    "id = ?",
                    (video_id,)
                )
                
                await self.db.update(
                    "download_queue",
                    {
                        "status": "failed",
                        "error_message": str(e)
                    },
                    "video_id = ?",
                    (video_id,)
                )
                
                return False
                
            finally:
                del self.active_downloads[video_id]
    
    async def _update_progress_db(self, progress: DownloadProgress):
        """Update download progress in database"""
        await self.db.update(
            "download_queue",
            {"progress": progress.progress},
            "video_id = ?",
            (progress.video_id,)
        )
    
    async def queue_download(self, video_id: int, priority: int = 0) -> int:
        """Add video to download queue"""
        queue_id = await self.db.insert("download_queue", {
            "video_id": video_id,
            "priority": priority,
            "status": "queued",
            "progress": 0.0
        })
        
        # Start download task
        asyncio.create_task(self._process_download(video_id))
        
        return queue_id
    
    async def _process_download(self, video_id: int):
        """Process a queued download"""
        # Get video info
        video = await self.db.execute_one(
            """SELECT v.*, c.youtube_id as channel_youtube_id, c.name as channel_name
               FROM videos v
               JOIN channels c ON v.channel_id = c.id
               WHERE v.id = ?""",
            (video_id,)
        )
        
        if not video:
            return
        
        # Create output directory
        channel_path = settings.get_channel_path(
            video['channel_youtube_id'],
            video['channel_name']
        )
        
        safe_title = "".join(c for c in video['title'] if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_title = safe_title.replace(' ', '_')[:100]
        video_dir = channel_path / f"{video['youtube_id']}_{safe_title}"
        video_dir.mkdir(parents=True, exist_ok=True)
        
        # Download
        url = f"https://www.youtube.com/watch?v={video['youtube_id']}"
        await self.download_video(video_id, url, video_dir)
    
    def get_active_downloads(self) -> Dict[int, DownloadProgress]:
        """Get current active downloads"""
        return self.active_downloads.copy() 