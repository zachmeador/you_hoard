"""
Quality management and mapping for YouHoard
"""

from typing import Any, Dict, Optional

from app.core.database import Database


class QualityService:
    """Service for handling video quality preferences and mapping"""

    # Quality option to yt-dlp format mapping
    QUALITY_FORMATS = {
        "best": "bestvideo+bestaudio/best",
        **{
            f"{height}p": f"bestvideo[height<=?{height}]+bestaudio/best[height<=?{height}]"
            for height in (240, 360, 480, 720, 1080, 1440, 2160)
        },
        "worst": "worst",
    }

    DEFAULT_QUALITY = "1080p"

    @classmethod
    def get_format_selector(cls, quality: str) -> str:
        """Convert quality preference to yt-dlp format selector"""
        if not cls.validate_quality(quality):
            raise ValueError(f"Unsupported quality: {quality}")
        return cls.QUALITY_FORMATS[quality]

    @classmethod
    def validate_quality(cls, quality: str) -> bool:
        """Check if quality option is valid"""
        return quality in cls.QUALITY_FORMATS

    @classmethod
    async def resolve_quality_preference(
        cls,
        db: Database,
        video_quality: Optional[str] = None,
        subscription_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> str:
        """
        Resolve quality preference using hierarchy:
        1. video_quality (individual submission)
        2. subscription quality_preference
        3. user's global quality preference
        4. default quality
        """

        # 1. Individual video submission quality (highest priority)
        if video_quality and cls.validate_quality(video_quality):
            return video_quality

        # 2. Subscription quality preference
        if subscription_id:
            subscription = await db.execute_one(
                "SELECT quality_preference FROM subscriptions WHERE id = ?", (subscription_id,)
            )
            if subscription and subscription["quality_preference"]:
                if cls.validate_quality(subscription["quality_preference"]):
                    return subscription["quality_preference"]

        # 3. Global application quality preference
        global_setting = await db.execute_one(
            "SELECT value FROM settings WHERE key = ?", ("default_quality",)
        )
        if global_setting and global_setting["value"]:
            if cls.validate_quality(global_setting["value"]):
                return global_setting["value"]

        # 4. System default quality (fallback)
        from app.core.config import settings

        return (
            settings.DEFAULT_QUALITY
            if cls.validate_quality(settings.DEFAULT_QUALITY)
            else cls.DEFAULT_QUALITY
        )

    @classmethod
    def extract_quality_from_metadata(cls, metadata: Dict[str, Any]) -> Optional[str]:
        """Extract quality information from yt-dlp metadata"""
        # Try to get resolution info
        height = metadata.get("height")
        if height:
            return f"{int(height)}p"

        # Fallback to format info
        format_note = metadata.get("format_note", "").lower()
        if "hd" in format_note or "1080" in format_note:
            return "1080p"
        elif "720" in format_note:
            return "720p"
        elif "480" in format_note:
            return "480p"
        elif "360" in format_note:
            return "360p"

        return None
