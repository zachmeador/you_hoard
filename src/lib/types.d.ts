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
}

export type VideoType = 'video' | 'short' | 'live'
export type VideoStatus = 'archived' | 'downloading' | 'queued' | 'failed' | 'deleted' | 'missing'

export interface Video {
  id: number
  youtube_id: string
  title: string
  description: string | null
  channel: ChannelRef | null
  duration: number | null
  published_at: string | null
  view_count: number | null
  like_count: number | null
  video_type: VideoType
  status: VideoStatus
  job_id: number | null
  error: string | null
  unavailable: boolean
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
  thumbnail_url: string
  media_url: string
}

export interface Subtitle {
  lang: string
  url: string
}

export interface VideoDetail extends Video {
  subtitles: Subtitle[]
}

export interface VideoQuery {
  q?: string
  status?: string
  video_type?: string
  channel_id?: number | string
  watched?: string
  sort?: string
  order?: string
  page?: number
  per_page?: number
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

export type JobCounts = Record<JobStatus, number>

export interface JobList {
  items: Job[]
  total: number
  counts: JobCounts
}

export interface JobQuery {
  status?: string
  kind?: string
  limit?: number
  offset?: number
}

export interface SettingsOptions {
  qualities: string[]
  check_intervals: number[]
  policies: DownloadPolicy[]
  content_types: VideoType[]
}

export interface Settings {
  default_quality: string
  subtitle_languages: string[]
  download_comments: boolean
  max_concurrent_downloads: number
  check_interval_hours: number
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
}
