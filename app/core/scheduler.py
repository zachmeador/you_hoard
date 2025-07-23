"""
Scheduler service for automatic subscription checking
"""
import logging
from datetime import datetime
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.database import Database
from app.core.downloader import Downloader

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
        from app.core.config import settings
        self.downloader = Downloader(settings)
        
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
        try:
            logger.info(f"Checking subscription {subscription_id}")
            
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
                return
            
            # Extract video list from channel/playlist
            info = await self.downloader.extract_info(subscription['source_url'])
            
            new_videos = []
            errors = []
            
            # Get list of videos
            entries = info.get('entries', [])
            
            for entry in entries[:20]:  # Check only recent 20 videos
                video_id = entry.get('id')
                if not video_id:
                    continue
                
                # Check if video already exists
                existing = await self.db.execute_one(
                    "SELECT id FROM videos WHERE youtube_id = ?",
                    (video_id,)
                )
                
                if not existing:
                    # Add new video
                    try:
                        await self.db.insert("videos", {
                            "youtube_id": video_id,
                            "channel_id": subscription['channel_id'],
                            "title": entry.get('title', 'Unknown Title'),
                            "description": entry.get('description'),
                            "duration": entry.get('duration'),
                            "upload_date": entry.get('upload_date'),
                            "download_status": "pending",
                            "created_at": datetime.utcnow().isoformat(),
                            "updated_at": datetime.utcnow().isoformat()
                        })
                        new_videos.append({
                            "youtube_id": video_id,
                            "title": entry.get('title')
                        })
                        logger.info(f"Added new video: {entry.get('title')}")
                    except Exception as e:
                        error_msg = f"Failed to add video {video_id}: {str(e)}"
                        errors.append(error_msg)
                        logger.error(error_msg)
            
            # Update last check time
            await self.db.update(
                "subscriptions",
                {"last_check": datetime.utcnow().isoformat()},
                "id = ?",
                (subscription_id,)
            )
            
            if new_videos:
                logger.info(f"Found {len(new_videos)} new videos for subscription {subscription_id}")
            else:
                logger.info(f"No new videos found for subscription {subscription_id}")
            
            if errors:
                logger.warning(f"Errors during check: {errors}")
            
        except Exception as e:
            logger.error(f"Failed to check subscription {subscription_id}: {e}")
    
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