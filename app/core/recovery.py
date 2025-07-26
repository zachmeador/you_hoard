"""
Auto-recovery and migration system for YouHoard
Scans storage directory and rebuilds database from existing video files
"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import logging

from app.core.database import Database
from app.core.config import settings
from app.core.metadata import MetadataManager

logger = logging.getLogger(__name__)


class RecoveryResult:
    """Result of recovery operation"""
    def __init__(self):
        self.channels_discovered = 0
        self.channels_created = 0
        self.channels_updated = 0
        self.videos_discovered = 0
        self.videos_created = 0
        self.videos_updated = 0
        self.errors: List[str] = []
        self.warnings: List[str] = []


class RecoveryManager:
    """Manages auto-recovery operations"""
    
    def __init__(self, db: Database):
        self.db = db
        self.storage_path = settings.get_storage_path()
        
    async def scan_and_recover(self) -> RecoveryResult:
        """
        Main recovery method - scans storage and rebuilds database
        """
        logger.info("Starting storage scan and recovery")
        result = RecoveryResult()
        
        try:
            # Discover channels and videos in storage
            discovered_data = await self._discover_storage_structure()
            result.channels_discovered = len(discovered_data['channels'])
            result.videos_discovered = sum(len(ch['videos']) for ch in discovered_data['channels'].values())
            
            # Process channels
            for channel_info in discovered_data['channels'].values():
                try:
                    channel_id = await self._process_channel(channel_info)
                    if channel_info.get('_created'):
                        result.channels_created += 1
                    else:
                        result.channels_updated += 1
                    
                    # Process videos for this channel
                    for video_info in channel_info['videos']:
                        try:
                            video_info['channel_id'] = channel_id
                            await self._process_video(video_info)
                            if video_info.get('_created'):
                                result.videos_created += 1
                            else:
                                result.videos_updated += 1
                        except Exception as e:
                            error_msg = f"Error processing video {video_info.get('youtube_id', 'unknown')}: {str(e)}"
                            result.errors.append(error_msg)
                            logger.error(error_msg)
                
                except Exception as e:
                    error_msg = f"Error processing channel {channel_info.get('youtube_id', 'unknown')}: {str(e)}"
                    result.errors.append(error_msg)
                    logger.error(error_msg)
                    
        except Exception as e:
            error_msg = f"Fatal error during recovery: {str(e)}"
            result.errors.append(error_msg)
            logger.error(error_msg)
        
        logger.info(f"Recovery completed: {result.channels_created} channels created, {result.videos_created} videos created")
        return result
    
    async def _discover_storage_structure(self) -> Dict[str, Any]:
        """
        Discover channels and videos from storage directory structure
        Returns: {'channels': {youtube_id: channel_info}}
        """
        channels_path = self.storage_path / "channels"
        discovered = {'channels': {}}
        
        if not channels_path.exists():
            logger.warning(f"Channels directory not found: {channels_path}")
            return discovered
        
        # Scan channel directories
        for channel_dir in channels_path.iterdir():
            if not channel_dir.is_dir():
                continue
                
            try:
                channel_info = await self._extract_channel_info(channel_dir)
                if channel_info:
                    # Discover videos in this channel
                    channel_info['videos'] = await self._discover_channel_videos(channel_dir)
                    discovered['channels'][channel_info['youtube_id']] = channel_info
            except Exception as e:
                logger.warning(f"Error processing channel directory {channel_dir.name}: {str(e)}")
        
        return discovered
    
    async def _extract_channel_info(self, channel_dir: Path) -> Optional[Dict[str, Any]]:
        """
        Extract channel information from directory and metadata files
        """
        # Try to read channel_info.json first
        channel_info_file = channel_dir / "channel_info.json"
        if channel_info_file.exists():
            try:
                with open(channel_info_file, 'r', encoding='utf-8') as f:
                    info = json.load(f)
                    return {
                        'youtube_id': info.get('id', ''),
                        'name': info.get('title', ''),
                        'description': info.get('description', ''),
                        'subscriber_count': info.get('subscriber_count'),
                        'thumbnail_url': info.get('thumbnail'),
                        'directory_path': channel_dir,
                        'source': 'metadata_file'
                    }
            except Exception as e:
                logger.warning(f"Error reading channel_info.json from {channel_dir}: {str(e)}")
        
        # Fallback: parse from directory name
        channel_info = self._parse_channel_from_dirname(channel_dir.name)
        if channel_info:
            channel_info['directory_path'] = channel_dir
            channel_info['source'] = 'directory_name'
            return channel_info
        
        return None
    
    def _parse_channel_from_dirname(self, dirname: str) -> Optional[Dict[str, Any]]:
        """
        Parse channel info from directory name format: {youtube_id}_{channel_name}
        """
        # Match pattern: UCxxxxxxxxxxxxxxxxxx_ChannelName or @channelhandle_ChannelName
        pattern = r'^(UC[a-zA-Z0-9_-]{22}|@[a-zA-Z0-9._-]+)_(.+)$'
        match = re.match(pattern, dirname)
        
        if match:
            youtube_id, channel_name = match.groups()
            return {
                'youtube_id': youtube_id,
                'name': channel_name.replace('_', ' '),
                'description': None,
                'subscriber_count': None,
                'thumbnail_url': None
            }
        
        # Try simpler pattern for legacy directories
        if '_' in dirname:
            parts = dirname.split('_', 1)
            if len(parts) == 2 and len(parts[0]) >= 10:  # Assume first part is some kind of ID
                return {
                    'youtube_id': parts[0],
                    'name': parts[1].replace('_', ' '),
                    'description': None,
                    'subscriber_count': None,
                    'thumbnail_url': None
                }
        
        return None
    
    async def _discover_channel_videos(self, channel_dir: Path) -> List[Dict[str, Any]]:
        """
        Discover videos in a channel directory
        """
        videos = []
        
        # Scan for video directories
        for video_dir in channel_dir.iterdir():
            if not video_dir.is_dir():
                continue
                
            try:
                video_info = await self._extract_video_info(video_dir)
                if video_info:
                    videos.append(video_info)
            except Exception as e:
                logger.warning(f"Error processing video directory {video_dir.name}: {str(e)}")
        
        return videos
    
    async def _extract_video_info(self, video_dir: Path) -> Optional[Dict[str, Any]]:
        """
        Extract video information from directory and metadata files
        """
        # Try to load app metadata first (preferred)
        app_metadata = MetadataManager.load_metadata(video_dir)
        if app_metadata:
            try:
                # Extract info from app metadata structure
                video_file = self._find_video_file(video_dir)
                
                return {
                    'youtube_id': app_metadata.video.get('youtube_id', ''),
                    'title': app_metadata.video.get('title', ''),
                    'description': app_metadata.video.get('description', ''),
                    'duration': app_metadata.video.get('duration'),
                    'upload_date': self._parse_upload_date(app_metadata.video.get('upload_date')),
                    'view_count': app_metadata.video.get('view_count'),
                    'like_count': app_metadata.video.get('like_count'),
                    'quality': self._get_quality_from_technical(app_metadata.technical),
                    'file_path': app_metadata.app.get('file_path') or (str(video_file.relative_to(self.storage_path)) if video_file else None),
                    'file_size': app_metadata.app.get('file_size') or (video_file.stat().st_size if video_file and video_file.exists() else None),
                    'directory_path': video_dir,
                    'source': 'app_metadata'
                }
            except Exception as e:
                logger.warning(f"Error reading app metadata from {video_dir}: {str(e)}")
        
        # Fallback: Try to read yt-dlp info.json
        info_file = video_dir / "info.json"
        if not info_file.exists():
            # Also try video.info.json (some downloads might use this pattern)
            info_file = video_dir / "video.info.json"
        
        if info_file.exists():
            try:
                with open(info_file, 'r', encoding='utf-8') as f:
                    info = json.load(f)
                    
                    # Find video file
                    video_file = self._find_video_file(video_dir)
                    
                    return {
                        'youtube_id': info.get('id', ''),
                        'title': info.get('title', ''),
                        'description': info.get('description', ''),
                        'duration': info.get('duration'),
                        'upload_date': self._parse_upload_date(info.get('upload_date')),
                        'view_count': info.get('view_count'),
                        'like_count': info.get('like_count'),
                        'quality': info.get('height', ''),
                        'file_path': str(video_file.relative_to(self.storage_path)) if video_file else None,
                        'file_size': video_file.stat().st_size if video_file and video_file.exists() else None,
                        'directory_path': video_dir,
                        'source': 'ytdlp_metadata'
                    }
            except Exception as e:
                logger.warning(f"Error reading yt-dlp info.json from {video_dir}: {str(e)}")
        
        # Final fallback: parse from directory name and files
        video_info = self._parse_video_from_dirname(video_dir.name)
        if video_info:
            video_file = self._find_video_file(video_dir)
            video_info.update({
                'file_path': str(video_file.relative_to(self.storage_path)) if video_file else None,
                'file_size': video_file.stat().st_size if video_file and video_file.exists() else None,
                'directory_path': video_dir,
                'source': 'directory_name'
            })
            return video_info
        
        return None
    
    def _parse_video_from_dirname(self, dirname: str) -> Optional[Dict[str, Any]]:
        """
        Parse video info from directory name format: {video_id}_{title}
        """
        # Match pattern: 11-character YouTube video ID followed by underscore
        pattern = r'^([a-zA-Z0-9_-]{11})_(.+)$'
        match = re.match(pattern, dirname)
        
        if match:
            video_id, title = match.groups()
            return {
                'youtube_id': video_id,
                'title': title.replace('_', ' '),
                'description': None,
                'duration': None,
                'upload_date': None,
                'view_count': None,
                'like_count': None,
                'quality': None
            }
        
        return None
    
    def _find_video_file(self, video_dir: Path) -> Optional[Path]:
        """
        Find the main video file in a video directory
        """
        video_extensions = {'.mp4', '.mkv', '.webm', '.avi', '.mov', '.flv', '.m4v'}
        
        for file_path in video_dir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in video_extensions:
                return file_path
        
        return None
    
    def _parse_upload_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse upload date from various formats
        """
        if not date_str:
            return None
            
        try:
            # Try YYYYMMDD format first
            if len(date_str) == 8 and date_str.isdigit():
                return datetime.strptime(date_str, '%Y%m%d')
            
            # Try ISO format
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            
        except Exception:
            return None
    
    def _get_quality_from_technical(self, technical_data: Dict[str, Any]) -> str:
        """
        Extract quality string from technical metadata
        """
        height = technical_data.get('height')
        if height:
            return f"{height}p"
        
        resolution = technical_data.get('resolution', '')
        if resolution:
            return resolution
        
        return ''
    
    async def _process_channel(self, channel_info: Dict[str, Any]) -> int:
        """
        Create or update channel in database
        Returns channel ID
        """
        # Check if channel exists
        existing = await self.db.execute_one(
            "SELECT id FROM channels WHERE youtube_id = ?",
            (channel_info['youtube_id'],)
        )
        
        channel_data = {
            'youtube_id': channel_info['youtube_id'],
            'name': channel_info['name'] or 'Unknown Channel',
            'description': channel_info.get('description'),
            'subscriber_count': channel_info.get('subscriber_count'),
            'thumbnail_url': channel_info.get('thumbnail_url'),
            'updated_at': datetime.now()
        }
        
        if existing:
            # Update existing channel
            await self.db.update(
                'channels',
                channel_data,
                'id = ?',
                (existing['id'],)
            )
            channel_info['_created'] = False
            return existing['id']
        else:
            # Create new channel
            channel_data['created_at'] = datetime.now()
            channel_id = await self.db.insert('channels', channel_data)
            channel_info['_created'] = True
            return channel_id
    
    async def _process_video(self, video_info: Dict[str, Any]) -> int:
        """
        Create or update video in database
        Returns video ID
        """
        # Check if video exists
        existing = await self.db.execute_one(
            "SELECT id FROM videos WHERE youtube_id = ?",
            (video_info['youtube_id'],)
        )
        
        video_data = {
            'youtube_id': video_info['youtube_id'],
            'channel_id': video_info['channel_id'],
            'title': video_info['title'] or 'Unknown Title',
            'description': video_info.get('description'),
            'duration': video_info.get('duration'),
            'upload_date': video_info.get('upload_date'),
            'view_count': video_info.get('view_count'),
            'like_count': video_info.get('like_count'),
            'quality': video_info.get('quality'),
            'file_path': video_info.get('file_path'),
            'file_size': video_info.get('file_size'),
            'download_status': 'completed' if video_info.get('file_path') else 'pending',
            'updated_at': datetime.now()
        }
        
        if existing:
            # Update existing video
            await self.db.update(
                'videos',
                video_data,
                'id = ?',
                (existing['id'],)
            )
            video_info['_created'] = False
            return existing['id']
        else:
            # Create new video
            video_data['created_at'] = datetime.now()
            video_id = await self.db.insert('videos', video_data)
            video_info['_created'] = True
            return video_id
    
    async def check_database_empty(self) -> bool:
        """
        Check if database has any videos or channels
        """
        video_count = await self.db.execute_one("SELECT COUNT(*) as count FROM videos")
        channel_count = await self.db.execute_one("SELECT COUNT(*) as count FROM channels")
        
        return video_count['count'] == 0 and channel_count['count'] == 0 