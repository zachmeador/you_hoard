-- YouHoard Database Schema

-- Channels table
CREATE TABLE IF NOT EXISTS channels (
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

-- Videos table
CREATE TABLE IF NOT EXISTS videos (
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
    download_status TEXT CHECK(download_status IN ('pending', 'downloading', 'completed', 'failed', 'deleted')) DEFAULT 'pending',
    quality TEXT, -- e.g., "1080p", "720p"
    video_type TEXT CHECK(video_type IN ('video', 'short', 'live')) DEFAULT 'video',
    thumbnail_path TEXT, -- relative path to thumbnail file
    thumbnail_generated BOOLEAN DEFAULT FALSE, -- whether thumbnail was generated from video
    thumbnail_timestamp REAL, -- timestamp in seconds for generated thumbnails
    extra_metadata TEXT, -- JSON object for arbitrary future metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (channel_id) REFERENCES channels (id)
);

-- Subscriptions table
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    subscription_type TEXT CHECK(subscription_type IN ('channel', 'playlist')),
    source_url TEXT NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    auto_download BOOLEAN DEFAULT TRUE, -- automatically queue new videos for download
    quality_preference TEXT DEFAULT '1080p',
    download_comments BOOLEAN DEFAULT FALSE,
    subtitle_languages TEXT, -- JSON array of language codes
    audio_tracks TEXT, -- JSON array of audio track preferences
    check_frequency TEXT DEFAULT '0 * * * *', -- cron expression for check schedule (default: hourly)
    latest_n_videos INTEGER DEFAULT 20, -- number of recent videos to check for new content
    content_types TEXT DEFAULT '["video"]', -- JSON array of video types to include: video, short, live
    last_check TIMESTAMP,
    new_videos_count INTEGER DEFAULT 0, -- count of new videos found in last check
    extra_metadata TEXT, -- JSON object for arbitrary future metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (channel_id) REFERENCES channels (id)
);

-- Scheduler Events (for logging subscription checks)
CREATE TABLE IF NOT EXISTS scheduler_events (
    id INTEGER PRIMARY KEY,
    subscription_id INTEGER NOT NULL,
    event_type TEXT CHECK(event_type IN ('check_started', 'check_completed', 'check_failed', 'check_cancelled')) NOT NULL,
    status TEXT CHECK(status IN ('success', 'partial_success', 'failed')) DEFAULT 'success',
    videos_found INTEGER DEFAULT 0, -- total videos found from source
    videos_added INTEGER DEFAULT 0, -- new videos added to database
    videos_queued INTEGER DEFAULT 0, -- videos queued for download
    videos_filtered INTEGER DEFAULT 0, -- videos filtered out by content type
    duration_ms INTEGER, -- how long the check took in milliseconds
    error_message TEXT, -- error details if check failed
    error_count INTEGER DEFAULT 0, -- count of individual video processing errors
    content_types_processed TEXT, -- JSON array of content types found
    metadata TEXT, -- JSON object for additional event details
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (subscription_id) REFERENCES subscriptions (id) ON DELETE CASCADE
);

-- Tags table
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    color TEXT, -- hex color for UI
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Video Tags (many-to-many)
CREATE TABLE IF NOT EXISTS video_tags (
    video_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (video_id, tag_id),
    FOREIGN KEY (video_id) REFERENCES videos (id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE
);

-- Channel Tags (many-to-many)
CREATE TABLE IF NOT EXISTS channel_tags (
    channel_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (channel_id, tag_id),
    FOREIGN KEY (channel_id) REFERENCES channels (id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE
);

-- Unified Job Queue (handles downloads, subscription discovery, metadata extraction)
CREATE TABLE IF NOT EXISTS job_queue (
    id INTEGER PRIMARY KEY,
    job_type TEXT CHECK(job_type IN ('download', 'subscription_discovery', 'video_metadata_extraction')) DEFAULT 'download',
    video_id INTEGER, -- for download jobs
    subscription_id INTEGER, -- for subscription_discovery jobs
    video_url TEXT, -- for video_metadata_extraction jobs
    priority INTEGER DEFAULT 0,
    quality TEXT, -- for download jobs
    status TEXT CHECK(status IN ('queued', 'downloading', 'processing', 'completed', 'failed', 'paused')) DEFAULT 'queued',
    progress REAL DEFAULT 0.0, -- 0.0 to 100.0
    videos_found INTEGER DEFAULT 0, -- for discovery jobs
    videos_processed INTEGER DEFAULT 0, -- for discovery jobs
    error_message TEXT,
    result_data TEXT, -- JSON object with job results
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos (id) ON DELETE CASCADE,
    FOREIGN KEY (subscription_id) REFERENCES subscriptions (id) ON DELETE CASCADE
);

-- App Settings
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Users (simple auth)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sessions table
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_videos_channel_id ON videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_videos_download_status ON videos(download_status);
CREATE INDEX IF NOT EXISTS idx_videos_video_type ON videos(video_type);
CREATE INDEX IF NOT EXISTS idx_videos_youtube_id ON videos(youtube_id);
CREATE INDEX IF NOT EXISTS idx_channels_youtube_id ON channels(youtube_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_channel_id ON subscriptions(channel_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_enabled ON subscriptions(enabled);
CREATE INDEX IF NOT EXISTS idx_scheduler_events_subscription_id ON scheduler_events(subscription_id);
CREATE INDEX IF NOT EXISTS idx_scheduler_events_event_type ON scheduler_events(event_type);
CREATE INDEX IF NOT EXISTS idx_scheduler_events_started_at ON scheduler_events(started_at);
CREATE INDEX IF NOT EXISTS idx_job_queue_video_id ON job_queue(video_id);
CREATE INDEX IF NOT EXISTS idx_job_queue_subscription_id ON job_queue(subscription_id);
CREATE INDEX IF NOT EXISTS idx_job_queue_status ON job_queue(status);
CREATE INDEX IF NOT EXISTS idx_job_queue_job_type ON job_queue(job_type);
CREATE INDEX IF NOT EXISTS idx_video_tags_video_id ON video_tags(video_id);
CREATE INDEX IF NOT EXISTS idx_video_tags_tag_id ON video_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_channel_tags_channel_id ON channel_tags(channel_id);
CREATE INDEX IF NOT EXISTS idx_channel_tags_tag_id ON channel_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);

-- Triggers to update timestamps
CREATE TRIGGER IF NOT EXISTS update_channels_timestamp 
AFTER UPDATE ON channels
BEGIN
    UPDATE channels SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_videos_timestamp 
AFTER UPDATE ON videos
BEGIN
    UPDATE videos SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_settings_timestamp 
AFTER UPDATE ON settings
BEGIN
    UPDATE settings SET updated_at = CURRENT_TIMESTAMP WHERE key = NEW.key;
END; 