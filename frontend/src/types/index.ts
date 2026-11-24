export type GameStatus = 'todo' | 'unplayed' | 'playing' | 'done' | 'completed'
export type ActiveStatusFilter = 'all' | 'playing' | 'unplayed' | 'completed'
export type GameEdition = 'standard' | 'collector'
export type LaunchMode = 'direct' | 'le' | 'cli'
export type ShelfViewMode = 'showcase' | 'spine'
export type ShelfBgMode = 'linked' | 'random' | 'minimal'
export type ImportTab =
  | 'aggregated'
  | 'ymgal'
  | 'kungal'
  | 'dlsite'
  | 'bgm'
  | 'bangumi'
  | 'vndb'
  | 'steam'
  | 'igdb'
  | 'tgal'
  | 'local'
export type ScraperCategory = 'all' | 'galgame' | 'general'
export type SettingsSectionId = 'general' | 'network' | 'sources' | 'data' | 'environment'
export type LibrarySortBy = 'series_name' | 'recent_played' | 'release_date' | 'play_time' | 'created_at'
export type LibrarySortOrder = 'asc' | 'desc'
export type MediaSaveMode = 'none' | 'link_only' | 'download'
export type CollectionType = 'series' | 'custom'
export type NoteType = 'work' | 'character' | 'misc'
export type RatingDimensionKey = 'story' | 'visual' | 'music' | 'atmosphere'

export interface RatingDimensions {
  story?: number
  visual?: number
  music?: number
  atmosphere?: number
  [key: string]: number | undefined
}

export interface CollectionWorkSummary {
  game_id: number
  title: string
  sub_title: string
  cover_thumb_url: string
  cover_path: string
  play_status: string
  is_nsfw: boolean
  rating_overall: number | null
  relation_label: string
  position: number
  added_at: string | null
}

export interface GameCollectionMembership {
  id: number
  name: string
  description: string
  collection_type: CollectionType | string
  relation_label: string
  position: number
  total_count: number
  completed_count: number
  items: CollectionWorkSummary[]
}

export interface CollectionItemInput {
  game_id: number
  relation_label?: string
}

export interface GameNote {
  id: number
  game_id: number
  note_type: NoteType | string
  title: string
  content_md: string
  is_pinned: boolean
  created_at: string
  updated_at: string
}

export interface GameMediaPath {
  cover_path: string
  cover_thumb_path: string
  logo_path: string
  hero_bg_path: string
  custom_spine_path: string
  pv_url_or_path: string
  pv_remote_url?: string
  pv_mode?: MediaSaveMode | string
  exe_path: string
  launch_mode: LaunchMode | string
  launch_args: string
  save_dir: string
  screenshot_dir: string
  bgm_path: string
  bgm_remote_url?: string
  bgm_mode?: MediaSaveMode | string
}

export interface PlayRecord {
  total_seconds: number
  last_played_at: string | null
}

export interface PlaySession {
  id: number
  game_id: number
  started_at: string
  duration_seconds: number
}

export interface Game {
  id: number
  title: string
  sub_title: string
  pinyin_initials: string
  developer: string
  publisher: string
  release_date: string
  synopsis: string
  tags: string[]
  external_ids: Record<string, string>
  locked_fields: string[]
  bangumi_id: string
  series: string
  rating_overall?: number | null
  rating_dimensions?: RatingDimensions | null
  short_review?: string
  status: GameStatus | string
  edition: GameEdition | string
  is_nsfw: boolean
  source_platform: string
  created_at: string
  media: GameMediaPath | null
  play_record: PlayRecord | null
  notes_count?: number
  collections?: GameCollectionMembership[]
  cover_thumb_url?: string
  background_thumb_url?: string
}

export interface GameCreatePayload {
  title: string
  sub_title?: string
  developer?: string
  publisher?: string
  release_date?: string
  synopsis?: string
  tags?: string[]
  status?: GameStatus | string
  edition?: GameEdition | string
  is_nsfw?: boolean
  source_platform?: string
  bangumi_id?: string
  series?: string
  external_ids?: Record<string, string>
  locked_fields?: string[]
  media?: Partial<GameMediaPath>
}

export interface GameUpdatePayload {
  title?: string
  sub_title?: string
  developer?: string
  publisher?: string
  release_date?: string
  synopsis?: string
  tags?: string[]
  status?: GameStatus | string
  edition?: GameEdition | string
  is_nsfw?: boolean
  source_platform?: string
  bangumi_id?: string
  series?: string
  external_ids?: Record<string, string>
  locked_fields?: string[]
  media?: Partial<GameMediaPath>
}

export interface ApiKeysConfig {
  steamgriddb: string
  touchgal: string
  bangumi: string
  [key: string]: string
}

export interface ScraperSourceDescriptor {
  id: string
  name: string
  short_name: string
  description: string
  requires_key: boolean
  is_free: boolean
  enabled: boolean
  configured: boolean
  available: boolean
  categories: string[]
  doc_url: string
  doc_hint: string
}

export interface ScraperSettingsResponse {
  enabled_sources: Record<string, boolean>
  ymgal_client_id: string
  ymgal_client_secret: string
  kungal_base_url: string
  kungal_token: string
  bangumi_token: string
  touchgal_api_key: string
  steamgriddb_api_key: string
  igdb_client_id: string
  igdb_client_secret: string
  configured_secrets: Record<string, boolean>
  source_status: Record<
    string,
    {
      enabled: boolean
      configured: boolean
      requires_key: boolean
    }
  >
  settings_file?: string
  sources?: ScraperSourceDescriptor[]
  source_links?: Record<string, string>
}

export interface ScraperSettingsUpdatePayload {
  enabled_sources?: Record<string, boolean>
  ymgal_client_id?: string | null
  ymgal_client_secret?: string | null
  kungal_base_url?: string | null
  kungal_token?: string | null
  bangumi_token?: string | null
  touchgal_api_key?: string | null
  steamgriddb_api_key?: string | null
  igdb_client_id?: string | null
  igdb_client_secret?: string | null
  clear_fields?: string[]
}

export interface ScraperTestResponse {
  ok: boolean
  source: string
  latency_ms: number
  sample_count?: number
  detail: string
}

export interface ScraperEnrichDescriptionItem {
  source: string
  source_name: string
  source_id: string
  source_url: string
  title: string
  original_title: string
  description: string
  developers: string[]
  publishers: string[]
  release_date: string
  tags: string[]
  has_chinese: boolean
  external_ids: Record<string, string>
}

export interface ScraperEnrichVisualItem {
  id: string
  source: string
  source_name: string
  url: string
  thumb_url: string
  title: string
  width: number | null
  height: number | null
  kind: 'cover' | 'background' | 'logo' | string
}

export interface ScraperEnrichResponse {
  descriptions: ScraperEnrichDescriptionItem[]
  covers: ScraperEnrichVisualItem[]
  backgrounds: ScraperEnrichVisualItem[]
  logos: ScraperEnrichVisualItem[]
  merged_external_ids: Record<string, string>
  sgdb_configured: boolean
  warnings: string[]
}

export interface AppSettings {
  last_active_game_id: number | null
  shelf_view_mode: ShelfViewMode | string
  shelf_bg_mode: ShelfBgMode | string
  bgm_autoplay: boolean
  gallery_particles: boolean
  proxy_url: string
  le_exe_path: string
  bangumi_token?: string
  api_keys: ApiKeysConfig
  scraper_settings?: ScraperSettingsResponse
  allow_nsfw_scrape: boolean
  privacy_blur_mode: boolean
  library_sort_by?: LibrarySortBy | string
  library_sort_order?: LibrarySortOrder | string
  source_links?: {
    ymgal?: string
    kungal?: string
    bangumi?: string
    touchgal?: string
    steamgriddb?: string
    igdb?: string
    [key: string]: string | undefined
  }
}

export interface ScrapedGameItem {
  source: string
  source_id?: string
  source_label?: string
  source_url?: string
  external_id: string
  title: string
  original_title?: string
  sub_title: string
  aliases?: string[]
  developers?: string[]
  publishers?: string[]
  developer: string
  publisher: string
  release_date: string
  description?: string
  synopsis: string
  tags: string[]
  is_nsfw: boolean
  rating?: number | null
  cover_url: string
  logo_url: string
  background_url?: string
  hero_bg_url: string
  pv_url: string
  screenshots: string[]
  external_ids?: Record<string, string>
  extra_ids: Record<string, string>
  bangumi_id?: string
  match_score?: number
  direct_hit?: boolean
  already_in_library?: boolean
  existing_game_id?: number | null
}

export interface ScraperSearchResponse {
  source: string
  category?: ScraperCategory
  sources?: string[]
  query: string
  direct_match?: { source: string; source_id: string } | null
  count: number
  sgdb_configured: boolean
  igdb_configured?: boolean
  touchgal_configured?: boolean
  available_sources?: ScraperSourceDescriptor[]
  source_errors?: Record<string, string>
  items: ScrapedGameItem[]
}

export interface ScraperAggregateResponse {
  item: ScrapedGameItem
  matched_sources: string[]
  sources_detail: Record<string, ScrapedGameItem>
}

export interface ScraperImportPayload {
  title: string
  sub_title: string
  developer: string
  publisher: string
  release_date: string
  synopsis: string
  tags: string[]
  status: string
  edition: string
  is_nsfw: boolean
  source_platform: string
  bangumi_id?: string
  external_ids: Record<string, string>
  cover_url: string
  logo_url: string
  hero_bg_url: string
  pv_url: string
  pv_mode?: MediaSaveMode
  selected_pv_url?: string | null
  selected_pv_source?: string | null
  selected_pv_mime_hint?: string | null
  selected_pv_fallback_urls?: string[]
  op_mode?: MediaSaveMode
  selected_bgm_url?: string | null
  screenshots: string[]
  download_screenshots?: boolean
  auto_fetch_bgm?: boolean
  exe_path: string
  launch_mode: string
  launch_args: string
  save_dir: string
  screenshot_dir: string
}

export interface RunningStatus {
  running: boolean
  game_id: number | null
  title: string
  elapsed_seconds: number
  total_seconds: number
  pid: number | null
  is_mock: boolean
  started_at: string | null
  platform: string
}

export interface ScreenshotItem {
  name: string
  path: string
  mtime: number
}

export interface BackupItem {
  game_id: number
  filename: string
  path: string
  size_bytes: number
  created_at: string
  file_count?: number
}

export interface BatchScanCandidate {
  folder_name: string
  folder_path: string
  clean_title: string
  suggested_exe: string
  candidate_exes: string[]
  detected_save_dir: string
  detected_screenshot_dir: string
  already_imported: boolean
}

export interface BatchImportItemPayload {
  title: string
  folder_path: string
  exe_path: string
  launch_mode: string
  save_dir: string
  screenshot_dir: string
  edition: string
}

export interface HealthInfo {
  status: string
  os_adapter: string
  db_file: string
  initialized_tables: string[]
  frontend_dist_ready: boolean
  running_game: RunningStatus
}

export interface DroppedFileInfo {
  kind: string
  folder_path: string
  exe_path: string
  suggested_title: string
}

export interface ToastMessage {
  id: number
  message: string
  type: 'info' | 'success' | 'warning' | 'error'
  actionLabel?: string
  onAction?: () => void
}

export interface PathBrowseEntry {
  name: string
  path: string
  is_dir: boolean
}

export interface PathBrowseResponse {
  current_dir: string
  parent_dir: string | null
  platform: string
  entries: PathBrowseEntry[]
}

export interface PathValidateResponse {
  valid: boolean
  exists: boolean
  is_uri: boolean
  is_file: boolean
  normalized_path: string
  platform: string
}

export interface RandomBackdropResponse {
  path?: string
  source?: string
  game_id?: number | null
  thumb_url?: string
  pool_size?: number
}

export interface MusicCandidate {
  id: string
  title: string
  artist: string
  source: string
  duration: number
  thumbnail: string
  preview_url: string
  source_url: string
}

export interface MusicSearchResponse {
  query: string
  source?: string
  count: number
  items: MusicCandidate[]
}

export type PickerAssetType = 'cover' | 'logo' | 'hero' | 'spine' | 'pv'
export type AssetRole = 'hero' | 'cover'

export interface AssetCandidate {
  id: string
  url: string
  fallback_urls?: string[]
  thumb_url: string
  source: string
  platform?: string
  is_official?: boolean
  title: string
  width: number | null
  height: number | null
  duration: number | null
  mime_hint: 'image' | 'hls' | 'mp4' | 'webm' | 'dash' | 'video_page' | string
  asset_role?: AssetRole | null
  asset_roles?: AssetRole[]
}

export interface AssetSearchResponse {
  asset_type: PickerAssetType
  query: string
  source: string
  count: number
  sgdb_configured: boolean
  steam_empty?: boolean
  warnings: string[]
  items: AssetCandidate[]
}

export interface AssetApplyPayload {
  asset_type: PickerAssetType
  url: string
  source?: string
  mime_hint?: string
  fallback_urls?: string[]
  mode?: MediaSaveMode
  async_mode?: boolean
}

export interface DownloadTaskItem {
  game_id: number
  asset_type: 'pv' | 'bgm' | string
  status: 'queued' | 'downloading' | 'done' | 'error' | string
  progress: number | null
  message: string
  updated_at: string
}

export interface DownloadTasksResponse {
  count: number
  items: DownloadTaskItem[]
}

export type AssetApplyResponse = Game & {
  download_task?: DownloadTaskItem
}

export interface StorageBucket {
  bytes: number
  files: number
  dirs?: number
}

export interface AutoSnapshotItem {
  filename: string
  created_at: string
  size_bytes: number
  tag: 'auto' | 'pre_restore' | 'pre_import' | string
  tag_label: string
}

export interface StorageUsageResponse {
  videos: StorageBucket
  audios: StorageBucket
  images: StorageBucket
  thumbs?: StorageBucket
  backups: StorageBucket
  database: StorageBucket
  orphans: StorageBucket
  total_bytes: number
  total_files: number
  db_bytes?: number
  images_bytes?: number
  videos_bytes?: number
  audios_bytes?: number
  thumbs_bytes?: number
  backups_bytes?: number
  snapshots?: AutoSnapshotItem[]
}

export interface ClearThumbsResponse {
  cleared: boolean
  deleted_files: number
  freed_bytes: number
}

export interface LibraryBackupManifest {
  app?: string
  app_version?: string
  backup_version?: number
  created_at?: string
  game_count?: number
  include_videos?: boolean
  files_count?: number
}

export interface LibraryBackupExportResponse {
  exported: boolean
  filename: string
  path: string
  size_bytes: number
  file_count: number
  manifest: LibraryBackupManifest
}

export interface LibraryBackupRestoreResponse {
  restored: boolean
  safety_snapshot: string | null
  manifest?: LibraryBackupManifest
  removed_sidecars?: string[]
  restored_assets?: number
  cleared_thumbs?: number
}

export interface SnapshotRestoreResponse {
  restored: boolean
  filename: string
  safety_snapshot: string | null
  removed_sidecars?: string[]
  cleared_thumbs?: number
}

export interface StorageCleanupResponse {
  deleted_files: number
  deleted_dirs: number
  freed_bytes: number
}

export interface ConvertWebpResponse {
  converted_count: number
  saved_bytes: number
  skipped_count: number
}

export interface AppVersionInfo {
  current_version: string
  github_repo: string
  repo_url: string
}

export type UpdateCheckStatus =
  | 'update_available'
  | 'up_to_date'
  | 'not_published'
  | 'rate_limited'
  | 'error'

export interface UpdateCheckResponse {
  status: UpdateCheckStatus
  current_version: string
  latest_version?: string
  release_name?: string
  release_notes?: string
  published_at?: string
  release_url?: string
  download_url?: string
  message: string
}

export interface BangumiMeResponse {
  valid: boolean
  username?: string
  nickname?: string
  avatar?: string
  detail?: string
}

export interface BangumiSyncResponse {
  synced: boolean
  bangumi_id: string
  local_status: string
  bangumi_type: number
  bangumi_type_label: string
}

export type MetadataSourceKey =
  | 'ymgal'
  | 'kungal'
  | 'dlsite'
  | 'vndb'
  | 'bangumi'
  | 'steam'
  | 'igdb'
  | 'touchgal'

export type MetadataFieldKey =
  | 'title'
  | 'sub_title'
  | 'developer'
  | 'publisher'
  | 'release_date'
  | 'bangumi_id'
  | 'tags'
  | 'description'

export interface MetadataCandidateItem {
  external_id: string
  source: MetadataSourceKey
  title: string
  sub_title: string
  developer: string
  release_date: string
  cover_url: string
  description_preview: string
}

export interface MetadataSearchResponse {
  source: MetadataSourceKey
  query: string
  count: number
  items: MetadataCandidateItem[]
}

export interface MetadataDetailResponse {
  source: MetadataSourceKey
  external_id: string
  title: string
  sub_title: string
  developer: string
  publisher: string
  release_date: string
  tags: string[]
  description: string
  bangumi_id: string
  is_nsfw: boolean
}

export interface MetadataApplyPatch {
  title?: string
  sub_title?: string
  developer?: string
  publisher?: string
  release_date?: string
  bangumi_id?: string
  tags?: string[]
  tagsMode?: 'replace' | 'merge'
  description?: string
}

export interface CollectionItem {
  id: number
  name: string
  description: string
  collection_type: CollectionType | string
  sort_order: number
  created_at: string | null
  updated_at?: string | null
  game_ids: number[]
  items: CollectionWorkSummary[]
  total_count: number
  completed_count: number
  playing_count: number
  unplayed_count: number
}

export interface LedgerDayGame {
  game_id: number
  title: string
  duration_seconds: number
}

export interface LedgerHeatmapDay {
  date: string
  total_seconds: number
  sessions_count: number
  games: LedgerDayGame[]
}

export interface LedgerMonthlyItem {
  month: string
  total_seconds: number
  sessions_count: number
}

export interface LedgerTopGame {
  game_id: number
  title: string
  developer: string
  status: string
  is_nsfw: boolean
  cover_thumb_path: string
  total_seconds: number
  session_count: number
  first_played_at: string | null
  last_played_at: string | null
}

export interface LedgerRecentSession {
  id: number
  game_id: number
  title: string
  is_nsfw: boolean
  cover_thumb_path: string
  started_at: string
  duration_seconds: number
}

export interface TimeLedgerResponse {
  days: number
  summary: {
    total_seconds: number
    total_sessions: number
    total_games: number
    done_games: number
    playing_games: number
    active_days: number
    longest_streak: number
    current_streak: number
  }
  heatmap: LedgerHeatmapDay[]
  monthly: LedgerMonthlyItem[]
  top_games: LedgerTopGame[]
  recent_sessions: LedgerRecentSession[]
}

export interface CollageGameItem {
  id: number
  title: string
  sub_title: string
  play_seconds: number
  status: string
  is_nsfw: boolean
  cover_path: string
  cover_thumb_path: string
  hero_bg_path: string
}

export interface JourneyCollageResponse {
  year: string
  available_years: string[]
  total_seconds: number
  played_games_count: number
  total_games_count: number
  items: CollageGameItem[]
}

export type ExternalImportSource = 'playnite' | 'vnite'
export type ExternalDuplicateStrategy = 'skip' | 'merge_playtime'

export interface ExternalDetectResponse {
  source?: ExternalImportSource
  found?: boolean
  path?: string
  detected_path?: string
  valid?: boolean
  message: string
  candidates?: string[]
}

export interface ExternalGameCandidate {
  external_id: string
  source_app: ExternalImportSource
  name: string
  original_name: string
  description: string
  release_date: string
  developers: string[]
  publishers: string[]
  tags: string[]
  playtime_seconds: number
  last_played_at: string | null
  play_status: string
  platform_source: string
  steam_appid: string
  vndb_id: string
  bangumi_id: string
  ymgal_id?: string
  install_dir: string
  executable_path: string
  cover_path: string
  background_path: string
  exists_in_tsumugi: boolean
  existing_game_id: number | null
}

export interface ExternalScanResponse {
  source: ExternalImportSource
  path: string
  stats: {
    total: number
    new: number
    existing: number
  }
  items: ExternalGameCandidate[]
}

export interface ExternalImportErrorItem {
  external_id: string
  name: string
  error: string
}

export interface ExternalExecuteResponse {
  source: ExternalImportSource
  imported: number
  merged: number
  skipped: number
  errors: ExternalImportErrorItem[]
  imported_ids: number[]
  merged_ids: number[]
}
