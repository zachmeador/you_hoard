-- The pause on YouTube work and its backoff in one row, so a restart doesn't forget them.
CREATE TABLE youtube_pause (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    -- When YouTube work resumes; NULL when it isn't paused.
    paused_until TEXT,
    -- Refusals in a row; a video request that goes through resets it.
    refusals INTEGER NOT NULL DEFAULT 0,
    -- What YouTube said when it refused; NULL for a pause the owner asked for.
    reason TEXT
);

INSERT INTO youtube_pause (id) VALUES (1);

-- A pause running when this upgrade lands was only in memory, but the job YouTube refused still
-- says when it ends and why.
WITH refused AS (
    SELECT run_after, error FROM jobs
    WHERE status = 'queued' AND kind IN ('download', 'check')
      AND run_after > strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
      AND (lower(error) LIKE '%sign in to confirm you%'
           OR lower(error) LIKE '%try again later%'
           OR lower(error) LIKE '%http error 429%'
           OR lower(error) LIKE '%too many requests%'
           OR lower(error) LIKE '%rate-limit%')
    ORDER BY run_after DESC
    LIMIT 1
)
UPDATE youtube_pause SET
    paused_until = (SELECT run_after FROM refused),
    refusals = (SELECT count(*) FROM refused),
    reason = (SELECT error FROM refused);
