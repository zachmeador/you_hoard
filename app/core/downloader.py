"""
YouTube downloader using yt-dlp
"""
import asyncio
import json
from pathlib import Path
from typing import Optional, Dict, Any, Callable
import yt_dlp
from datetime import datetime

from app.core.config import settings
from app.core.database import Database
from app.core.metadata import MetadataManager
from app.core.quality import QualityService
from app.core.ytdlp_service import get_ytdlp_service


class DownloadProgress:
    """Track download progress"""
    def __init__(self, video_id: int, loop: asyncio.AbstractEventLoop, callback: Optional[Callable] = None):
        self.video_id = video_id
        self.callback = callback
        self.loop = loop
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
            # Schedule the async callback on the event loop
            if asyncio.iscoroutinefunction(self.callback):
                asyncio.run_coroutine_threadsafe(self.callback(self), self.loop)
            else:
                self.callback(self)


class Downloader:
    """Unified job processor for downloads, subscription discovery, and metadata extraction"""
    
    def __init__(self, db: Database):
        self.db = db
        self.active_downloads = {}  # Keep this name for backward compatibility  
        self.active_tasks = {}  # New: track asyncio.Tasks for cancellation
        self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_DOWNLOADS)
    
    def get_ydl_opts(self, output_path: Path, quality: Optional[str] = None, progress_hook: Optional[Callable] = None) -> dict:
        """Get yt-dlp options"""
        import shutil
        
        # Use provided quality or fall back to default
        format_selector = settings.FORMAT_SELECTOR
        if quality:
            format_selector = QualityService.get_format_selector(quality)
            
        opts = {
            'format': format_selector,
            'outtmpl': {
                'default': str(output_path / 'video.%(ext)s'),
                'thumbnail': str(output_path / 'thumbnail.%(ext)s'),
            },
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'writeinfojson': settings.WRITE_INFO_JSON,
            'writethumbnail': settings.WRITE_THUMBNAIL,
            'write_subs': True,
            'write_auto_subs': True,
            'sub_langs': settings.SUBTITLE_LANGUAGES,
            'postprocessors': [],
            # Format compatibility settings
            'merge_output_format': settings.MERGE_OUTPUT_FORMAT,
            'remux_video': settings.REMUX_VIDEO,
            'format_sort': settings.FORMAT_SORT
        }
        
        # Explicitly set ffmpeg path if found
        ffmpeg_path = shutil.which('ffmpeg')
        if ffmpeg_path:
            opts['ffmpeg_location'] = ffmpeg_path
        
        if settings.EMBED_SUBS:
            opts['postprocessors'].append({
                'key': 'FFmpegEmbedSubtitle',
                'already_have_subtitle': False
            })
        
        # Convert thumbnails to JPG format
        opts['postprocessors'].append({
            'key': 'FFmpegThumbnailsConvertor',
            'format': 'jpg',
            'when': 'before_dl'
        })
        
        if progress_hook:
            opts['progress_hooks'] = [progress_hook]
        
        return opts
    
    async def extract_info(self, url: str) -> Dict[str, Any]:
        """Extract video/channel info without downloading"""
        ytdlp_service = get_ytdlp_service()
        config = {'playlistend': settings.PLAYLIST_BATCH_SIZE}  # Limit extraction to batch size
        return await ytdlp_service.extract_info(url, extra_config=config)
    
    async def download_video(self, video_id: int, url: str, output_dir: Path, quality: Optional[str] = None) -> bool:
        """Download a video"""
        async with self._semaphore:
            loop = asyncio.get_event_loop()
            progress = DownloadProgress(video_id, loop, self._update_progress_db_async)
            self.active_downloads[video_id] = progress
            
            try:
                # Update status to downloading
                await self.db.update(
                    "job_queue",
                    {"status": "downloading", "started_at": datetime.utcnow().isoformat()},
                    "video_id = ?",
                    (video_id,)
                )
                
                # Create progress hook
                def progress_hook(d):
                    progress.update(d)
                
                # Download using centralized YTDLPService
                ytdlp_service = get_ytdlp_service()
                opts = self.get_ydl_opts(output_dir, quality, progress_hook)
                
                await ytdlp_service.download_with_progress(
                    url=url,
                    output_path=output_dir,
                    progress_callback=progress_hook,
                    extra_config=opts
                )
                
                # Process thumbnails after successful download
                thumbnail_path = None
                try:
                    thumbnail_path = await self._find_existing_thumbnails(output_dir)
                except Exception as e:
                    # Don't fail the download if thumbnail processing fails
                    print(f"Thumbnail processing error: {e}")
                
                # Create app metadata from yt-dlp info.json
                try:
                    await self._create_app_metadata(output_dir)
                except Exception as e:
                    # Don't fail the download if metadata creation fails
                    print(f"App metadata creation error: {e}")
                
                # Extract actual quality from downloaded video info
                actual_quality = None
                try:
                    info_file = output_dir / "video.info.json"
                    if not info_file.exists():
                        info_file = output_dir / "info.json"
                    
                    if info_file.exists():
                        import json
                        with open(info_file, 'r', encoding='utf-8') as f:
                            info_data = json.load(f)
                            actual_quality = QualityService.extract_quality_from_metadata(info_data)
                except Exception as e:
                    print(f"Quality extraction error: {e}")
                
                # Update video record
                video_update = {
                    "download_status": "completed",
                    "file_path": str(output_dir.relative_to(settings.get_storage_path())),
                    "updated_at": datetime.utcnow().isoformat()
                }
                
                if actual_quality:
                    video_update["quality"] = actual_quality
                
                if thumbnail_path:
                    video_update["thumbnail_path"] = thumbnail_path
                    video_update["thumbnail_generated"] = True
                
                await self.db.update(
                    "videos",
                    video_update,
                    "id = ?",
                    (video_id,)
                )
                
                # Update queue
                await self.db.update(
                    "job_queue",
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
                    "job_queue",
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
    
    async def _update_progress_db_async(self, progress: DownloadProgress):
        """Update download progress in database"""
        try:
            await self.db.update(
                "job_queue",
                {"progress": progress.progress},
                "video_id = ?",
                (progress.video_id,)
            )
        except Exception as e:
            # Don't let progress update errors crash the download
            print(f"Progress update error: {e}")
    
    async def queue_download(self, video_id: int, priority: int = 0, quality: Optional[str] = None) -> int:
        """Add video download job to the unified job queue"""
        queue_id = await self.db.insert("job_queue", {
            "job_type": "download",
            "video_id": video_id,
            "priority": priority,
            "quality": quality,
            "status": "queued",
            "progress": 0.0
        })
        
        # Start download task and track it
        task = asyncio.create_task(self._process_job(queue_id))
        self.active_tasks[queue_id] = task
        
        return queue_id
        
    async def queue_subscription_discovery(self, subscription_id: int, priority: int = 0) -> int:
        """Queue a subscription discovery job"""
        queue_id = await self.db.insert("job_queue", {
            "job_type": "subscription_discovery",
            "subscription_id": subscription_id,
            "priority": priority,
            "status": "queued",
            "progress": 0.0
        })
        
        # Start processing task and track it
        task = asyncio.create_task(self._process_job(queue_id))
        self.active_tasks[queue_id] = task
        
        return queue_id
        
    async def queue_video_metadata_extraction(self, video_url: str, priority: int = 0) -> int:
        """Queue a video metadata extraction job"""
        queue_id = await self.db.insert("job_queue", {
            "job_type": "video_metadata_extraction", 
            "video_url": video_url,
            "priority": priority,
            "status": "queued",
            "progress": 0.0
        })
        
        # Start processing task and track it
        task = asyncio.create_task(self._process_job(queue_id))
        self.active_tasks[queue_id] = task
        
        return queue_id
    
    async def _process_job(self, queue_id: int):
        """Process a queued job (download, subscription discovery, etc.)"""
        # Get job info
        job = await self.db.execute_one(
            "SELECT * FROM job_queue WHERE id = ? AND status IN ('queued', 'downloading', 'processing')",
            (queue_id,)
        )
        
        if not job:
            return
            
        job_type = job['job_type']
        
        try:
            if job_type == 'download':
                await self._process_download_job(job)
            elif job_type == 'subscription_discovery':
                await self._process_subscription_discovery_job(job)
            elif job_type == 'video_metadata_extraction':
                await self._process_metadata_extraction_job(job)
            else:
                raise ValueError(f"Unknown job type: {job_type}")
        except Exception as e:
            logger.error(f"Job {queue_id} ({job_type}) failed: {e}")
            await self.db.update(
                "job_queue",
                {
                    "status": "failed",
                    "error_message": str(e),
                    "completed_at": datetime.utcnow().isoformat()
                },
                "id = ?",
                (queue_id,)
            )
        finally:
            # Clean up task tracking
            if queue_id in self.active_tasks:
                del self.active_tasks[queue_id]
    
    async def _process_download_job(self, job: Dict[str, Any]):
        """Process a download job"""
        video_id = job['video_id']
        
        # Get video and download queue info
        video = await self.db.execute_one(
            """SELECT v.*, c.youtube_id as channel_youtube_id, c.name as channel_name
               FROM videos v
               JOIN channels c ON v.channel_id = c.id
               WHERE v.id = ?""",
            (video_id,)
        )
        
        if not video:
            raise ValueError(f"Video {video_id} not found")
        
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
        await self.download_video(video_id, url, video_dir, job.get('quality'))
    
    async def _process_subscription_discovery_job(self, job: Dict[str, Any]):
        """Process a subscription discovery job"""
        subscription_id = job['subscription_id']
        queue_id = job['id']
        
        # Update status to processing
        await self.db.update(
            "job_queue",
            {
                "status": "processing",
                "started_at": datetime.utcnow().isoformat()
            },
            "id = ?",
            (queue_id,)
        )
        
        # Get subscription details
        subscription = await self.db.execute_one(
            """SELECT s.*, c.youtube_id as channel_youtube_id 
               FROM subscriptions s 
               JOIN channels c ON s.channel_id = c.id 
               WHERE s.id = ?""",
            (subscription_id,)
        )
        
        if not subscription:
            raise ValueError(f"Subscription {subscription_id} not found")
            
        logger.info(f"Processing subscription discovery for {subscription['source_url']}")
        
        # Import the classification function
        from app.api.endpoints.videos import classify_video_type
        
        # Extract video list using ytdlp
        ytdlp_service = get_ytdlp_service()
        
        try:
            info = await ytdlp_service.extract_info(subscription['source_url'])
        except Exception as e:
            raise Exception(f"Failed to extract info from {subscription['source_url']}: {e}")
            
        # Handle different info structures
        entries = []
        if info.get('_type') == 'playlist' or 'entries' in info:
            entries = info.get('entries', [])
        elif info.get('id'):  # Single video
            entries = [info]
            
        if not entries:
            logger.warning(f"No entries found for subscription {subscription_id}")
            await self.db.update(
                "job_queue",
                {
                    "status": "completed",
                    "progress": 100.0,
                    "videos_found": 0,
                    "videos_processed": 0,
                    "completed_at": datetime.utcnow().isoformat()
                },
                "id = ?",
                (queue_id,)
            )
            return
            
        # Update progress - found videos
        await self.db.update(
            "job_queue",
            {
                "progress": 10.0,
                "videos_found": len(entries)
            },
            "id = ?",
            (queue_id,)
        )
        
        # Get subscription preferences
        desired_count = subscription.get('latest_n_videos', 20)
        subscription_content_types = Database.json_decode(subscription.get('content_types', '["video"]'))
        
        # Filter and process videos
        matched_videos = []
        for i, entry in enumerate(entries[:desired_count * 2]):  # Process more to find matches
            if not entry or not entry.get('id'):
                continue
                
            video_id = entry.get('id')
            video_type = classify_video_type(entry)
            
            # Check if this video type is wanted
            if video_type not in subscription_content_types:
                continue
                
            # Check if video already exists
            existing = await self.db.execute_one(
                "SELECT id FROM videos WHERE youtube_id = ?",
                (video_id,)
            )
            
            if not existing:
                matched_videos.append({
                    'entry': entry,
                    'video_id': video_id,
                    'video_type': video_type
                })
                
            # Update progress
            progress_pct = 10.0 + (i / len(entries)) * 40.0
            await self.db.update(
                "job_queue",
                {"progress": progress_pct},
                "id = ?",
                (queue_id,)
            )
            
            if len(matched_videos) >= desired_count:
                break
                
        logger.info(f"Found {len(matched_videos)} new videos for subscription {subscription_id}")
        
        # Process matched videos
        new_videos = []
        errors = []
        
        for i, video_data in enumerate(matched_videos):
            entry = video_data['entry']
            video_id = video_data['video_id']
            video_type = video_data['video_type']
            
            try:
                # Create video record
                video_db_id = await self.db.insert("videos", {
                    "youtube_id": video_id,
                    "channel_id": subscription['channel_id'],
                    "title": entry.get('title', 'Unknown Title'),
                    "description": entry.get('description'),
                    "duration": entry.get('duration'),
                    "upload_date": entry.get('upload_date'),
                    "video_type": video_type,
                    "download_status": "pending",
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat()
                })
                
                # Auto-queue for download if enabled
                if subscription.get('auto_download', True):
                    try:
                        await self.queue_download(
                            video_db_id,
                            priority=1,  # Subscription videos get priority 1
                            quality=subscription.get('quality_preference', '720p')
                        )
                    except Exception as e:
                        errors.append(f"Failed to queue video {video_id}: {str(e)}")
                        
                new_videos.append({
                    "youtube_id": video_id,
                    "title": entry.get('title')
                })
                
                # Update progress
                progress_pct = 50.0 + (i / len(matched_videos)) * 50.0
                await self.db.update(
                    "job_queue",
                    {
                        "progress": progress_pct,
                        "videos_processed": len(new_videos)
                    },
                    "id = ?",
                    (queue_id,)
                )
                
            except Exception as e:
                error_msg = f"Failed to add video {video_id}: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
                
        # Update subscription stats
        await self.db.update(
            "subscriptions",
            {
                "last_check": datetime.utcnow().isoformat(),
                "new_videos_count": len(new_videos)
            },
            "id = ?",
            (subscription_id,)
        )
        
        # Store results and mark completed
        result_data = {
            "new_videos": new_videos,
            "errors": errors,
            "total_entries": len(entries),
            "matched_videos": len(matched_videos),
            "processed_videos": len(new_videos)
        }
        
        await self.db.update(
            "job_queue",
            {
                "status": "completed",
                "progress": 100.0,
                "videos_found": len(entries),
                "videos_processed": len(new_videos),
                "result_data": Database.json_encode(result_data),
                "completed_at": datetime.utcnow().isoformat()
            },
            "id = ?",
            (queue_id,)
        )
        
        logger.info(f"Subscription discovery completed: {len(new_videos)} new videos added")
    
    async def _process_metadata_extraction_job(self, job: Dict[str, Any]):
        """Process a video metadata extraction job"""
        video_url = job['video_url']
        queue_id = job['id']
        
        # Update status to processing
        await self.db.update(
            "job_queue",
            {
                "status": "processing",
                "started_at": datetime.utcnow().isoformat()
            },
            "id = ?",
            (queue_id,)
        )
        
        logger.info(f"Processing video metadata extraction for {video_url}")
        
        # Extract metadata using ytdlp
        ytdlp_service = get_ytdlp_service()
        
        try:
            info = await ytdlp_service.extract_info(video_url)
            
            # Store results and mark completed
            result_data = {
                "video_info": info,
                "extracted_at": datetime.utcnow().isoformat()
            }
            
            await self.db.update(
                "job_queue",
                {
                    "status": "completed",
                    "progress": 100.0,
                    "videos_found": 1,
                    "videos_processed": 1,
                    "result_data": Database.json_encode(result_data),
                    "completed_at": datetime.utcnow().isoformat()
                },
                "id = ?",
                (queue_id,)
            )
            
        except Exception as e:
            raise Exception(f"Failed to extract metadata from {video_url}: {e}")
    
    def get_active_downloads(self) -> Dict[int, DownloadProgress]:
        """Get current active downloads and jobs"""
        return self.active_downloads.copy() 

    async def _find_existing_thumbnails(self, output_dir: Path) -> Optional[str]:
        """Find existing yt-dlp thumbnail files and return relative path from storage root."""
        # Check JPG first since we convert to JPG
        for ext in ('.jpg', '.jpeg', '.png', '.webp'):
            thumbnail_file = output_dir / f'thumbnail{ext}'
            if thumbnail_file.exists():
                # Return relative path from storage root
                return str(thumbnail_file.relative_to(settings.get_storage_path()))
        return None
    
    async def _create_app_metadata(self, output_dir: Path) -> bool:
        """Create app metadata file from yt-dlp info.json"""
        try:
            # Find yt-dlp info.json file
            info_json_file = None
            for file_path in output_dir.iterdir():
                if file_path.name.endswith('.info.json'):
                    info_json_file = file_path
                    break
            
            if not info_json_file or not info_json_file.exists():
                print(f"No yt-dlp info.json found in {output_dir}")
                return False
            
            # Load yt-dlp metadata
            with open(info_json_file, 'r', encoding='utf-8') as f:
                ytdlp_info = json.load(f)
            
            # Parse into app metadata format
            storage_root = settings.get_storage_path()
            metadata = MetadataManager.parse_from_ytdlp(ytdlp_info, output_dir, storage_root)
            
            # Save app metadata
            success = MetadataManager.save_metadata(metadata, output_dir)
            if success:
                print(f"Created app metadata for {output_dir.name}")
            
            return success
            
        except Exception as e:
            print(f"Error creating app metadata for {output_dir}: {str(e)}")
            return False

    async def cancel_download(self, video_id: int) -> bool:
        """Cancel an active download"""
        if video_id in self.active_tasks:
            task = self.active_tasks[video_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                del self.active_tasks[video_id]
                if video_id in self.active_downloads:
                    del self.active_downloads[video_id]
                await self.db.update(
                    "job_queue",
                    {"status": "failed", "error_message": "Cancelled by user"},
                    "video_id = ?",
                    (video_id,)
                )
                await self.db.update(
                    "videos",
                    {"download_status": "failed"},
                    "id = ?",
                    (video_id,)
                )
                return True
        return False