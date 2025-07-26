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

-- Download Queue
CREATE TABLE IF NOT EXISTS download_queue (
    id INTEGER PRIMARY KEY,
    video_id INTEGER NOT NULL,
    priority INTEGER DEFAULT 0,
    quality TEXT,
    status TEXT CHECK(status IN ('queued', 'downloading', 'completed', 'failed', 'paused')) DEFAULT 'queued',
    progress REAL DEFAULT 0.0, -- 0.0 to 100.0
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (video_id) REFERENCES videos (id) ON DELETE CASCADE
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

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_videos_channel_id ON videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_videos_download_status ON videos(download_status);
CREATE INDEX IF NOT EXISTS idx_videos_youtube_id ON videos(youtube_id);
CREATE INDEX IF NOT EXISTS idx_channels_youtube_id ON channels(youtube_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_channel_id ON subscriptions(channel_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_enabled ON subscriptions(enabled);
CREATE INDEX IF NOT EXISTS idx_download_queue_video_id ON download_queue(video_id);
CREATE INDEX IF NOT EXISTS idx_download_queue_status ON download_queue(status);
CREATE INDEX IF NOT EXISTS idx_video_tags_video_id ON video_tags(video_id);
CREATE INDEX IF NOT EXISTS idx_video_tags_tag_id ON video_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_channel_tags_channel_id ON channel_tags(channel_id);
CREATE INDEX IF NOT EXISTS idx_channel_tags_tag_id ON channel_tags(tag_id);

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