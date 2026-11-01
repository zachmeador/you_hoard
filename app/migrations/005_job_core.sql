-- Jobs say why they are where they are, and what happens is recorded.

-- The view is rebuilt from app/views.sql once the migrations have run.
DROP VIEW IF EXISTS video_status;

-- Jobs are rebuilt to add AUTOINCREMENT as well as the new columns. Events refer to a job by its
-- plain id, and Clear finished deletes rows, so an id must never be handed out twice: a new job
-- would otherwise inherit the history of an old one.
CREATE TABLE jobs_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('download', 'check', 'scan')),
    video_id INTEGER REFERENCES videos (id) ON DELETE CASCADE,
    -- The subscription a check is for.
    subscription_id INTEGER REFERENCES subscriptions (id) ON DELETE CASCADE,
    -- The subscription a download came through. Deleting it leaves the download on library defaults.
    via_subscription_id INTEGER REFERENCES subscriptions (id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'paused', 'running', 'completed', 'failed', 'cancelled')),
    -- Who asked for the job: the owner by hand, a subscription's download policy or a due check.
    origin TEXT NOT NULL CHECK (origin IN ('user', 'policy', 'schedule')),
    -- Why the job is in its current status, one of Reason in app/jobs.py; NULL when there is
    -- nothing to explain, including while it runs or after it completes.
    reason TEXT,
    -- What reason becomes when a paused job resumes: the one it had while it was queued, so that a
    -- pause doesn't make a job forget it is waiting out a retry or a premiere.
    resume_reason TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    -- How many times YouTube has refused this job. A refused job goes behind every job YouTube
    -- hasn't refused.
    refusals INTEGER NOT NULL DEFAULT 0,
    options TEXT NOT NULL DEFAULT '{}',
    result TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    -- This job's own retry or premiere wait, and nothing else.
    run_after TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    started_at TEXT,
    finished_at TEXT,
    CHECK ((kind = 'download') = (video_id IS NOT NULL)),
    CHECK ((kind = 'check') = (subscription_id IS NOT NULL))
);

-- What an error means, with the phrases of WAITING, BLOCKED, INACCESSIBLE and GONE in
-- app/youtube.py. The lowest place that matches wins, as in `classify`.
WITH phrases (meaning, place, phrase) AS (VALUES
    ('waiting', 1, 'will begin'),
    ('waiting', 1, 'premieres in'),
    ('waiting', 1, 'premiere will begin'),
    -- The adapter's own message for a video that hasn't aired.
    ('waiting', 1, 'not available for download yet'),
    ('blocked', 2, 'not a bot'),
    ('blocked', 2, 'captcha'),
    ('blocked', 2, 'try again later'),
    ('blocked', 2, 'http error 429'),
    ('blocked', 2, 'too many requests'),
    ('blocked', 2, 'rate-limit'),
    ('inaccessible', 3, 'in your country'),
    ('inaccessible', 3, 'members-only'),
    ('inaccessible', 3, 'join this channel'),
    ('inaccessible', 3, 'confirm your age'),
    ('inaccessible', 3, 'age-restricted'),
    ('inaccessible', 3, 'inappropriate for some users'),
    ('inaccessible', 3, 'requires payment'),
    ('gone', 4, 'private video'),
    ('gone', 4, 'has been removed'),
    ('gone', 4, 'been terminated'),
    ('gone', 4, 'no longer available'),
    ('gone', 4, 'removed for violating'),
    ('gone', 4, 'copyright'),
    ('gone', 4, 'does not exist'),
    ('gone', 4, 'video unavailable')
)
INSERT INTO jobs_new (
    id, kind, video_id, subscription_id, via_subscription_id, status, origin, reason,
    resume_reason, priority, refusals, options, result, error, attempts, run_after, created_at,
    started_at, finished_at
)
SELECT
    j.id,
    j.kind,
    j.video_id,
    j.subscription_id,
    -- The foreign key refuses a subscription that was since deleted, and so does this.
    (SELECT s.id FROM subscriptions s WHERE s.id = json_extract(j.options, '$.subscription_id')),
    j.status,
    -- Asking for a job by hand gave it a priority. Without one, a check came from the schedule and
    -- a download came from a policy if it names a subscription. Read before the key goes below.
    CASE
        WHEN j.kind = 'scan' OR j.priority > 0 THEN 'user'
        WHEN j.kind = 'check' THEN 'schedule'
        WHEN json_extract(j.options, '$.subscription_id') IS NOT NULL THEN 'policy'
        ELSE 'user'
    END,
    -- Paused jobs stay NULL: nothing recorded why they were paused. A failed job that was only
    -- ever refused is an error, not gone, so that retrying failed jobs picks it up.
    CASE
        WHEN j.status = 'queued' AND j.error IS NOT NULL THEN
            CASE j.meaning WHEN 'waiting' THEN 'premiere' WHEN 'blocked' THEN 'refused' ELSE 'retry' END
        WHEN j.status = 'failed' THEN
            CASE
                WHEN j.kind = 'scan' AND j.error LIKE 'Rescan stopped:%' THEN 'declined'
                WHEN j.meaning = 'inaccessible' THEN 'needs_account'
                WHEN j.meaning = 'gone' THEN 'gone'
                ELSE 'error'
            END
    END,
    -- A paused job comes back to what it was waiting for, read from its error the same way.
    CASE
        WHEN j.status = 'paused' AND j.error IS NOT NULL THEN
            CASE j.meaning WHEN 'waiting' THEN 'premiere' WHEN 'blocked' THEN 'refused' ELSE 'retry' END
    END,
    -- The old code lowered a refused job's priority each time and kept no count. The count does
    -- that work now: refused at least once puts a job behind the ones YouTube hasn't refused.
    max(j.priority, 0),
    CASE WHEN j.status IN ('queued', 'paused') AND j.meaning = 'blocked' THEN 1 ELSE 0 END,
    json_remove(j.options, '$.subscription_id'),
    j.result,
    j.error,
    j.attempts,
    -- A queued download or check held until the pause ends is the pause copied onto the job, which
    -- nothing copies any more. So is a paused one that was queued when the pause began. Anything
    -- later is the job's own wait.
    CASE
        WHEN j.status IN ('queued', 'paused') AND j.kind IN ('download', 'check')
            AND j.run_after = (SELECT paused_until FROM youtube_pause) THEN NULL
        ELSE j.run_after
    END,
    j.created_at,
    j.started_at,
    j.finished_at
FROM (
    SELECT jobs.*, (
        SELECT meaning FROM phrases WHERE instr(lower(jobs.error), phrase) > 0 ORDER BY place LIMIT 1
    ) AS meaning
    FROM jobs
) j
ORDER BY j.id;

DROP TABLE jobs;
ALTER TABLE jobs_new RENAME TO jobs;

CREATE UNIQUE INDEX jobs_one_active_download ON jobs (video_id)
    WHERE kind = 'download' AND status IN ('queued', 'paused', 'running');
CREATE UNIQUE INDEX jobs_one_active_check ON jobs (subscription_id)
    WHERE kind = 'check' AND status IN ('queued', 'paused', 'running');
CREATE UNIQUE INDEX jobs_one_active_scan ON jobs (kind)
    WHERE kind = 'scan' AND status IN ('queued', 'paused', 'running');
CREATE INDEX jobs_claim ON jobs (status, refusals, priority DESC, id);
CREATE INDEX jobs_video ON jobs (video_id, id);
CREATE INDEX jobs_subscription ON jobs (subscription_id, id);
CREATE INDEX jobs_via_subscription ON jobs (via_subscription_id);

-- Append-only. The ids are plain integers, not foreign keys: the record outlives what it
-- describes, and Clear finished removes jobs but never events.
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    -- A name like job.paused or youtube.refused; the part before the dot is its group.
    event TEXT NOT NULL,
    -- owner (came through the API), app or cli.
    actor TEXT NOT NULL CHECK (actor IN ('owner', 'app', 'cli')),
    job_id INTEGER,
    job_kind TEXT,
    video_id INTEGER,
    subscription_id INTEGER,
    reason TEXT,
    detail TEXT
);

CREATE INDEX events_job ON events (job_id, id);
CREATE INDEX events_video ON events (video_id, id);
CREATE INDEX events_subscription ON events (subscription_id, id);
CREATE INDEX events_event ON events (event, at);

-- History for the Activity page and the download rate from the first start. Cancelling was always
-- the owner's doing.
INSERT INTO events (at, event, actor, job_id, job_kind, video_id, subscription_id, reason, detail)
SELECT
    coalesce(finished_at, created_at),
    'job.' || status,
    CASE status WHEN 'cancelled' THEN 'owner' ELSE 'app' END,
    id,
    kind,
    video_id,
    coalesce(subscription_id, via_subscription_id),
    CASE WHEN status = 'failed' THEN reason END,
    CASE WHEN status = 'failed' THEN error END
FROM jobs
WHERE status IN ('completed', 'failed', 'cancelled')
ORDER BY coalesce(finished_at, created_at), id;

-- Set when a rescan loses a file; cleared when it is relinked or downloaded again.
ALTER TABLE videos ADD COLUMN lost_at TEXT;

-- What started the pause, one of CAUSES in app/gate.py. Until now a reason meant a refusal.
ALTER TABLE youtube_pause ADD COLUMN cause TEXT;
UPDATE youtube_pause SET cause = CASE WHEN reason IS NULL THEN 'asked' ELSE 'refused' END
WHERE paused_until IS NOT NULL;
