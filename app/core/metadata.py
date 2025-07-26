"""
Metadata management for You Hoard
Handles parsing yt-dlp metadata into stable app format
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class VideoMetadata:
    """Stable app metadata structure for videos"""
    
    def __init__(self):
        self.app: Dict[str, Any] = {}
        self.video: Dict[str, Any] = {}
        self.channel: Dict[str, Any] = {}
        self.technical: Dict[str, Any] = {}
        self.content: Dict[str, Any] = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'app': self.app,
            'video': self.video,
            'channel': self.channel,
            'technical': self.technical,
            'content': self.content
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoMetadata':
        """Create from dictionary loaded from JSON"""
        metadata = cls()
        metadata.app = data.get('app', {})
        metadata.video = data.get('video', {})
        metadata.channel = data.get('channel', {})
        metadata.technical = data.get('technical', {})
        metadata.content = data.get('content', {})
        return metadata


class MetadataManager:
    """Manages video metadata creation and parsing"""
    
    APP_METADATA_VERSION = "1.0"
    
    @classmethod
    def parse_from_ytdlp(cls, ytdlp_info: Dict[str, Any], video_dir: Path, 
                        storage_root: Path) -> VideoMetadata:
        """
        Parse yt-dlp info.json into stable app metadata format
        """
        metadata = VideoMetadata()
        
        # App-specific metadata
        now = datetime.utcnow().isoformat() + 'Z'
        video_file = cls._find_video_file(video_dir)
        thumbnail_file = cls._find_thumbnail_file(video_dir)
        
        metadata.app = {
            'version': cls.APP_METADATA_VERSION,
            'created_at': now,
            'updated_at': now,
            'download_status': 'completed',
            'file_path': str(video_file.relative_to(storage_root)) if video_file else None,
            'file_size': video_file.stat().st_size if video_file and video_file.exists() else None,
            'thumbnail_path': str(thumbnail_file.relative_to(storage_root)) if thumbnail_file else None,
            'source': 'yt-dlp'
        }
        
        # Core video metadata
        metadata.video = {
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
            'display_id': ytdlp_info.get('display_id', '')
        }
        
        # Channel metadata
        metadata.channel = {
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
        metadata.technical = {
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
        metadata.content = {
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
        
        return metadata
    
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
            
            return VideoMetadata.from_dict(data)
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