"""Translate subscription schedules into discovery jobs."""

import logging
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.database import Database
from app.core.downloader import Downloader

logger = logging.getLogger(__name__)


class SubscriptionScheduler:
    def __init__(self, db: Database, downloader: Downloader):
        self.db = db
        self.downloader = downloader
        self.scheduler = AsyncIOScheduler()

    @property
    def is_running(self) -> bool:
        return self.scheduler.running

    async def start(self) -> None:
        if self.is_running:
            return
        subscriptions = await self.db.execute(
            "SELECT id, check_frequency FROM subscriptions WHERE enabled = 1"
        )
        for subscription in subscriptions:
            try:
                await self.add_subscription(subscription["id"], subscription["check_frequency"])
            except ValueError:
                logger.exception("Invalid schedule for subscription %s", subscription["id"])
        self.scheduler.start()

    async def stop(self) -> None:
        if self.is_running:
            self.scheduler.shutdown(wait=False)

    async def _check_subscription(self, subscription_id: int) -> None:
        subscription = await self.db.execute_one(
            "SELECT id FROM subscriptions WHERE id = ? AND enabled = 1", (subscription_id,)
        )
        if subscription:
            await self.downloader.queue_subscription_discovery(subscription_id, priority=1)

    async def add_subscription(self, subscription_id: int, cron_expression: str) -> None:
        self.scheduler.add_job(
            self._check_subscription,
            trigger=CronTrigger.from_crontab(cron_expression),
            args=[subscription_id],
            id=f"subscription_{subscription_id}",
            name=f"Check subscription {subscription_id}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )

    async def remove_subscription(self, subscription_id: int) -> None:
        job_id = f"subscription_{subscription_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

    async def update_subscription(self, subscription_id: int, cron_expression: str) -> None:
        await self.add_subscription(subscription_id, cron_expression)

    def get_scheduled_subscriptions(self) -> list[dict[str, Any]]:
        return [
            {
                "subscription_id": int(job.id.removeprefix("subscription_")),
                "next_run_time": getattr(job, "next_run_time", None),
                "trigger": str(job.trigger),
            }
            for job in self.scheduler.get_jobs()
        ]

    def next_check(self, subscription_id: int) -> datetime | None:
        job = self.scheduler.get_job(f"subscription_{subscription_id}")
        return getattr(job, "next_run_time", None) if job else None
