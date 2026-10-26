-- The latest download job's wait and tries too, so a queued video can show it is paused or waiting.
DROP VIEW video_status;
CREATE VIEW video_status AS
SELECT
    v.id AS video_id,
    j.id AS job_id,
    j.status AS job_status,
    j.error AS job_error,
    j.run_after AS job_run_after,
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
LEFT JOIN jobs j ON j.id = (
    SELECT max(id) FROM jobs WHERE kind = 'download' AND video_id = v.id
);
