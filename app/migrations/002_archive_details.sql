-- Facts about the archived video and file, for display and filtering. The .info.json holds the rest.
ALTER TABLE videos ADD COLUMN availability TEXT;
ALTER TABLE videos ADD COLUMN age_limit INTEGER;
ALTER TABLE videos ADD COLUMN fps REAL;
-- Codec families: avc1, vp9, av01, hevc; mp4a, opus.
ALTER TABLE videos ADD COLUMN vcodec TEXT;
ALTER TABLE videos ADD COLUMN acodec TEXT;
ALTER TABLE videos ADD COLUMN dynamic_range TEXT;
-- JSON list of language codes for the audio tracks in the file, default first.
ALTER TABLE videos ADD COLUMN audio_languages TEXT;
ALTER TABLE videos ADD COLUMN comment_count INTEGER;
-- JSON list of {lang, name, source} for each saved subtitle track.
ALTER TABLE videos ADD COLUMN subtitle_tracks TEXT;

-- NULL means the library default.
ALTER TABLE subscriptions ADD COLUMN audio_languages TEXT;
ALTER TABLE subscriptions ADD COLUMN auto_captions INTEGER;
ALTER TABLE subscriptions ADD COLUMN live_chat INTEGER;
ALTER TABLE subscriptions ADD COLUMN sponsorblock INTEGER;

ALTER TABLE source_entries ADD COLUMN channel_youtube_id TEXT;
ALTER TABLE source_entries ADD COLUMN channel_name TEXT;
ALTER TABLE source_entries ADD COLUMN view_count INTEGER;

ALTER TABLE channels ADD COLUMN verified INTEGER NOT NULL DEFAULT 0;
-- Relative to MEDIA_DIR: channel.jpg and banner.jpg in the channel folder.
ALTER TABLE channels ADD COLUMN avatar_path TEXT;
ALTER TABLE channels ADD COLUMN banner_path TEXT;
