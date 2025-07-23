# You Hoard - Design Document

## Overview

You Hoard is a self-hosted YouTube archiving application designed to be simple, lightweight, and effective. Unlike TubeArchivist which uses complex infrastructure (Elasticsearch, Redis), You Hoard keeps it simple with FastAPI, SQLite, and proven downloading libraries.

**Target User**: Single user running a LAN web application for personal YouTube archiving.

## Philosophy

- **Keep It Simple**: Minimal dependencies, straightforward architecture
- **Single User Focus**: No complex multi-tenancy or distributed systems
- **Reliable**: Lean on proven libraries (yt-dlp) for core functionality
- **Media Server Ready**: File organization compatible with Plex/Jellyfin

## Architecture

### Backend Stack
- **FastAPI**: REST API and web server
- **SQLite**: Database for metadata and application data
- **yt-dlp**: YouTube downloading library
- **Python UV**: Package management

### Frontend Stack
- **Simple HTML/CSS/JS**: Information-dense, responsive UI
- **Minimal frameworks**: Avoid complexity, focus on functionality

## Database Schema

### Core Tables

```sql
-- Channels
CREATE TABLE channels (
    id INTEGER PRIMARY KEY,
    youtube_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    subscriber_count INTEGER,
    thumbnail_url TEXT,
    extra_metadata TEXT, -- JSON object for arbitrary future metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Videos
CREATE TABLE videos (
    id INTEGER PRIMARY KEY,
    youtube_id TEXT UNIQUE NOT NULL,
    channel_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    duration INTEGER, -- seconds
    upload_date DATE,
    view_count INTEGER,
    like_count INTEGER,
    file_path TEXT, -- relative to storage root
    file_size INTEGER, -- bytes
    download_status TEXT CHECK(download_status IN ('pending', 'downloading', 'completed', 'failed', 'deleted')),
    quality TEXT, -- e.g., "1080p", "720p"
    extra_metadata TEXT, -- JSON object for arbitrary future metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (channel_id) REFERENCES channels (id)
);

-- Subscriptions
CREATE TABLE subscriptions (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    subscription_type TEXT CHECK(subscription_type IN ('channel', 'playlist')),
    source_url TEXT NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    quality_preference TEXT DEFAULT '1080p',
    download_comments BOOLEAN DEFAULT FALSE,
    subtitle_languages TEXT, -- JSON array of language codes
    audio_tracks TEXT, -- JSON array of audio track preferences
    check_frequency TEXT DEFAULT '0 * * * *', -- cron expression for check schedule (default: hourly)
    last_check TIMESTAMP,
    extra_metadata TEXT, -- JSON object for arbitrary future metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (channel_id) REFERENCES channels (id)
);

-- Tags
CREATE TABLE tags (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    color TEXT, -- hex color for UI
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Video Tags (many-to-many)
CREATE TABLE video_tags (
    video_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (video_id, tag_id),
    FOREIGN KEY (video_id) REFERENCES videos (id),
    FOREIGN KEY (tag_id) REFERENCES tags (id)
);

-- Channel Tags (many-to-many)
CREATE TABLE channel_tags (
    channel_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (channel_id, tag_id),
    FOREIGN KEY (channel_id) REFERENCES channels (id),
    FOREIGN KEY (tag_id) REFERENCES tags (id)
);

-- Download Queue
CREATE TABLE download_queue (
    id INTEGER PRIMARY KEY,
    video_id INTEGER NOT NULL,
    priority INTEGER DEFAULT 0,
    status TEXT CHECK(status IN ('queued', 'downloading', 'completed', 'failed', 'paused')),
    progress REAL DEFAULT 0.0, -- 0.0 to 100.0
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos (id)
);

-- App Settings
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Users (simple auth)
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## File Structure

### Storage Organization
```
/storage_root/
├── channels/
│   ├── {channel_youtube_id}_{sanitized_channel_name}/
│   │   ├── {video_id}_{sanitized_title}/
│   │   │   ├── video.{ext}                    # Main video file
│   │   │   ├── info.json                      # Video metadata
│   │   │   ├── thumbnail.{ext}                # Video thumbnail
│   │   │   ├── subtitles/
│   │   │   │   ├── {lang}.srt
│   │   │   │   └── {lang}.vtt
│   │   │   └── comments.json                  # Comments (if enabled)
│   │   └── channel_info.json                  # Channel metadata
│   └── ...
├── temp/
│   └── downloads/
└── logs/
    └── download.log
```

### Application Structure
```
you_hoard/
├── app/
│   ├── api/
│   │   ├── endpoints/
│   │   │   ├── videos.py
│   │   │   ├── channels.py
│   │   │   ├── subscriptions.py
│   │   │   ├── downloads.py
│   │   │   └── auth.py
│   │   └── __init__.py
│   ├── core/
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── security.py
│   │   └── downloader.py
│   ├── models/
│   │   ├── video.py
│   │   ├── channel.py
│   │   └── subscription.py
│   ├── static/
│   └── templates/
├── docs/
├── tests/
├── main.py
├── DESIGN.md
├── README.md
└── pyproject.toml
```

## API Design

### Authentication
- Simple session-based auth with username/password
- `/api/auth/login` - POST
- `/api/auth/logout` - POST
- `/api/auth/status` - GET

### Core Endpoints

#### Videos
- `GET /api/videos` - List videos with filtering/search
- `GET /api/videos/{id}` - Get video details
- `POST /api/videos` - Add video by URL
- `PUT /api/videos/{id}` - Update video metadata
- `DELETE /api/videos/{id}` - Delete video
- `POST /api/videos/{id}/download` - Queue video for download

#### Channels
- `GET /api/channels` - List channels
- `GET /api/channels/{id}` - Get channel details
- `GET /api/channels/{id}/videos` - Get channel's videos
- `PUT /api/channels/{id}` - Update channel metadata

#### Subscriptions
- `GET /api/subscriptions` - List subscriptions
- `POST /api/subscriptions` - Create subscription
- `PUT /api/subscriptions/{id}` - Update subscription
- `DELETE /api/subscriptions/{id}` - Delete subscription
- `POST /api/subscriptions/{id}/check` - Manual check for new content
- `POST /api/subscriptions/{id}/pause` - Pause subscription (sets 'enabled' to FALSE)
- `POST /api/subscriptions/{id}/resume` - Resume subscription (sets 'enabled' to TRUE)

#### Downloads
- `GET /api/downloads` - List download queue
- `POST /api/downloads/{id}/pause` - Pause download
- `POST /api/downloads/{id}/resume` - Resume download
- `POST /api/downloads/{id}/retry` - Retry failed download

#### Tags
- `GET /api/tags` - List tags
- `POST /api/tags` - Create tag
- `PUT /api/tags/{id}` - Update tag
- `DELETE /api/tags/{id}` - Delete tag

## Frontend Pages

### Home Page (`/`)
- Navigation bar with search
- Recent downloads dashboard
- Subscription check logs
- Storage usage statistics
- Quick actions (add video, check subscriptions)

### Videos Page (`/videos`)
- Searchable/filterable video grid
- Bulk operations (tag, delete, re-download)
- Sort by date, duration, quality, etc.
- Video player integration

### Channels Page (`/channels`)
- Channel grid with thumbnails
- Channel-specific settings
- Subscription management per channel

### Subscriptions Page (`/subscriptions`)
- List of active subscriptions
- Add new subscription form
- Subscription-specific settings (quality, comments, subtitles)
- Last check status and next check time
- Pause/resume controls for each subscription

### Downloads Page (`/downloads`)
- Active download progress
- Download queue management
- Failed download retry options
- Download history

### Settings Page (`/settings`)
- Storage paths configuration
- Default download quality
- YouTube API settings
- Authentication settings
- Cleanup policies

## Configuration

### Core Settings
- `storage_path`: Base directory for video storage
- `temp_path`: Temporary download directory
- `default_quality`: Default video quality preference
- `max_concurrent_downloads`: Download concurrency limit
- `default_check_cron`: Default cron expression for new subscription checks (e.g., '0 * * * *' for hourly)
- `youtube_api_key`: YouTube Data API key (optional, used for efficient metadata fetching and subscription checks to avoid scraping limits; fallback to yt-dlp if not provided)
- `default_audio_tracks`: Default audio track preferences as JSON array (e.g., ["en", "original"])
- `cleanup_enabled`: Auto-cleanup old videos
- `cleanup_days`: Days to keep videos before cleanup

### Download Settings
- `format_selector`: yt-dlp format selector string
- `audio_quality`: Audio quality preference
- `subtitle_languages`: Default subtitle languages to download
- `embed_subs`: Whether to embed subtitles in video files
- `write_info_json`: Save video metadata as JSON
- `write_thumbnail`: Download video thumbnails

## Security Considerations

- Input validation for all API endpoints
- SQL injection prevention with parameterized queries
- File path sanitization to prevent directory traversal
- Rate limiting on API endpoints
- Secure session management
- Password hashing with bcrypt

## Error Handling
- **Download Failures**: Track in `download_queue` with `error_message`; expose retry via API and UI notifications.
- **Rate Limiting/Retries**: Implement exponential backoff for YouTube interactions.
- **Input Validation**: Sanitize URLs, tags, and metadata to prevent errors or exploits.
- **Logging**: Centralize in `logs/download.log`; add `/api/logs` endpoint for recent entries on home page.

## Future Extensibility

- Plugin system for additional video platforms
- Webhook support for external integrations
- Video transcoding options
- Multi-user support (if needed)
- Mobile app API compatibility 