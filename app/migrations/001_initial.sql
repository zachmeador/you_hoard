CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE channels (
    id INTEGER PRIMARY KEY,
    youtube_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    handle TEXT,
    description TEXT,
    subscriber_count INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE videos (
    id INTEGER PRIMARY KEY,
    youtube_id TEXT NOT NULL UNIQUE,
    channel_id INTEGER REFERENCES channels (id),
    title TEXT NOT NULL,
    description TEXT,
    duration INTEGER,
    published_at TEXT,
    view_count INTEGER,
    like_count INTEGER,
    video_type TEXT NOT NULL DEFAULT 'video' CHECK (video_type IN ('video', 'short', 'live')),
    -- Relative to MEDIA_DIR. Sidecars share the media file's basename.
    media_path TEXT,
    media_size INTEGER,
    width INTEGER,
    height INTEGER,
    archived_at TEXT,
    -- The user removed the local files: never download automatically again.
    deleted_at TEXT,
    -- YouTube reported the video private, removed or otherwise gone.
    unavailable_at TEXT,
    watched_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX videos_channel ON videos (channel_id);
CREATE INDEX videos_published ON videos (published_at);
CREATE INDEX videos_archived ON videos (archived_at);
CREATE INDEX videos_media_path ON videos (media_path);

CREATE TABLE subscriptions (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('channel', 'playlist')),
    youtube_id TEXT NOT NULL,
    title TEXT NOT NULL,
    channel_id INTEGER REFERENCES channels (id),
    owner_name TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    content_types TEXT NOT NULL DEFAULT '["video"]',
    download_policy TEXT NOT NULL DEFAULT 'new'
        CHECK (download_policy IN ('none', 'new', 'recent', 'all')),
    recent_count INTEGER NOT NULL DEFAULT 10 CHECK (recent_count BETWEEN 1 AND 1000),
    -- NULL means the library default.
    quality TEXT,
    subtitle_languages TEXT,
    download_comments INTEGER,
    check_interval_hours INTEGER NOT NULL DEFAULT 6 CHECK (check_interval_hours BETWEEN 1 AND 720),
    -- Content types whose tab has been listed completely at least once.
    inventoried_types TEXT NOT NULL DEFAULT '[]',
    next_check_at TEXT,
    last_checked_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (kind, youtube_id)
);

CREATE INDEX subscriptions_due ON subscriptions (enabled, next_check_at);

CREATE TABLE source_entries (
    subscription_id INTEGER NOT NULL REFERENCES subscriptions (id) ON DELETE CASCADE,
    youtube_id TEXT NOT NULL,
    video_type TEXT NOT NULL DEFAULT 'video' CHECK (video_type IN ('video', 'short', 'live')),
    title TEXT,
    duration INTEGER,
    -- Order within its tab or playlist when listed (0 = newest/first).
    position INTEGER NOT NULL,
    -- Present in the first complete listing of its tab.
    baseline INTEGER NOT NULL,
    live_status TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    -- Absent from a later complete listing.
    removed_at TEXT,
    PRIMARY KEY (subscription_id, youtube_id)
);

CREATE INDEX source_entries_video ON source_entries (youtube_id);

CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('download', 'check', 'scan')),
    video_id INTEGER REFERENCES videos (id) ON DELETE CASCADE,
    subscription_id INTEGER REFERENCES subscriptions (id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'paused', 'running', 'completed', 'failed', 'cancelled')),
    priority INTEGER NOT NULL DEFAULT 0,
    options TEXT NOT NULL DEFAULT '{}',
    result TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    run_after TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    started_at TEXT,
    finished_at TEXT,
    CHECK ((kind = 'download') = (video_id IS NOT NULL)),
    CHECK ((kind = 'check') = (subscription_id IS NOT NULL))
);

CREATE UNIQUE INDEX jobs_one_active_download ON jobs (video_id)
    WHERE kind = 'download' AND status IN ('queued', 'paused', 'running');
CREATE UNIQUE INDEX jobs_one_active_check ON jobs (subscription_id)
    WHERE kind = 'check' AND status IN ('queued', 'paused', 'running');
CREATE UNIQUE INDEX jobs_one_active_scan ON jobs (kind)
    WHERE kind = 'scan' AND status IN ('queued', 'paused', 'running');
CREATE INDEX jobs_claim ON jobs (status, priority DESC, id);
CREATE INDEX jobs_video ON jobs (video_id, id);
CREATE INDEX jobs_subscription ON jobs (subscription_id, id);

-- Status is derived: durable facts on the video, transient work from its latest download job.
CREATE VIEW video_status AS
SELECT
    v.id AS video_id,
    j.id AS job_id,
    j.status AS job_status,
    j.error AS job_error,
    CASE
        WHEN v.media_path IS NOT NULL THEN 'archived'
        WHEN j.status = 'running' THEN 'downloading'
        WHEN j.status IN ('queued', 'paused') THEN 'queued'
        WHEN v.deleted_at IS NOT NULL THEN 'deleted'
        WHEN j.status = 'failed' THEN 'failed'
        ELSE 'missing'
    END AS status
FROM videos v
LEFT JOIN jobs j ON j.id = (
    SELECT max(id) FROM jobs WHERE kind = 'download' AND video_id = v.id
);
