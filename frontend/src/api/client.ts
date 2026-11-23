import type {
  AppSettings,
  AppVersionInfo,
  AssetApplyPayload,
  AssetApplyResponse,
  AssetSearchResponse,
  BackupItem,
  BangumiMeResponse,
  BangumiSyncResponse,
  BatchImportItemPayload,
  BatchScanCandidate,
  CollectionItem,
  ConvertWebpResponse,
  DownloadTasksResponse,
  ExternalDetectResponse,
  ExternalDuplicateStrategy,
  ExternalExecuteResponse,
  ExternalImportSource,
  ExternalScanResponse,
  Game,
  GameCreatePayload,
  GameUpdatePayload,
  HealthInfo,
  JourneyCollageResponse,
  MediaSaveMode,
  MetadataDetailResponse,
  MetadataSearchResponse,
  MetadataSourceKey,
  MusicSearchResponse,
  PathBrowseResponse,
  PathValidateResponse,
  PickerAssetType,
  PlaySession,
  RandomBackdropResponse,
  RunningStatus,
  ScrapedGameItem,
  ScraperAggregateResponse,
  ScraperCategory,
  ScraperEnrichResponse,
  ScraperImportPayload,
  ScraperSearchResponse,
  ScraperSettingsResponse,
  ScraperSettingsUpdatePayload,
  ScraperSourceDescriptor,
  ScraperTestResponse,
  ScreenshotItem,
  StorageCleanupResponse,
  StorageUsageResponse,
  TimeLedgerResponse,
  UpdateCheckResponse,
} from '@/types'

export class ApiError extends Error {
  status: number
  code?: string
  constructor(message: string, status: number, code?: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const isFormData = options.body instanceof FormData
  const headers: Record<string, string> = {}
  if (!isFormData) {
    headers['Content-Type'] = 'application/json'
  }
  if (options.headers) {
    Object.assign(headers, options.headers)
  }

  const res = await fetch(url, { ...options, headers })
  if (!res.ok) {
    let detail = `请求失败 (${res.status})`
    let code: string | undefined
    try {
      const errBody = await res.json()
      if (typeof errBody?.code === 'string') {
        code = errBody.code
      }
      if (errBody?.detail) {
        detail = typeof errBody.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail)
      }
    } catch {
      // ignore json parse failure
    }
    throw new ApiError(detail, res.status, code)
  }
  return (await res.json()) as T
}

export function assetUrl(relOrUrl?: string | null, cacheBust?: string | number): string {
  if (!relOrUrl) return ''
  const trimmed = relOrUrl.trim()
  if (!trimmed) return ''
  if (trimmed.startsWith('http://') || trimmed.startsWith('https://') || trimmed.startsWith('/static/')) {
    return trimmed
  }
  const clean = trimmed.replace(/^\/+/, '')
  const base = `/static/data/${clean}`
  return cacheBust ? `${base}?v=${cacheBust}` : base
}

export function thumbUrl(path: string, width = 400, cacheBust?: string | number): string {
  const base = `/api/media/thumb?path=${encodeURIComponent(path)}&width=${width}`
  return cacheBust ? `${base}&v=${cacheBust}` : base
}

export function rawImageUrl(path: string): string {
  return `/api/media/raw?path=${encodeURIComponent(path)}`
}

export function audioUrl(path: string, cacheBust?: string | number): string {
  const base = `/api/media/audio?path=${encodeURIComponent(path)}`
  return cacheBust ? `${base}&v=${cacheBust}` : base
}

export function videoUrl(path: string, cacheBust?: string | number): string {
  const base = `/api/media/video?path=${encodeURIComponent(path)}`
  return cacheBust ? `${base}&v=${cacheBust}` : base
}

export function videoStreamUrl(url: string): string {
  return `/api/media/video-stream?url=${encodeURIComponent(url)}`
}

export function musicPreviewUrl(url: string): string {
  return `/api/scraper/music/preview?url=${encodeURIComponent(url)}`
}

export function assetProxyUrl(url: string): string {
  return `/api/scraper/assets/proxy?url=${encodeURIComponent(url)}`
}

export function isDesktopBridgeAvailable(): boolean {
  return Boolean(window.pywebview?.api)
}

export async function pickNativeFile(title?: string, fileTypes?: string[]): Promise<string | null> {
  const fn = window.pywebview?.api?.pick_file
  if (!fn) return null
  try {
    return (await fn(title, fileTypes)) || ''
  } catch {
    return null
  }
}

export async function pickNativeFolder(title?: string): Promise<string | null> {
  const fn = window.pywebview?.api?.pick_folder
  if (!fn) return null
  try {
    return (await fn(title)) || ''
  } catch {
    return null
  }
}

export const systemApi = {
  health: () => request<HealthInfo>('/api/health'),
  version: () => request<AppVersionInfo>('/api/system/version'),
  checkUpdate: () => request<UpdateCheckResponse>('/api/system/check-update'),
  storage: () => request<StorageUsageResponse>('/api/system/storage'),
  cleanupStorage: () =>
    request<StorageCleanupResponse>('/api/system/storage/cleanup', { method: 'POST' }),
  convertWebp: () =>
    request<ConvertWebpResponse>('/api/system/storage/convert-webp', { method: 'POST' }),
  sourceLinks: () => request<Record<string, string>>('/api/system/source-links'),
  getScraperSettings: () => request<ScraperSettingsResponse>('/api/system/scraper-settings'),
  updateScraperSettings: (payload: ScraperSettingsUpdatePayload) =>
    request<ScraperSettingsResponse>('/api/system/scraper-settings', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
}

export const tasksApi = {
  downloads: (gameId?: number) => {
    const qs = gameId != null ? `?game_id=${encodeURIComponent(String(gameId))}` : ''
    return request<DownloadTasksResponse>(`/api/tasks/downloads${qs}`)
  },
}

export const gamesApi = {
  list: (params?: { status?: string; collection_id?: number; tag?: string; q?: string }) => {
    const qs = new URLSearchParams()
    if (params?.status && params.status !== 'all') qs.set('status', params.status)
    if (params?.collection_id != null) qs.set('collection_id', String(params.collection_id))
    if (params?.tag) qs.set('tag', params.tag)
    if (params?.q) qs.set('q', params.q)
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return request<Game[]>(`/api/games${suffix}`)
  },
  get: (id: number, recordActive = true) =>
    request<Game>(`/api/games/${id}?record_active=${recordActive ? 'true' : 'false'}`),
  create: (payload: GameCreatePayload) =>
    request<Game>('/api/games', { method: 'POST', body: JSON.stringify(payload) }),
  update: (id: number, payload: GameUpdatePayload) =>
    request<Game>(`/api/games/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  remove: (id: number) =>
    request<{ status: string; game_id: number }>(`/api/games/${id}`, { method: 'DELETE' }),
  launch: (id: number) =>
    request<{
      game_id: number
      title: string
      status: string
      mode: string
      target: string
      pid: number
      message: string
      tracker: RunningStatus
    }>(`/api/games/${id}/launch`, { method: 'POST' }),
  sessions: (id: number, limit = 20) =>
    request<PlaySession[]>(`/api/games/${id}/sessions?limit=${limit}`),
  syncBangumi: (id: number, bangumiId?: string) =>
    request<BangumiSyncResponse>(`/api/games/${id}/sync/bangumi`, {
      method: 'POST',
      body: JSON.stringify(bangumiId ? { bangumi_id: bangumiId } : {}),
    }),
}

export const settingsApi = {
  getAll: () => request<AppSettings>('/api/settings'),
  update: <K extends keyof AppSettings>(key: K, value: AppSettings[K]) =>
    request<{ key: string; value: AppSettings[K] }>(`/api/settings/${String(key)}`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    }),
}

export const mediaApi = {
  upload: (
    gameId: number,
    assetType: 'cover' | 'logo' | 'hero' | 'custom_spine' | 'pv' | 'bgm',
    file: File,
  ) => {
    const form = new FormData()
    form.append('file', file)
    return request<{ game_id: number; asset_type: string; path: string; thumb_path?: string }>(
      `/api/media/upload/${gameId}?asset_type=${assetType}`,
      { method: 'POST', body: form },
    )
  },
  dropLocalCache: (gameId: number, assetType: 'pv' | 'bgm') =>
    request<Game>(`/api/media/drop-local-cache/${gameId}?asset_type=${assetType}`, {
      method: 'POST',
    }),
  cacheRemote: (gameId: number, assetType: 'pv' | 'bgm') =>
    request<AssetApplyResponse>(`/api/media/cache-remote/${gameId}?asset_type=${assetType}`, {
      method: 'POST',
    }),
  screenshots: (gameId: number) =>
    request<{ game_id: number; items: ScreenshotItem[] }>(`/api/media/screenshots/${gameId}`),
  randomBackdrop: (excludeNsfw = true) =>
    request<RandomBackdropResponse>(
      `/api/media/random-backdrop?exclude_nsfw=${excludeNsfw ? 'true' : 'false'}`,
    ),
  openFolder: (gameId: number, target: 'save' | 'screenshot' | 'game') =>
    request<{ opened: boolean; path: string; adapter: string }>(
      `/api/media/open-folder/${gameId}?target=${target}`,
      { method: 'POST' },
    ),
  searchPv: (
    q: string,
    opts?: { source?: string; steam_appid?: string; alt_title?: string },
  ) => {
    const qs = new URLSearchParams()
    qs.set('q', q)
    qs.set('source', opts?.source || 'auto')
    if (opts?.steam_appid) qs.set('steam_appid', opts.steam_appid)
    if (opts?.alt_title) qs.set('alt_title', opts.alt_title)
    return request<AssetSearchResponse>(`/api/media/search-pv?${qs.toString()}`)
  },
}

export const scraperApi = {
  sources: () =>
    request<{
      sources: ScraperSourceDescriptor[]
      sgdb_configured: boolean
      igdb_configured: boolean
      touchgal_configured?: boolean
    }>('/api/scraper/sources'),
  testSource: (
    source: string,
    overrides?: Partial<{
      ymgal_client_id: string
      ymgal_client_secret: string
      kungal_base_url: string
      kungal_token: string
      bangumi_token: string
      touchgal_api_key: string
      steamgriddb_api_key: string
      igdb_client_id: string
      igdb_client_secret: string
    }>,
  ) =>
    request<ScraperTestResponse>(`/api/scraper/test/${encodeURIComponent(source)}`, {
      method: 'POST',
      body: JSON.stringify(overrides || {}),
    }),
  search: (
    q: string,
    sourceOrOpts:
      | string
      | {
          category?: ScraperCategory
          sources?: string[]
          limit?: number
        } = 'aggregated',
    limit = 15,
  ) => {
    const qs = new URLSearchParams()
    qs.set('q', q)
    if (typeof sourceOrOpts === 'string') {
      qs.set('source', sourceOrOpts)
      qs.set('limit', String(limit))
    } else {
      if (sourceOrOpts.category) qs.set('category', sourceOrOpts.category)
      if (sourceOrOpts.sources && sourceOrOpts.sources.length > 0) {
        for (const s of sourceOrOpts.sources) {
          qs.append('sources', s)
        }
      }
      qs.set('limit', String(sourceOrOpts.limit ?? limit))
    }
    return request<ScraperSearchResponse>(`/api/scraper/search?${qs.toString()}`)
  },
  detail: (source: string, externalId: string) =>
    request<ScrapedGameItem>(
      `/api/scraper/detail/${encodeURIComponent(source)}/${encodeURIComponent(externalId)}`,
    ),
  enrich: (payload: {
    title: string
    original_title?: string
    aliases?: string[]
    release_date?: string
    source?: string
    source_id?: string
    external_ids?: Record<string, string>
    target_sources?: string[]
    mode?: 'all' | 'description' | 'covers'
  }) =>
    request<ScraperEnrichResponse>('/api/scraper/enrich', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  aggregate: (keyword: string, externalIds: Record<string, string> = {}, preferredSource = '') =>
    request<ScraperAggregateResponse>('/api/scraper/aggregate', {
      method: 'POST',
      body: JSON.stringify({
        keyword,
        external_ids: externalIds,
        preferred_source: preferredSource,
      }),
    }),
  importGame: (payload: ScraperImportPayload) =>
    request<Game>('/api/scraper/import', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  refresh: (gameId: number) =>
    request<Game>(`/api/scraper/refresh/${gameId}`, { method: 'POST' }),
  searchMusic: (q: string, opts?: { source?: string; alt_title?: string }) => {
    const qs = new URLSearchParams()
    qs.set('q', q)
    if (opts?.source) qs.set('source', opts.source)
    if (opts?.alt_title) qs.set('alt_title', opts.alt_title)
    return request<MusicSearchResponse>(`/api/scraper/music/search?${qs.toString()}`)
  },
  downloadMusic: (
    gameId: number,
    payload: {
      source_url?: string
      preview_url?: string
      mode?: MediaSaveMode
      async_mode?: boolean
    },
  ) =>
    request<{
      game_id: number
      bgm_path: string
      bgm_remote_url?: string
      bgm_mode?: string
      download_task?: DownloadTasksResponse['items'][number]
    }>(`/api/scraper/music/download/${gameId}`, {
      method: 'POST',
      body: JSON.stringify({
        source_url: payload.source_url || '',
        preview_url: payload.preview_url || '',
        mode: payload.mode || 'download',
        async_mode: Boolean(payload.async_mode),
      }),
    }),
  searchAssets: (
    assetType: PickerAssetType,
    q: string,
    source = 'all',
    opts?: { steam_appid?: string; alt_title?: string },
  ) => {
    const qs = new URLSearchParams()
    qs.set('asset_type', assetType)
    qs.set('q', q)
    qs.set('source', source)
    if (opts?.steam_appid) qs.set('steam_appid', opts.steam_appid)
    if (opts?.alt_title) qs.set('alt_title', opts.alt_title)
    return request<AssetSearchResponse>(`/api/scraper/assets/search?${qs.toString()}`)
  },
  applyAsset: (gameId: number, payload: AssetApplyPayload) =>
    request<AssetApplyResponse>(`/api/scraper/assets/apply/${gameId}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  verifyBangumiMe: (token?: string) => {
    const cleaned = (token || '').trim()
    const qs = cleaned ? `?token=${encodeURIComponent(cleaned)}` : ''
    return request<BangumiMeResponse>(`/api/scraper/bangumi/me${qs}`)
  },
  searchMetadata: (q: string, source: MetadataSourceKey, limit = 10) =>
    request<MetadataSearchResponse>(
      `/api/scraper/metadata/search?q=${encodeURIComponent(q)}&source=${encodeURIComponent(source)}&limit=${limit}`,
    ),
  detailMetadata: (source: MetadataSourceKey, externalId: string) =>
    request<MetadataDetailResponse>(
      `/api/scraper/metadata/detail?source=${encodeURIComponent(source)}&external_id=${encodeURIComponent(externalId)}`,
    ),
}

export const libraryApi = {
  running: () => request<RunningStatus>('/api/library/running'),
  stopRunning: (terminateProcess = false) =>
    request<{
      stopped: boolean
      game_id?: number
      title?: string
      session_seconds?: number
      total_seconds?: number
      message: string
    }>('/api/library/running/stop', {
      method: 'POST',
      body: JSON.stringify({ terminate_process: terminateProcess }),
    }),
  scanDirectory: (rootDir: string) =>
    request<{ root_dir: string; count: number; items: BatchScanCandidate[] }>(
      '/api/library/scan-directory',
      { method: 'POST', body: JSON.stringify({ root_dir: rootDir }) },
    ),
  batchImport: (items: BatchImportItemPayload[], autoScrape = true) =>
    request<{ imported_count: number; imported_ids: number[]; errors: { title: string; error: string }[] }>(
      '/api/library/batch-import',
      { method: 'POST', body: JSON.stringify({ items, auto_scrape: autoScrape }) },
    ),
  listBackups: (gameId: number) =>
    request<{ game_id: number; items: BackupItem[] }>(`/api/library/backups/${gameId}`),
  createBackup: (gameId: number, note = '') =>
    request<BackupItem>(`/api/library/backups/${gameId}`, {
      method: 'POST',
      body: JSON.stringify({ note }),
    }),
  deleteBackup: (gameId: number, filename: string) =>
    request<{ deleted: boolean; filename: string }>(
      `/api/library/backups/${gameId}/${encodeURIComponent(filename)}`,
      { method: 'DELETE' },
    ),
  restoreBackup: (gameId: number, filename: string) =>
    request<{ restored: boolean; filename: string; restored_files: number; safety_backup: string | null }>(
      `/api/library/backups/${gameId}/${encodeURIComponent(filename)}/restore`,
      { method: 'POST' },
    ),
  browsePath: (path = '', extensions: string[] = []) =>
    request<PathBrowseResponse>('/api/library/browse-path', {
      method: 'POST',
      body: JSON.stringify({ path, extensions }),
    }),
  validatePath: (path: string) =>
    request<PathValidateResponse>('/api/library/validate-path', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),
}

export const externalImportApi = {
  detect: (source: ExternalImportSource) =>
    request<ExternalDetectResponse>(`/api/import/external/${encodeURIComponent(source)}/detect`),
  scan: (source: ExternalImportSource, path: string) =>
    request<ExternalScanResponse>(`/api/import/external/${encodeURIComponent(source)}/scan`, {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),
  execute: (
    source: ExternalImportSource,
    payload: {
      path: string
      selected_ids: string[]
      duplicate_strategy: ExternalDuplicateStrategy
    },
  ) =>
    request<ExternalExecuteResponse>(`/api/import/external/${encodeURIComponent(source)}/execute`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}

export const statsApi = {
  ledger: (days = 365) => request<TimeLedgerResponse>(`/api/stats/ledger?days=${days}`),
  collage: (params?: { year?: string; collection_id?: number | null }) => {
    const qs = new URLSearchParams()
    if (params?.year) qs.set('year', params.year)
    if (params?.collection_id != null) qs.set('collection_id', String(params.collection_id))
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return request<JourneyCollageResponse>(`/api/stats/collage${suffix}`)
  },
}

export const collectionsApi = {
  list: () => request<CollectionItem[]>('/api/collections'),
  create: (name: string, gameIds: number[] = []) =>
    request<CollectionItem>('/api/collections', {
      method: 'POST',
      body: JSON.stringify({ name, game_ids: gameIds }),
    }),
  update: (collectionId: number, patch: { name?: string; sort_order?: number }) =>
    request<CollectionItem>(`/api/collections/${collectionId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  remove: (collectionId: number) =>
    request<{ status: string; collection_id: number }>(`/api/collections/${collectionId}`, {
      method: 'DELETE',
    }),
  replaceGames: (collectionId: number, gameIds: number[]) =>
    request<CollectionItem>(`/api/collections/${collectionId}/games`, {
      method: 'PUT',
      body: JSON.stringify({ game_ids: gameIds }),
    }),
  addGame: (collectionId: number, gameId: number) =>
    request<CollectionItem>(`/api/collections/${collectionId}/games/${gameId}`, {
      method: 'POST',
    }),
  removeGame: (collectionId: number, gameId: number) =>
    request<CollectionItem>(`/api/collections/${collectionId}/games/${gameId}`, {
      method: 'DELETE',
    }),
}
