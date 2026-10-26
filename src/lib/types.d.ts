export interface Page<T> {
  items: T[]
  total: number
  page: number
  per_page: number
}

export interface AuthStatus {
  authenticated: boolean
  username: string | null
  setup_required: boolean
}

export interface ChannelRef {
  id: number
  youtube_id: string
  name: string
  avatar_url?: string | null
}

export type VideoType = 'video' | 'short' | 'live'
export type VideoStatus = 'archived' | 'downloading' | 'queued' | 'failed' | 'deleted' | 'missing'
export type Availability =
  | 'public'
  | 'unlisted'
  | 'private'
  | 'needs_auth'
  | 'subscriber_only'
  | 'premium_only'

export interface Video {
  id: number
  youtube_id: string
  title: string
  description: string | null
  channel: ChannelRef | null
  duration: number | null
  /** "YYYY-MM-DDTHH:MM:SSZ" when YouTube gives the exact time, else "YYYY-MM-DD" */
  published_at: string | null
  view_count: number | null
  like_count: number | null
  video_type: VideoType
  status: VideoStatus
  job_id: number | null
  job: JobState | null
  error: string | null
  unavailable: boolean
  unavailable_at: string | null
  availability: Availability | null
  age_limit: number | null
  fps: number | null
  vcodec: string | null
  acodec: string | null
  dynamic_range: string | null
  audio_languages: string[] | null
  comment_count: number | null
  media_size: number | null
  width: number | null
  height: number | null
  quality: string | null
  media_path: string | null
  archived_at: string | null
  watched_at: string | null
  deleted_at: string | null
  created_at: string
  youtube_url: string
  thumbnail_url: string | null
  media_url: string
}

export type SubtitleSource = 'uploaded' | 'auto' | 'translated' | 'unknown'

export interface Subtitle {
  lang: string
  name: string | null
  source: SubtitleSource
  url: string
}

export interface Chapter {
  start: number
  end: number
  title: string
}

export interface HeatPoint {
  start: number
  end: number
  value: number
}

export interface SponsorSegment {
  start: number
  end: number
  category: string
}

export type FileKind = 'media' | 'info' | 'thumbnail' | 'subtitles' | 'chat' | 'other'

export interface VideoFile {
  path: string
  kind: FileKind
  size: number | null
}

export interface VideoDetail extends Video {
  tags?: string[] | null
  categories?: string[] | null
  chapters?: Chapter[] | null
  heatmap?: HeatPoint[] | null
  sponsor_segments?: SponsorSegment[] | null
  subtitles?: Subtitle[] | null
  files?: VideoFile[] | null
  comments?: { saved: number; url: string } | null
  chat_url?: string | null
  /** Set while a removed video's files are in the trash and can be restored. */
  trash?: { removed_at: string; expires_at: string } | null
}

export interface VideoQuery {
  q?: string
  status?: string
  video_type?: string
  channel_id?: number | string
  watched?: string
  unavailable?: string
  sort?: string
  order?: string
  page?: number
  per_page?: number
}

export interface VideoCounts {
  all: number
  archived: number
  downloading: number
  queued: number
  failed: number
  missing: number
  deleted: number
  unavailable: number
}

export interface VideoOptions {
  quality?: string
  subtitle_languages?: string[]
  auto_captions?: boolean
  download_comments?: boolean
  audio_languages?: string[]
  live_chat?: boolean
  sponsorblock?: boolean
}

export interface Comment {
  id: string
  text: string
  author: string | null
  author_id: string | null
  author_is_uploader: boolean
  author_is_verified: boolean
  is_pinned: boolean
  is_favorited: boolean
  like_count: number
  /** Unix seconds, and only as exact as YouTube's "2 years ago" */
  timestamp: number | null
  replies?: Comment[]
}

export interface CommentPage {
  items: Comment[]
  total: number
}

export interface ResolvedVideo {
  youtube_id: string
  title: string | null
  channel_name: string | null
  duration: number | null
  published_at: string | null
  live_status: string | null
  view_count: number | null
  existing: { video_id: number; status: VideoStatus } | null
}

export interface ChatMessage {
  t: number
  author: string
  text: string
}

export interface Channel {
  id: number
  youtube_id: string
  name: string
  handle: string | null
  description: string | null
  subscriber_count: number | null
  video_count: number
  archived_count: number
  archived_size: number
  subscription_id: number | null
  youtube_url: string
  verified?: boolean | null
  avatar_url?: string | null
  banner_url?: string | null
}

export type SubscriptionKind = 'channel' | 'playlist'
export type DownloadPolicy = 'none' | 'new' | 'recent' | 'all'

export interface SubscriptionCounts {
  entries: number
  archived: number
  queued: number
  failed: number
  not_selected: number
  removed: number
  deleted?: number
}

export interface CheckResult {
  listed: number
  new_entries: number
  removed: number
  queued: number
  full: boolean
}

export interface LastCheck {
  job_id: number
  status: JobStatus
  error: string | null
  finished_at: string | null
  result: CheckResult | null
}

export interface SubscriptionOptions {
  enabled?: boolean
  content_types?: VideoType[]
  download_policy?: DownloadPolicy
  recent_count?: number
  quality?: string | null
  subtitle_languages?: string[] | null
  download_comments?: boolean | null
  audio_languages?: string[] | null
  auto_captions?: boolean | null
  live_chat?: boolean | null
  sponsorblock?: boolean | null
  check_interval_hours?: number
}

export interface Subscription {
  id: number
  kind: SubscriptionKind
  youtube_id: string
  title: string
  url: string
  channel: ChannelRef | null
  owner_name: string | null
  enabled: boolean
  content_types: VideoType[]
  download_policy: DownloadPolicy
  recent_count: number
  quality: string | null
  subtitle_languages: string[] | null
  download_comments: boolean | null
  audio_languages: string[] | null
  auto_captions: boolean | null
  live_chat: boolean | null
  sponsorblock: boolean | null
  check_interval_hours: number
  next_check_at: string | null
  last_checked_at: string | null
  created_at: string
  counts: SubscriptionCounts
  last_check: LastCheck | null
  checking: boolean
}

export interface ResolvedSource {
  kind: SubscriptionKind
  youtube_id: string
  title: string
  url: string
  channel_name: string | null
  channel_handle?: string | null
  subscriber_count?: number | null
  owner_name: string | null
  existing_subscription_id: number | null
}

export type EntryStatus = VideoStatus | 'not_selected'

export interface Entry {
  youtube_id: string
  title: string | null
  video_type: VideoType
  duration: number | null
  position: number
  live_status: string | null
  first_seen_at: string
  removed_at: string | null
  video_id: number | null
  status: EntryStatus
  job: JobState | null
  channel_name?: string | null
  view_count?: number | null
}

export interface EntryQuery {
  status?: string
  video_type?: string
  q?: string
  page?: number
  per_page?: number
}

export type JobKind = 'download' | 'check' | 'scan'
export type JobStatus = 'queued' | 'paused' | 'running' | 'completed' | 'failed' | 'cancelled'
/** What a job list can filter by: `queued` is ready to run, `waiting` is queued until its `run_after`. */
export type JobFilter = JobStatus | 'waiting'

/** A video's download job while it is queued, paused or running. */
export interface JobState {
  status: JobStatus
  run_after: string | null
  attempts: number
  error: string | null
}

export interface JobProgress {
  phase: 'downloading' | 'processing'
  percent: number | null
  downloaded_bytes: number | null
  total_bytes: number | null
  speed: number | null
  eta: number | null
}

export interface Job {
  id: number
  kind: JobKind
  status: JobStatus
  priority: number
  attempts: number
  error: string | null
  result: Record<string, unknown> | null
  run_after: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  video: { id: number; title: string; youtube_id: string } | null
  subscription: { id: number; title: string } | null
  progress: JobProgress | null
}

export type JobCounts = Record<JobStatus, number> & { waiting: number }

export interface JobList {
  items: Job[]
  total: number
  counts: JobCounts
  /** Set while downloads and checks wait out a YouTube bot check. */
  youtube_paused_until: string | null
}

export interface JobQuery {
  /** Several filters match any of them. */
  status?: JobFilter | JobFilter[]
  kind?: string
  limit?: number
  offset?: number
}

export interface Language {
  code: string
  name: string
}

export interface SettingsOptions {
  qualities: string[]
  check_intervals: number[]
  trash_days: number[]
  policies: DownloadPolicy[]
  content_types: VideoType[]
  languages: Language[]
}

export interface Settings {
  default_quality: string
  subtitle_languages: string[]
  download_comments: boolean
  max_concurrent_downloads: number
  check_interval_hours: number
  audio_languages: string[]
  auto_captions: boolean
  live_chat: boolean
  sponsorblock: boolean
  /** Days removed files stay in the trash; 0 deletes them right away. */
  trash_days: number
  options: SettingsOptions
}

export type SettingsUpdate = Partial<Omit<Settings, 'options'>>

export interface SystemInfo {
  version: string
  yt_dlp: string
  ffmpeg: string | null
  js_runtime: string | null
  cookies: boolean
  media_dir: string
  disk: { total: number; used: number; free: number } | null
  library: {
    videos: number
    archived: number
    archived_size: number
    channels: number
    subscriptions: number
    unavailable: number
  }
  queue: { queued: number; running: number; failed: number }
  trash: { videos: number; size: number }
  youtube_paused_until: string | null
}
