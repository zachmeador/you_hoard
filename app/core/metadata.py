"""
Video metadata handling and parsing
"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, List, Literal
from datetime import datetime

logger = logging.getLogger(__name__)

# Video type enumeration
VideoType = Literal['video', 'short', 'live']

@dataclass
class VideoMetadata:
    """Structured video metadata"""
    app: Dict[str, Any]
    video: Dict[str, Any] 
    channel: Dict[str, Any]
    technical: Dict[str, Any]
    content: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def classify_video_type(ytdlp_info: Dict[str, Any]) -> VideoType:
    """
    Classify video type based on yt-dlp metadata
    
    Args:
        ytdlp_info: Video metadata from yt-dlp
        
    Returns:
        VideoType: 'live', 'short', or 'video'
    """
    # Live content takes highest priority
    if ytdlp_info.get('is_live'):
        return 'live'
    
    live_status = ytdlp_info.get('live_status', '')
    if live_status in ('is_live', 'is_upcoming'):
        return 'live'
    
    # Check for shorts based on aspect ratio
    width = ytdlp_info.get('width', 0)
    height = ytdlp_info.get('height', 0)
    
    if height > 0 and width > 0:
        aspect_ratio = width / height
        # Vertical videos (aspect ratio < 1.0) are likely shorts
        if aspect_ratio < 1.0:
            return 'short'
    
    # Also check duration as secondary indicator for shorts
    duration = ytdlp_info.get('duration', 0)
    if duration and duration <= 60 and width and height and width < height:
        return 'short'
    
    # Default to regular video
    return 'video'


class MetadataManager:
    """Manages video metadata creation and parsing"""
    
    APP_METADATA_VERSION = "1.0"
    
    @classmethod
    def parse_from_ytdlp(cls, ytdlp_info: Dict[str, Any], video_dir: Path, 
                        storage_root: Path) -> VideoMetadata:
        """
        Parse yt-dlp info.json into stable app metadata format
        """
        # App-specific metadata
        now = datetime.utcnow().isoformat() + 'Z'
        video_file = cls._find_video_file(video_dir)
        thumbnail_file = cls._find_thumbnail_file(video_dir)
        
        app_metadata = {
            'version': cls.APP_METADATA_VERSION,
            'created_at': now,
            'updated_at': now,
            'download_status': 'completed',
            'file_path': str(video_file.relative_to(storage_root)) if video_file else None,
            'file_size': video_file.stat().st_size if video_file and video_file.exists() else None,
            'thumbnail_path': str(thumbnail_file.relative_to(storage_root)) if thumbnail_file else None,
            'source': 'yt-dlp',
            'video_type': classify_video_type(ytdlp_info)  # Add classification
        }
        
        # Core video metadata
        video_metadata = {
            'youtube_id': ytdlp_info.get('id', ''),
            'title': ytdlp_info.get('title', ''),
            'fulltitle': ytdlp_info.get('fulltitle', ''),
            'description': ytdlp_info.get('description', ''),
            'duration': ytdlp_info.get('duration'),
            'duration_string': ytdlp_info.get('duration_string', ''),
            'upload_date': ytdlp_info.get('upload_date', ''),
            'timestamp': ytdlp_info.get('timestamp'),
            'view_count': ytdlp_info.get('view_count'),
            'like_count': ytdlp_info.get('like_count'),
            'comment_count': ytdlp_info.get('comment_count'),
            'webpage_url': ytdlp_info.get('webpage_url', ''),
            'display_id': ytdlp_info.get('display_id', ''),
            'video_type': classify_video_type(ytdlp_info)  # Add to video metadata too
        }
        
        # Channel metadata
        channel_metadata = {
            'youtube_id': ytdlp_info.get('channel_id', ''),
            'name': ytdlp_info.get('channel', '') or ytdlp_info.get('uploader', ''),
            'uploader': ytdlp_info.get('uploader', ''),
            'uploader_id': ytdlp_info.get('uploader_id', ''),
            'uploader_url': ytdlp_info.get('uploader_url', ''),
            'channel_url': ytdlp_info.get('channel_url', ''),
            'is_verified': ytdlp_info.get('channel_is_verified', False),
            'follower_count': ytdlp_info.get('channel_follower_count')
        }
        
        # Technical metadata
        technical_metadata = {
            'format': ytdlp_info.get('ext', ''),
            'format_id': ytdlp_info.get('format_id', ''),
            'format_note': ytdlp_info.get('format_note', ''),
            'resolution': ytdlp_info.get('resolution', ''),
            'width': ytdlp_info.get('width'),
            'height': ytdlp_info.get('height'),
            'fps': ytdlp_info.get('fps'),
            'aspect_ratio': ytdlp_info.get('aspect_ratio'),
            'vcodec': ytdlp_info.get('vcodec', ''),
            'acodec': ytdlp_info.get('acodec', ''),
            'tbr': ytdlp_info.get('tbr'),
            'vbr': ytdlp_info.get('vbr'),
            'abr': ytdlp_info.get('abr'),
            'asr': ytdlp_info.get('asr'),
            'audio_channels': ytdlp_info.get('audio_channels'),
            'dynamic_range': ytdlp_info.get('dynamic_range', ''),
            'filesize_approx': ytdlp_info.get('filesize_approx'),
            'protocol': ytdlp_info.get('protocol', ''),
            'language': ytdlp_info.get('language', '')
        }
        
        # Content metadata
        content_metadata = {
            'categories': ytdlp_info.get('categories', []),
            'tags': ytdlp_info.get('tags', []),
            'availability': ytdlp_info.get('availability', ''),
            'age_limit': ytdlp_info.get('age_limit', 0),
            'is_live': ytdlp_info.get('is_live', False),
            'was_live': ytdlp_info.get('was_live', False),
            'live_status': ytdlp_info.get('live_status', ''),
            'media_type': ytdlp_info.get('media_type', ''),
            'playable_in_embed': ytdlp_info.get('playable_in_embed'),
            'subtitles': cls._extract_subtitle_languages(ytdlp_info.get('subtitles', {})),
            'automatic_captions': cls._extract_subtitle_languages(ytdlp_info.get('automatic_captions', {}))
        }
        
        return VideoMetadata(
            app=app_metadata,
            video=video_metadata, 
            channel=channel_metadata,
            technical=technical_metadata,
            content=content_metadata
        )
    
    @classmethod
    def save_metadata(cls, metadata: VideoMetadata, video_dir: Path) -> bool:
        """Save app metadata to video directory"""
        try:
            metadata_file = video_dir / 'app.meta.json'
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata.to_dict(), f, indent=2, ensure_ascii=False)
            logger.info(f"Saved app metadata to {metadata_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save metadata to {video_dir}: {str(e)}")
            return False
    
    @classmethod
    def load_metadata(cls, video_dir: Path) -> Optional[VideoMetadata]:
        """Load app metadata from video directory"""
        try:
            metadata_file = video_dir / 'app.meta.json'
            if not metadata_file.exists():
                return None
                
            with open(metadata_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return VideoMetadata(
                app=data.get('app', {}),
                video=data.get('video', {}),
                channel=data.get('channel', {}),
                technical=data.get('technical', {}),
                content=data.get('content', {})
            )
        except Exception as e:
            logger.warning(f"Failed to load metadata from {video_dir}: {str(e)}")
            return None
    
    @classmethod
    def update_app_metadata(cls, video_dir: Path, **updates) -> bool:
        """Update specific app metadata fields"""
        try:
            metadata = cls.load_metadata(video_dir)
            if not metadata:
                logger.warning(f"No metadata file found in {video_dir}")
                return False
            
            # Update app metadata fields
            metadata.app.update(updates)
            metadata.app['updated_at'] = datetime.utcnow().isoformat() + 'Z'
            
            return cls.save_metadata(metadata, video_dir)
        except Exception as e:
            logger.error(f"Failed to update metadata in {video_dir}: {str(e)}")
            return False
    
    @classmethod
    def _find_video_file(cls, video_dir: Path) -> Optional[Path]:
        """Find the main video file in directory"""
        video_extensions = {'.mp4', '.mkv', '.webm', '.avi', '.mov', '.flv', '.m4v'}
        
        for file_path in video_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in video_extensions:
                return file_path
        return None
    
    @classmethod
    def _find_thumbnail_file(cls, video_dir: Path) -> Optional[Path]:
        """Find thumbnail file in directory"""
        thumbnail_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
        
        for file_path in video_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in thumbnail_extensions:
                return file_path
        return None
    
    @classmethod
    def _extract_subtitle_languages(cls, subtitles_dict: Dict[str, Any]) -> list:
        """Extract available subtitle language codes"""
        return list(subtitles_dict.keys()) if subtitles_dict else [] 