-- The rest of the gate's state, so a restart forgets nothing. Both are JSON objects keyed by kind:
-- for each kind of call ("download", "check", "lookup"), what the ones that failed in a row for
-- no particular reason were about; and when each kind of job may start again.
ALTER TABLE youtube_pause ADD COLUMN failures TEXT NOT NULL DEFAULT '{}';
ALTER TABLE youtube_pause ADD COLUMN rests TEXT NOT NULL DEFAULT '{}';
