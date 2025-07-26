"""
Scheduler service for automatic subscription checking
"""
import logging
import time
from datetime import datetime
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.database import Database
from app.core.downloader import Downloader
from app.core.metadata import classify_video_type

logger = logging.getLogger(__name__)


class SubscriptionScheduler:
    """Manages automatic subscription checking via APScheduler"""
    
    def __init__(self, db: Database):
        self.db = db
        self.scheduler = AsyncIOScheduler()
        self.downloader = None
        self._is_running = False
    
    async def start(self):
        """Start the scheduler"""
        if self._is_running:
            return
        
        # Initialize downloader
        from app.core.downloader import Downloader
        self.downloader = Downloader(self.db)
        
        # Load and schedule all active subscriptions
        await self._load_subscriptions()
        
        # Start the scheduler
        self.scheduler.start()
        self._is_running = True
        logger.info("Subscription scheduler started")
    
    async def stop(self):
        """Stop the scheduler"""
        if not self._is_running:
            return
        
        self.scheduler.shutdown(wait=False)
        self._is_running = False
        logger.info("Subscription scheduler stopped")
    
    async def _load_subscriptions(self):
        """Load all active subscriptions and schedule them"""
        subscriptions = await self.db.execute(
            "SELECT id, check_frequency FROM subscriptions WHERE enabled = 1"
        )
        
        for sub in subscriptions:
            await self._schedule_subscription(sub['id'], sub['check_frequency'])
    
    async def _schedule_subscription(self, subscription_id: int, cron_expression: str):
        """Schedule a subscription check"""
        try:
            # Parse cron expression
            trigger = CronTrigger.from_crontab(cron_expression)
            
            # Add job to scheduler
            job_id = f"subscription_{subscription_id}"
            
            # Remove existing job if it exists
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
            
            # Add new job
            self.scheduler.add_job(
                self._check_subscription,
                trigger=trigger,
                args=[subscription_id],
                id=job_id,
                name=f"Check subscription {subscription_id}",
                max_instances=1,  # Prevent overlapping runs
                coalesce=True,    # Combine missed runs
                misfire_grace_time=300  # 5 minute grace period
            )
            
            logger.info(f"Scheduled subscription {subscription_id} with cron: {cron_expression}")
            
        except Exception as e:
            logger.error(f"Failed to schedule subscription {subscription_id}: {e}")
    
    async def _check_subscription(self, subscription_id: int):
        """Check a subscription for new content"""
        start_time = time.time()
        event_id = None
        
        try:
            logger.info(f"Checking subscription {subscription_id}")
            
            # Create initial event log
            event_id = await self.db.insert("scheduler_events", {
                "subscription_id": subscription_id,
                "event_type": "check_started",
                "status": "success",
                "started_at": datetime.utcnow().isoformat()
            })
            
            # Get subscription details
            subscription = await self.db.execute_one(
                """SELECT s.*, c.youtube_id as channel_youtube_id, c.name as channel_name
                   FROM subscriptions s
                   JOIN channels c ON s.channel_id = c.id
                   WHERE s.id = ? AND s.enabled = 1""",
                (subscription_id,)
            )
            
            if not subscription:
                logger.warning(f"Subscription {subscription_id} not found or disabled")
                # Update event with failure
                if event_id:
                    await self._complete_event(event_id, start_time, "failed", 
                                            error_message="Subscription not found or disabled")
                return
            
            # Extract video list from channel/playlist
            info = await self.downloader.extract_info(subscription['source_url'])
            
            new_videos = []
            errors = []
            videos_queued = 0
            videos_filtered = 0
            content_types_found = set()
            
            # Get list of videos
            entries = info.get('entries', [])
            videos_found = len(entries)
            
            # Get subscription's content type preferences
            subscription_content_types = subscription.get('content_types', ['video'])
            if isinstance(subscription_content_types, str):
                subscription_content_types = self.db.json_decode(subscription_content_types)
            
            # Calculate fetch limit to ensure we get enough videos after filtering
            desired_count = subscription.get('latest_n_videos', 20)
            if len(subscription_content_types) >= 3:  # All content types
                fetch_limit = desired_count
            else:
                # Fetch 3-5x more to account for filtering, max 200 for performance
                fetch_limit = min(desired_count * 4, 200)
            
            # Process videos and apply content filtering
            matched_videos = []
            for entry in entries[:fetch_limit]:
                video_id = entry.get('id')
                if not video_id:
                    continue
                
                # Classify video type and check if it's wanted by this subscription
                video_type = classify_video_type(entry)
                content_types_found.add(video_type)
                
                if video_type not in subscription_content_types:
                    videos_filtered += 1
                    continue  # Skip this video - not wanted by subscription
                
                # Check if video already exists
                existing = await self.db.execute_one(
                    "SELECT id FROM videos WHERE youtube_id = ?",
                    (video_id,)
                )
                
                if not existing:
                    # Add this video to our matched list
                    matched_videos.append({
                        'entry': entry,
                        'video_id': video_id, 
                        'video_type': video_type
                    })
                    
                    # Stop when we have enough matching videos
                    if len(matched_videos) >= desired_count:
                        break
            
            # Now process the matched videos (up to desired count)
            for video_data in matched_videos[:desired_count]:
                entry = video_data['entry']
                video_id = video_data['video_id']
                video_type = video_data['video_type']
                
                try:
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
                            await self.downloader.queue_download(
                                video_db_id, 
                                priority=1,  # Subscription downloads get priority 1
                                quality=subscription.get('quality_preference', '1080p')
                            )
                            videos_queued += 1
                            logger.info(f"Queued new video for download: {entry.get('title')}")
                        except Exception as e:
                            logger.error(f"Failed to queue video {video_id}: {e}")
                    
                    new_videos.append({
                        "youtube_id": video_id,
                        "title": entry.get('title')
                    })
                    logger.info(f"Added new video: {entry.get('title')}")
                except Exception as e:
                    error_msg = f"Failed to add video {video_id}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg)
            
            # Update last check time and new videos count
            await self.db.update(
                "subscriptions",
                {
                    "last_check": datetime.utcnow().isoformat(),
                    "new_videos_count": len(new_videos)
                },
                "id = ?",
                (subscription_id,)
            )
            
            # Complete event log with success
            status = "success" if not errors else "partial_success"
            if event_id:
                await self._complete_event(
                    event_id, start_time, status,
                    videos_found=videos_found,
                    videos_added=len(new_videos),
                    videos_queued=videos_queued,
                    videos_filtered=videos_filtered,
                    error_count=len(errors),
                    error_message="; ".join(errors[:3]) if errors else None,  # First 3 errors
                    content_types_processed=list(content_types_found),
                    metadata={
                        "channel_name": subscription.get('channel_name'),
                        "source_url": subscription.get('source_url'),
                        "fetch_limit": fetch_limit,
                        "desired_count": desired_count
                    }
                )
            
            if new_videos:
                logger.info(f"Found {len(new_videos)} new videos for subscription {subscription_id}")
            else:
                logger.info(f"No new videos found for subscription {subscription_id}")
            
            if errors:
                logger.warning(f"Errors during check: {errors}")
            
        except Exception as e:
            logger.error(f"Failed to check subscription {subscription_id}: {e}")
            # Complete event log with failure
            if event_id:
                await self._complete_event(event_id, start_time, "failed", 
                                        error_message=str(e))
    
    async def _complete_event(self, event_id: int, start_time: float, status: str, 
                            videos_found: int = 0, videos_added: int = 0, 
                            videos_queued: int = 0, videos_filtered: int = 0,
                            error_count: int = 0, error_message: str = None,
                            content_types_processed: list = None, metadata: dict = None):
        """Complete a scheduler event with final metrics"""
        duration_ms = int((time.time() - start_time) * 1000)
        
        update_data = {
            "event_type": "check_completed" if status != "failed" else "check_failed",
            "status": status,
            "videos_found": videos_found,
            "videos_added": videos_added,
            "videos_queued": videos_queued,
            "videos_filtered": videos_filtered,
            "duration_ms": duration_ms,
            "error_count": error_count,
            "completed_at": datetime.utcnow().isoformat()
        }
        
        if error_message:
            update_data["error_message"] = error_message
        if content_types_processed:
            update_data["content_types_processed"] = self.db.json_encode(content_types_processed)
        if metadata:
            update_data["metadata"] = self.db.json_encode(metadata)
        
        await self.db.update(
            "scheduler_events",
            update_data,
            "id = ?",
            (event_id,)
        )

    async def add_subscription(self, subscription_id: int, cron_expression: str):
        """Add or update a subscription to the scheduler"""
        await self._schedule_subscription(subscription_id, cron_expression)
    
    async def remove_subscription(self, subscription_id: int):
        """Remove a subscription from the scheduler"""
        job_id = f"subscription_{subscription_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            logger.info(f"Removed subscription {subscription_id} from scheduler")
    
    async def update_subscription(self, subscription_id: int, cron_expression: str):
        """Update a subscription's schedule"""
        await self.add_subscription(subscription_id, cron_expression)
    
    def get_scheduled_subscriptions(self) -> list:
        """Get list of currently scheduled subscriptions"""
        jobs = []
        for job in self.scheduler.get_jobs():
            if job.id.startswith('subscription_'):
                subscription_id = int(job.id.replace('subscription_', ''))
                jobs.append({
                    'subscription_id': subscription_id,
                    'next_run_time': job.next_run_time,
                    'trigger': str(job.trigger)
                })
        return jobs 