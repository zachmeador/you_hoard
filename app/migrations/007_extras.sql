-- A job fetches the subtitles and live chat a download missed, so a refused one is not lost for
-- good.

-- The views are rebuilt from app/views.sql once the migrations have run.
DROP VIEW IF EXISTS video_status;
DROP VIEW IF EXISTS job_state;

-- Jobs are rebuilt because SQLite can't change a CHECK: an extras job belongs to a video, as a
-- download does. Events refer to a job by its plain id, so every row keeps its id.
CREATE TABLE jobs_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('download', 'check', 'scan', 'extras')),
    video_id INTEGER REFERENCES videos (id) ON DELETE CASCADE,
    -- The subscription a check is for.
    subscription_id INTEGER REFERENCES subscriptions (id) ON DELETE CASCADE,
    -- The subscription a download or extras job came through. Deleting it leaves the job on
    -- library defaults.
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
    CHECK ((kind IN ('download', 'extras')) = (video_id IS NOT NULL)),
    CHECK ((kind = 'check') = (subscription_id IS NOT NULL))
);

INSERT INTO jobs_new (
    id, kind, video_id, subscription_id, via_subscription_id, status, origin, reason,
    resume_reason, priority, refusals, options, result, error, attempts, run_after, created_at,
    started_at, finished_at
)
SELECT
    id, kind, video_id, subscription_id, via_subscription_id, status, origin, reason,
    resume_reason, priority, refusals, options, result, error, attempts, run_after, created_at,
    started_at, finished_at
FROM jobs
ORDER BY id;

-- The highest id ever handed out is kept in sqlite_sequence, and dropping the old table loses
-- it. Clear finished may have deleted the newest jobs, whose ids events still refer to, so the
-- rebuilt table starts from the old table's number, not from its highest remaining id.
DELETE FROM sqlite_sequence WHERE name = 'jobs_new';
INSERT INTO sqlite_sequence (name, seq)
SELECT 'jobs_new', seq FROM sqlite_sequence WHERE name = 'jobs';

DROP TABLE jobs;
ALTER TABLE jobs_new RENAME TO jobs;

CREATE UNIQUE INDEX jobs_one_active_download ON jobs (video_id)
    WHERE kind = 'download' AND status IN ('queued', 'paused', 'running');
CREATE UNIQUE INDEX jobs_one_active_extras ON jobs (video_id)
    WHERE kind = 'extras' AND status IN ('queued', 'paused', 'running');
CREATE UNIQUE INDEX jobs_one_active_check ON jobs (subscription_id)
    WHERE kind = 'check' AND status IN ('queued', 'paused', 'running');
CREATE UNIQUE INDEX jobs_one_active_scan ON jobs (kind)
    WHERE kind = 'scan' AND status IN ('queued', 'paused', 'running');
CREATE INDEX jobs_claim ON jobs (status, refusals, priority DESC, id);
CREATE INDEX jobs_video ON jobs (video_id, id);
CREATE INDEX jobs_subscription ON jobs (subscription_id, id);
CREATE INDEX jobs_via_subscription ON jobs (via_subscription_id);

-- Videos that lost subtitles or chat to a refusal before this: one extras job each, from the
-- latest completed download that was refused, which kept its origin and options.
INSERT INTO jobs (kind, video_id, via_subscription_id, origin, options, priority)
SELECT 'extras', d.video_id, d.via_subscription_id, d.origin, d.options, 0
FROM jobs d
JOIN videos v ON v.id = d.video_id
WHERE d.kind = 'download' AND d.status = 'completed'
  AND json_extract(d.result, '$.refused') IS NOT NULL
  AND d.id = (
      SELECT max(id) FROM jobs
      WHERE kind = 'download' AND status = 'completed' AND video_id = d.video_id
  )
  AND v.media_path IS NOT NULL AND v.deleted_at IS NULL
ORDER BY d.id;

INSERT INTO events (event, actor, job_id, job_kind, video_id, subscription_id, detail)
SELECT
    'job.queued', 'app', id, kind, video_id, via_subscription_id,
    'origin ' || origin || '; subtitles or chat were lost to a refusal'
FROM jobs
WHERE kind = 'extras'
ORDER BY id;
