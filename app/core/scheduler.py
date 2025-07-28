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
        """Check a subscription for new content (queue job for background processing)"""
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
            
            # Queue subscription discovery job (scheduled checks get priority 1)
            job_id = await self.downloader.queue_subscription_discovery(subscription_id, priority=1)
            logger.info(f"Queued subscription discovery job {job_id} for subscription {subscription_id}")
            
            # Complete the event immediately since we've queued the job
            if event_id:
                await self._complete_event(event_id, start_time, "success", 
                                         metadata={"job_id": job_id, "message": "Queued for background processing"})
            
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