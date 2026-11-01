-- Rules derived from the tables. Database.migrate() drops every view and runs this file at each
-- start, after the migrations, so changing a rule needs no migration.

-- Where each job stands. A queued job is waiting while its own run_after is ahead or, for the jobs
-- that talk to YouTube, while the pause on YouTube lasts. wait_ends is the later of the two and
-- waiting_on says which it is: 'youtube', or the job's own reason (a retry or a premiere). Both
-- are NULL unless the job is waiting. The pause and the time are read with scalar subqueries,
-- which run once per statement, rather than joined, so the views built on this one still flatten
-- into their callers.
CREATE VIEW job_state AS
SELECT
    w.*,
    CASE WHEN w.wait_ends IS NOT NULL THEN 'waiting' ELSE w.status END AS state,
    CASE
        WHEN w.wait_ends IS NULL THEN NULL
        WHEN w.kind IN ('download', 'check')
            AND w.wait_ends = (SELECT paused_until FROM youtube_pause) THEN 'youtube'
        ELSE w.reason
    END AS waiting_on
FROM (
    SELECT
        j.*,
        CASE WHEN j.status = 'queued' THEN nullif(max(
            coalesce(
                CASE WHEN j.run_after > (SELECT strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                    THEN j.run_after END,
                ''
            ),
            coalesce(
                CASE WHEN j.kind IN ('download', 'check') THEN (
                    SELECT paused_until FROM youtube_pause
                    WHERE paused_until > (SELECT strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                ) END,
                ''
            )
        ), '') END AS wait_ends
    FROM jobs j
) w;

-- Status is derived: durable facts on the video, transient work from its latest download job.
CREATE VIEW video_status AS
SELECT
    v.id AS video_id,
    j.id AS job_id,
    j.status AS job_status,
    j.state AS job_state,
    j.reason AS job_reason,
    j.waiting_on AS job_waiting_on,
    j.wait_ends AS job_waits_until,
    j.error AS job_error,
    j.attempts AS job_attempts,
    CASE
        WHEN v.media_path IS NOT NULL THEN 'archived'
        WHEN j.status = 'running' THEN 'downloading'
        WHEN j.status IN ('queued', 'paused') THEN 'queued'
        WHEN v.deleted_at IS NOT NULL THEN 'deleted'
        WHEN j.status = 'failed' THEN 'failed'
        ELSE 'missing'
    END AS status
FROM videos v
LEFT JOIN job_state j ON j.id = (
    SELECT max(id) FROM jobs WHERE kind = 'download' AND video_id = v.id
);

-- Why a subscription's download policy skips an inventory entry, or NULL when it selects it. The
-- first reason that applies wins. Whether the library already has the video is not part of the
-- rule: apply_policy only queues entries it has never seen. The statuses under not_ready are
-- NOT_READY in app/youtube.py.
CREATE VIEW entry_selection AS
SELECT
    e.*,
    CASE
        WHEN s.download_policy = 'none' THEN 'policy_none'
        WHEN s.enabled = 0 THEN 'subscription_off'
        WHEN e.removed_at IS NOT NULL THEN 'removed'
        WHEN coalesce(e.live_status, '') IN ('is_upcoming', 'is_live', 'post_live')
            THEN 'not_ready'
        WHEN s.kind = 'channel'
            AND e.video_type NOT IN (SELECT value FROM json_each(s.content_types)) THEN 'tab_off'
        WHEN s.download_policy = 'all' OR e.baseline = 0
            OR (s.download_policy = 'recent' AND e.position < s.recent_count) THEN NULL
        ELSE 'before_subscribing'
    END AS skip_reason
FROM source_entries e
JOIN subscriptions s ON s.id = e.subscription_id;
