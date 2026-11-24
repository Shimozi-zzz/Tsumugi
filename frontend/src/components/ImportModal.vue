<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  assetProxyUrl,
  gamesApi,
  isDesktopBridgeAvailable,
  libraryApi,
  pickNativeFile,
  pickNativeFolder,
  scraperApi,
} from '@/api/client'
import { useLibraryStore } from '@/stores/library'
import { useTaskStore } from '@/stores/tasks'
import type {
  AssetCandidate,
  BatchScanCandidate,
  MediaSaveMode,
  MusicCandidate,
  ScrapedGameItem,
  ScraperEnrichDescriptionItem,
  ScraperEnrichVisualItem,
  ScraperSourceDescriptor,
} from '@/types'
import { normalizePlatformBadge } from '@/utils/platform'

const store = useLibraryStore()
const taskStore = useTaskStore()
const hasBridge = isDesktopBridgeAvailable()

// 顶层模式：在线刮削导入 vs 本地 / 批量
const topMode = ref<'online' | 'local'>(store.importInitialTab === 'local' ? 'local' : 'online')
const localMode = ref<'single' | 'batch'>(store.importInitialLocalMode || 'single')

const SOURCE_LABELS: Record<string, string> = {
  ymgal: 'YMGal',
  kungal: 'Kungal',
  vndb: 'VNDB',
  bangumi: 'Bangumi',
  bgm: 'Bangumi',
  dlsite: 'DLsite',
  steam: 'Steam',
  igdb: 'IGDB',
  steamgriddb: 'SteamGridDB',
  sgdb: 'SteamGridDB',
  touchgal: 'TouchGal',
}

const activeSourceFilter = ref<string>('all')

// 后端动态返回的数据源状态
const availableSources = ref<ScraperSourceDescriptor[]>([])
const sgdbConfigured = ref(Boolean(store.settings.scraper_settings?.source_status?.steamgriddb?.configured || store.settings.api_keys?.steamgriddb))
const igdbConfigured = ref(Boolean(store.settings.scraper_settings?.source_status?.igdb?.configured))

// 单行数据源切换胶囊：首位「综合推荐」+ 右侧各单源（含 TouchGal，已配置 IGDB 凭证时动态追加）
const sourceFilterChips = computed<{ id: string; label: string }[]>(() => {
  const statusMap = new Map(availableSources.value.map((s) => [s.id, s]))
  const baseIds = ['ymgal', 'kungal', 'touchgal', 'vndb', 'bangumi', 'dlsite', 'steam']
  if (igdbConfigured.value) {
    baseIds.push('igdb')
  }
  const chips: { id: string; label: string }[] = [
    { id: 'all', label: '综合推荐' },
  ]
  for (const sid of baseIds) {
    const desc = statusMap.get(sid)
    if (desc && !desc.enabled) continue
    chips.push({
      id: sid,
      label: SOURCE_LABELS[sid] || sid.toUpperCase(),
    })
  }
  return chips
})

// 在线检索状态
const keyword = ref('')
const searching = ref(false)
const searchResults = ref<ScrapedGameItem[]>([])
const searchedOnce = ref(false)
const directMatchInfo = ref<{ source: string; source_id: string } | null>(null)
const sourceErrors = ref<Record<string, string>>({})
const brokenCardCovers = ref<Set<string>>(new Set())

// 客户端实时识别粘贴的直查链接/编号，给用户清晰即时反馈
const detectedDirectHint = computed<{ sourceLabel: string; id: string } | null>(() => {
  const raw = keyword.value.trim()
  if (!raw) return null
  let m = raw.match(/kungal\.(?:com|org)\/(?:[^/]+\/)?galgame\/(\d+)/i)
  if (m) return { sourceLabel: 'Kungal', id: `#${m[1]}` }
  m = raw.match(/touchgal\.(?:io|top|us)\/(?:galgame\/|patch\/)?([a-zA-Z0-9_-]{4,})/i)
  if (m && !['search', 'login', 'register', 'about', 'api', 'home'].includes(m[1].toLowerCase())) {
    return { sourceLabel: 'TouchGal', id: m[1] }
  }
  m = raw.match(/ymgal\.games\/(GA\d+)/i) || raw.match(/^(GA\d+)$/i)
  if (m) return { sourceLabel: 'YMGal', id: m[1].toUpperCase() }
  m = raw.match(/dlsite\.com\/[^\s]*?\b((?:RJ|VJ|BJ)\d{4,10})\b/i) || raw.match(/^((?:RJ|VJ|BJ)\d{4,10})$/i)
  if (m) return { sourceLabel: 'DLsite', id: m[1].toUpperCase() }
  m = raw.match(/vndb\.org\/(v\d+)/i) || raw.match(/^(v\d+)$/i)
  if (m) return { sourceLabel: 'VNDB', id: m[1].toLowerCase() }
  m = raw.match(/(?:bgm\.tv|bangumi\.tv|chii\.in)\/subject\/(\d+)/i)
  if (m) return { sourceLabel: 'Bangumi', id: `#${m[1]}` }
  m =
    raw.match(/(?:store\.steampowered\.com|steamcommunity\.com)\/app\/(\d+)/i) ||
    raw.match(/^steam:\/\/(?:run|rungameid|store)\/(\d+)/i) ||
    raw.match(/^(\d{4,9})$/)
  if (m) return { sourceLabel: 'Steam', id: `AppID ${m[1]}` }
  return null
})

// 预览微调状态
const loadingDetail = ref(false)
const importing = ref(false)
const matchedSources = ref<string[]>([])

const MEDIA_MODE_OPTIONS: { key: MediaSaveMode; label: string }[] = [
  { key: 'link_only', label: '仅保留链接' },
  { key: 'download', label: '下载到本地' },
  { key: 'none', label: '不附带' },
]
const pvMode = ref<MediaSaveMode>('none')
const opMode = ref<MediaSaveMode>('none')

const previewDraft = ref<{
  primary_source: string
  primary_source_id: string
  aliases: string[]
  title: string
  sub_title: string
  developer: string
  publisher: string
  release_date: string
  synopsis: string
  tagsText: string
  status: string
  edition: string
  is_nsfw: boolean
  source_platform: string
  bangumi_id: string
  external_ids: Record<string, string>
  cover_url: string
  logo_url: string
  hero_bg_url: string
  pv_url: string
  screenshots: string[]
  exe_path: string
  launch_mode: string
  launch_args: string
  save_dir: string
  screenshot_dir: string
} | null>(null)

// ── 跨源补全（简介 / 高清封面 & Hero，含 SteamGridDB）──
const enrichOpenMode = ref<null | 'description' | 'covers'>(null)
const enrichLoading = ref(false)
const enrichLoaded = ref(false)
const enrichDescriptions = ref<ScraperEnrichDescriptionItem[]>([])
const enrichCovers = ref<ScraperEnrichVisualItem[]>([])
const enrichBackgrounds = ref<ScraperEnrichVisualItem[]>([])
const enrichLogos = ref<ScraperEnrichVisualItem[]>([])
const enrichWarnings = ref<string[]>([])
const enrichVisualTab = ref<'covers' | 'backgrounds' | 'logos'>('covers')
const brokenEnrichImgs = ref<Set<string>>(new Set())

function resetEnrichState() {
  enrichOpenMode.value = null
  enrichLoading.value = false
  enrichLoaded.value = false
  enrichDescriptions.value = []
  enrichCovers.value = []
  enrichBackgrounds.value = []
  enrichLogos.value = []
  enrichWarnings.value = []
  enrichVisualTab.value = 'covers'
  brokenEnrichImgs.value = new Set()
}

async function openEnrichDrawer(mode: 'description' | 'covers', forceReload = false) {
  if (enrichOpenMode.value === mode && !forceReload) {
    enrichOpenMode.value = null
    return
  }
  enrichOpenMode.value = mode
  if (enrichLoaded.value && !forceReload) {
    return
  }
  const d = previewDraft.value
  if (!d) return

  enrichLoading.value = true
  try {
    const res = await scraperApi.enrich({
      title: d.title,
      original_title: d.sub_title,
      aliases: d.aliases,
      release_date: d.release_date,
      source: d.primary_source,
      source_id: d.primary_source_id,
      external_ids: d.external_ids,
      mode: 'all',
    })
    enrichDescriptions.value = res.descriptions || []
    enrichCovers.value = res.covers || []
    enrichBackgrounds.value = res.backgrounds || []
    enrichLogos.value = res.logos || []
    enrichWarnings.value = res.warnings || []
    sgdbConfigured.value = Boolean(res.sgdb_configured)
    enrichLoaded.value = true

    // 自动收敛新发现的跨站 ID（不覆盖用户手动输入）
    if (res.merged_external_ids) {
      d.external_ids = { ...res.merged_external_ids, ...d.external_ids }
      if (!d.bangumi_id && res.merged_external_ids.bangumi) {
        d.bangumi_id = res.merged_external_ids.bangumi
      }
    }
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '跨源补全请求失败', 'warning')
  } finally {
    enrichLoading.value = false
  }
}

function applyEnrichDescription(cand: ScraperEnrichDescriptionItem) {
  const d = previewDraft.value
  if (!d || !cand.description) return
  d.synopsis = cand.description
  if (cand.external_ids) {
    d.external_ids = { ...d.external_ids, ...cand.external_ids }
    if (!d.bangumi_id && cand.external_ids.bangumi) {
      d.bangumi_id = cand.external_ids.bangumi
    }
  }
  if (!matchedSources.value.includes(cand.source)) {
    matchedSources.value = [...matchedSources.value, cand.source]
  }
  store.notify(`已采用 ${cand.source_name} 的剧情简介`, 'success')
}

function applyEnrichMissingFields(cand: ScraperEnrichDescriptionItem) {
  const d = previewDraft.value
  if (!d) return
  let filled = 0
  if (!d.synopsis.trim() && cand.description.trim()) {
    d.synopsis = cand.description.trim()
    filled++
  }
  if (!d.sub_title.trim() && cand.original_title.trim()) {
    d.sub_title = cand.original_title.trim()
    filled++
  }
  if (!d.developer.trim() && cand.developers.length > 0) {
    d.developer = cand.developers.join(', ')
    filled++
  }
  if (!d.publisher.trim() && cand.publishers.length > 0) {
    d.publisher = cand.publishers.join(', ')
    filled++
  }
  if (!d.release_date.trim() && cand.release_date.trim()) {
    d.release_date = cand.release_date.trim()
    filled++
  }
  if (!d.tagsText.trim() && cand.tags.length > 0) {
    d.tagsText = cand.tags.join(', ')
    filled++
  }
  if (cand.external_ids) {
    d.external_ids = { ...d.external_ids, ...cand.external_ids }
    if (!d.bangumi_id && cand.external_ids.bangumi) {
      d.bangumi_id = cand.external_ids.bangumi
    }
  }
  if (!matchedSources.value.includes(cand.source)) {
    matchedSources.value = [...matchedSources.value, cand.source]
  }
  store.notify(
    filled > 0 ? `已从 ${cand.source_name} 补全 ${filled} 项空缺字段` : `已合并 ${cand.source_name} 关联 ID`,
    'success',
  )
}

function applyEnrichVisual(item: ScraperEnrichVisualItem) {
  const d = previewDraft.value
  if (!d) return
  if (enrichVisualTab.value === 'covers') {
    d.cover_url = item.url
    store.notify(`已更换封面（${item.source_name}）`, 'success')
  } else if (enrichVisualTab.value === 'backgrounds') {
    d.hero_bg_url = item.url
    store.notify(`已更换宽幅背景（${item.source_name}）`, 'success')
  } else {
    d.logo_url = item.url
    store.notify(`已更换透明 Logo（${item.source_name}）`, 'success')
  }
  if (!matchedSources.value.includes(item.source)) {
    matchedSources.value = [...matchedSources.value, item.source]
  }
}

const activeEnrichVisuals = computed(() => {
  if (enrichVisualTab.value === 'backgrounds') return enrichBackgrounds.value
  if (enrichVisualTab.value === 'logos') return enrichLogos.value
  return enrichCovers.value
})

function openSgdbSettingsShortcut() {
  store.showImportModal = false
  store.openSettings('sources', 'steamgriddb')
}

// 附带影音（可选）折叠挑选项
type PvSourceKey = 'auto' | 'bilibili' | 'youtube'
type BgmSourceKey = 'auto' | 'bilibili' | 'youtube' | 'itunes'

const PV_SOURCE_OPTIONS: { key: PvSourceKey; label: string }[] = [
  { key: 'auto', label: '优先 Steam' },
  { key: 'bilibili', label: 'Bilibili' },
  { key: 'youtube', label: 'YouTube' },
]

const BGM_SOURCE_OPTIONS: { key: BgmSourceKey; label: string }[] = [
  { key: 'auto', label: '自动' },
  { key: 'bilibili', label: 'Bilibili' },
  { key: 'youtube', label: 'YouTube' },
  { key: 'itunes', label: 'iTunes' },
]

const optionalMediaOpen = ref(false)
const pvQuery = ref('')
const pvSource = ref<PvSourceKey>('auto')
const pvSearching = ref(false)
const pvSearchedOnce = ref(false)
const pvSteamEmpty = ref(false)
const pvCandidates = ref<AssetCandidate[]>([])
const selectedPv = ref<AssetCandidate | null>(null)

const bgmQuery = ref('')
const bgmSource = ref<BgmSourceKey>('auto')
const bgmSearching = ref(false)
const bgmSearchedOnce = ref(false)
const bgmCandidates = ref<MusicCandidate[]>([])
const selectedBgm = ref<MusicCandidate | null>(null)

function resetOptionalMedia(defaultKeyword = '', hasScrapedPv = false) {
  optionalMediaOpen.value = false
  pvMode.value = hasScrapedPv ? 'link_only' : 'none'
  opMode.value = 'none'
  pvQuery.value = defaultKeyword
  pvSource.value = 'auto'
  pvSearching.value = false
  pvSearchedOnce.value = false
  pvSteamEmpty.value = false
  pvCandidates.value = []
  selectedPv.value = null
  bgmQuery.value = defaultKeyword
  bgmSource.value = 'auto'
  bgmSearching.value = false
  bgmSearchedOnce.value = false
  bgmCandidates.value = []
  selectedBgm.value = null
}

function setPvMode(mode: MediaSaveMode) {
  pvMode.value = mode
  if (mode === 'none') {
    selectedPv.value = null
    return
  }
  if (!selectedPv.value && !(previewDraft.value?.pv_url || '').trim()) {
    optionalMediaOpen.value = true
  }
}

function setOpMode(mode: MediaSaveMode) {
  opMode.value = mode
  if (mode === 'none') {
    selectedBgm.value = null
  }
}

function formatDurationSec(sec: number | null | undefined): string {
  if (!sec || sec <= 0) return ''
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

async function searchOptionalPv(overrideSource?: PvSourceKey) {
  const d = previewDraft.value
  if (overrideSource) {
    pvSource.value = overrideSource
  }
  const q = (pvQuery.value || d?.sub_title || d?.title || '').trim()
  if (!pvQuery.value.trim() && q) {
    pvQuery.value = q
  }
  const steamAppId = (d?.external_ids?.steam || '').trim()
  if ((!q && !steamAppId) || pvSearching.value) return
  const altTitle =
    d && q !== (d.title || '').trim()
      ? (d.title || '').trim()
      : (d?.sub_title || '').trim()

  optionalMediaOpen.value = true
  pvSearching.value = true
  pvSearchedOnce.value = true
  try {
    const res = await scraperApi.searchAssets('pv', q, pvSource.value, {
      steam_appid: steamAppId,
      alt_title: altTitle,
    })
    pvCandidates.value = res.items || []
    pvSteamEmpty.value = Boolean(res.steam_empty)
  } catch (err) {
    pvCandidates.value = []
    pvSteamEmpty.value = false
    store.notify(err instanceof Error ? err.message : 'PV 查找失败', 'warning')
  } finally {
    pvSearching.value = false
  }
}

async function searchOptionalBgm(overrideSource?: BgmSourceKey) {
  const d = previewDraft.value
  if (overrideSource) {
    bgmSource.value = overrideSource
  }
  const q = (bgmQuery.value || d?.sub_title || d?.title || '').trim()
  if (!bgmQuery.value.trim() && q) {
    bgmQuery.value = q
  }
  if (!q || bgmSearching.value) return
  const altTitle =
    d && q !== (d.title || '').trim()
      ? (d.title || '').trim()
      : (d?.sub_title || '').trim()

  optionalMediaOpen.value = true
  bgmSearching.value = true
  bgmSearchedOnce.value = true
  try {
    const res = await scraperApi.searchMusic(q, {
      source: bgmSource.value,
      alt_title: altTitle,
    })
    bgmCandidates.value = res.items || []
  } catch (err) {
    bgmCandidates.value = []
    store.notify(err instanceof Error ? err.message : '主题曲查找失败', 'warning')
  } finally {
    bgmSearching.value = false
  }
}

function toggleSelectPv(item: AssetCandidate) {
  if (selectedPv.value?.id === item.id) {
    selectedPv.value = null
    if (!(previewDraft.value?.pv_url || '').trim()) {
      pvMode.value = 'none'
    }
    return
  }
  selectedPv.value = item
  if (pvMode.value === 'none') {
    pvMode.value = 'link_only'
  }
}

function toggleSelectBgm(item: MusicCandidate) {
  if (selectedBgm.value?.id === item.id) {
    selectedBgm.value = null
    return
  }
  selectedBgm.value = item
  if (opMode.value === 'none') {
    opMode.value = 'link_only'
  }
}

// 本地单条自定义表单
const localForm = reactive({
  title: '',
  sub_title: '',
  developer: '',
  publisher: '',
  release_date: '',
  synopsis: '',
  tagsText: '',
  status: 'todo',
  edition: 'collector',
  is_nsfw: false,
  exe_path: '',
  launch_mode: 'direct',
  launch_args: '',
  save_dir: '',
  screenshot_dir: '',
})

// 本地批量扫描状态
const scanRootDir = ref('')
const scanning = ref(false)
const batchImporting = ref(false)
const autoScrapeOnBatch = ref(true)
const scanCandidates = ref<
  (BatchScanCandidate & { selected: boolean; custom_title: string; chosen_exe: string })[]
>([])

function extractYear(raw?: string): string {
  const m = (raw || '').match(/\d{4}/)
  return m ? m[0] : ''
}

function formatSourceLabel(src?: string): string {
  const key = (src || '').trim().toLowerCase()
  return SOURCE_LABELS[key] || (src || '').toUpperCase()
}

function sourceBadgeClass(src?: string): string {
  const key = (src || '').trim().toLowerCase()
  if (key === 'ymgal') return 'badge-ymgal'
  if (key === 'kungal') return 'badge-kungal'
  if (key === 'touchgal' || key === 'tgal') return 'badge-touchgal'
  if (key === 'dlsite') return 'badge-dlsite'
  if (key === 'vndb') return 'badge-vndb'
  if (key === 'bangumi' || key === 'bgm') return 'badge-bangumi'
  if (key === 'steam') return 'badge-steam'
  if (key === 'igdb') return 'badge-igdb'
  return 'badge-default'
}

function markCardCoverBroken(key: string) {
  const next = new Set(brokenCardCovers.value)
  next.add(key)
  brokenCardCovers.value = next
}

function markEnrichImgBroken(id: string) {
  const next = new Set(brokenEnrichImgs.value)
  next.add(id)
  brokenEnrichImgs.value = next
}

async function loadAvailableSources() {
  try {
    const res = await scraperApi.sources()
    availableSources.value = res.sources || []
    sgdbConfigured.value = Boolean(res.sgdb_configured)
    igdbConfigured.value = Boolean(res.igdb_configured)
  } catch {
    // 静默回退默认列表
  }
}

onMounted(() => {
  void loadAvailableSources()

  // 兼容从特定源入口打开
  const initTab = store.importInitialTab
  if (initTab && initTab !== 'aggregated' && initTab !== 'local') {
    activeSourceFilter.value = initTab === 'bgm' ? 'bangumi' : initTab
  }

  if (store.droppedFileInfo) {
    const info = store.droppedFileInfo
    if (info.kind === 'folder') {
      topMode.value = 'local'
      localMode.value = 'batch'
      scanRootDir.value = info.folder_path
      void runBatchScan()
    } else {
      topMode.value = 'local'
      localMode.value = 'single'
      localForm.title = info.suggested_title
      localForm.exe_path = info.exe_path
      keyword.value = info.suggested_title
    }
    store.droppedFileInfo = null
  }
})

function switchSourceFilter(srcId: string) {
  if (activeSourceFilter.value === srcId) return
  activeSourceFilter.value = srcId
  previewDraft.value = null
  if (searchedOnce.value && keyword.value.trim()) {
    void runSearch()
  }
}

async function runSearch() {
  const q = keyword.value.trim()
  if (!q) return
  searching.value = true
  searchedOnce.value = true
  previewDraft.value = null
  resetEnrichState()
  brokenCardCovers.value = new Set()
  directMatchInfo.value = null
  sourceErrors.value = {}
  try {
    const res = await scraperApi.search(q, {
      sources: activeSourceFilter.value === 'all' ? undefined : [activeSourceFilter.value],
      limit: 18,
    })
    searchResults.value = res.items || []
    directMatchInfo.value = res.direct_match || null
    sourceErrors.value = res.source_errors || {}
    sgdbConfigured.value = Boolean(res.sgdb_configured)
    if (res.igdb_configured != null) {
      igdbConfigured.value = Boolean(res.igdb_configured)
    }
    if (res.available_sources && res.available_sources.length > 0) {
      availableSources.value = res.available_sources
    }
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '检索失败，请检查网络或代理设置', 'error')
  } finally {
    searching.value = false
  }
}

const sourceErrorSummary = computed(() => {
  const entries = Object.entries(sourceErrors.value || {})
  if (entries.length === 0) return ''
  return entries.map(([src, msg]) => `${formatSourceLabel(src)}（${msg}）`).join('、')
})

function buildDraftFromItem(item: ScrapedGameItem) {
  resetEnrichState()
  resetOptionalMedia(
    (item.original_title || item.sub_title || item.title || '').trim(),
    Boolean((item.pv_url || '').trim()),
  )
  const extIds: Record<string, string> = {
    ...(item.extra_ids || {}),
    ...(item.external_ids || {}),
  }
  const normSrc = (item.source || '').trim().toLowerCase()
  const srcId = (item.source_id || item.external_id || '').trim()
  if (normSrc && srcId && !extIds[normSrc]) {
    extIds[normSrc] = srcId
  }

  previewDraft.value = {
    primary_source: normSrc,
    primary_source_id: srcId,
    aliases: [...(item.aliases || [])],
    title: item.title,
    sub_title: item.original_title || item.sub_title || '',
    developer: item.developers?.length ? item.developers.join(', ') : item.developer || '',
    publisher: item.publishers?.length ? item.publishers.join(', ') : item.publisher || '',
    release_date: item.release_date || '',
    synopsis: item.description || item.synopsis || '',
    tagsText: (item.tags || []).join(', '),
    status: 'todo',
    edition: 'collector',
    is_nsfw: Boolean(item.is_nsfw),
    source_platform: normalizePlatformBadge(item.source, extIds) || 'PC',
    bangumi_id: (item.bangumi_id || extIds.bangumi || extIds.bgm || '').trim(),
    external_ids: extIds,
    cover_url: item.cover_url || '',
    logo_url: item.logo_url || '',
    hero_bg_url: item.background_url || item.hero_bg_url || '',
    pv_url: item.pv_url || '',
    screenshots: [...(item.screenshots || [])],
    exe_path: localForm.exe_path || '',
    launch_mode: 'direct',
    launch_args: '',
    save_dir: '',
    screenshot_dir: '',
  }
}

async function selectCandidate(item: ScrapedGameItem) {
  if (item.already_in_library) {
    store.notify(`提示：《${item.title}》已在游戏库中，可按需核对避免重复导入`, 'warning', 3200)
  }

  const normSrc = (item.source || '').trim().toLowerCase()
  const srcId = (item.source_id || item.external_id || '').trim()

  // 直查结果本身已是完整详情，直接进入第二步预览确认
  if (item.direct_hit) {
    matchedSources.value = normSrc ? [normSrc] : []
    buildDraftFromItem(item)
    return
  }

  loadingDetail.value = true
  matchedSources.value = normSrc ? [normSrc] : []
  try {
    const detail =
      normSrc && srcId
        ? await scraperApi.detail(normSrc, srcId).catch(() => item)
        : item
    buildDraftFromItem(detail)
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '拉取完整详情失败', 'warning')
    buildDraftFromItem(item)
  } finally {
    loadingDetail.value = false
  }
}

async function confirmScrapedImport() {
  const d = previewDraft.value
  if (!d || !d.title.trim()) return
  importing.value = true
  try {
    const tags = d.tagsText
      .split(/[,，\n]/)
      .map((t) => t.trim())
      .filter(Boolean)

    const pvPicked = pvMode.value === 'none' ? null : selectedPv.value
    const bgmPicked = opMode.value === 'none' ? null : selectedBgm.value
    const bgmPickedUrl = bgmPicked ? (bgmPicked.preview_url || bgmPicked.source_url || '') : ''
    const effectivePvUrl = pvMode.value === 'none' ? '' : (pvPicked?.url || d.pv_url.trim())
    const shouldAutoMatchOp = opMode.value !== 'none' && !bgmPickedUrl

    const created = await scraperApi.importGame({
      title: d.title.trim(),
      sub_title: d.sub_title.trim(),
      developer: d.developer.trim(),
      publisher: d.publisher.trim(),
      release_date: d.release_date.trim(),
      synopsis: d.synopsis.trim(),
      tags,
      status: d.status,
      edition: d.edition,
      is_nsfw: d.is_nsfw,
      source_platform: d.source_platform,
      bangumi_id: d.bangumi_id,
      external_ids: d.external_ids,
      cover_url: d.cover_url,
      logo_url: d.logo_url,
      hero_bg_url: d.hero_bg_url,
      pv_url: pvMode.value === 'none' ? '' : d.pv_url,
      pv_mode: pvMode.value,
      selected_pv_url: pvPicked ? pvPicked.url : null,
      selected_pv_source: pvPicked ? pvPicked.source : null,
      selected_pv_mime_hint: pvPicked ? pvPicked.mime_hint : null,
      selected_pv_fallback_urls: pvPicked?.fallback_urls || [],
      op_mode: opMode.value,
      selected_bgm_url: bgmPickedUrl || null,
      screenshots: d.screenshots,
      download_screenshots: true,
      auto_fetch_bgm: shouldAutoMatchOp,
      exe_path: d.exe_path.trim(),
      launch_mode: d.launch_mode,
      launch_args: d.launch_args.trim(),
      save_dir: d.save_dir.trim(),
      screenshot_dir: d.screenshot_dir.trim(),
    })

    store.addOrFocusGame(created)

    const willDownloadPv = pvMode.value === 'download' && /^https?:\/\//i.test(effectivePvUrl)
    const willDownloadOp = opMode.value === 'download' && (Boolean(bgmPickedUrl) || shouldAutoMatchOp)

    if (willDownloadPv) {
      taskStore.trackTask(
        {
          game_id: created.id,
          asset_type: 'pv',
          status: 'queued',
          progress: 0,
          message: '等待下载宣传片…',
        },
        {
          url: effectivePvUrl,
          source: pvPicked?.source || '',
          mime_hint: pvPicked?.mime_hint || '',
          fallback_urls: pvPicked?.fallback_urls || [],
        },
      )
    }
    if (willDownloadOp) {
      taskStore.trackTask({
        game_id: created.id,
        asset_type: 'bgm',
        status: 'queued',
        progress: 0,
        message: '等待下载主题曲…',
      })
    }

    const hasLinkOnlyMedia =
      (pvMode.value === 'link_only' && Boolean(effectivePvUrl)) ||
      (opMode.value === 'link_only' && (Boolean(bgmPickedUrl) || shouldAutoMatchOp))

    store.notify(
      willDownloadPv || willDownloadOp
        ? `《${created.title}》已入库，影音正在后台下载`
        : hasLinkOnlyMedia
          ? `《${created.title}》已入库（已保留在线影音链接）`
          : `《${created.title}》已入库`,
      'success',
    )
    store.showImportModal = false
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '入库失败', 'error')
  } finally {
    importing.value = false
  }
}

async function submitLocalCustom() {
  if (!localForm.title.trim()) {
    store.notify('请输入游戏标题', 'warning')
    return
  }
  importing.value = true
  try {
    const tags = localForm.tagsText
      .split(/[,，\n]/)
      .map((t) => t.trim())
      .filter(Boolean)
    const created = await gamesApi.create({
      title: localForm.title.trim(),
      sub_title: localForm.sub_title.trim(),
      developer: localForm.developer.trim(),
      publisher: localForm.publisher.trim(),
      release_date: localForm.release_date.trim(),
      synopsis: localForm.synopsis.trim(),
      tags,
      status: localForm.status,
      edition: 'collector',
      is_nsfw: localForm.is_nsfw,
      source_platform: 'PC',
      media: {
        exe_path: localForm.exe_path.trim(),
        launch_mode: localForm.launch_mode,
        launch_args: localForm.launch_args.trim(),
        save_dir: localForm.save_dir.trim(),
        screenshot_dir: localForm.screenshot_dir.trim(),
      },
    })
    store.addOrFocusGame(created)
    store.notify(`本地游戏《${created.title}》已入库`, 'success')
    store.showImportModal = false
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '创建失败', 'error')
  } finally {
    importing.value = false
  }
}

async function runBatchScan() {
  if (!scanRootDir.value.trim()) {
    store.notify('请先输入或选择要扫描的游戏总根目录', 'warning')
    return
  }
  scanning.value = true
  try {
    const res = await libraryApi.scanDirectory(scanRootDir.value.trim())
    scanCandidates.value = res.items.map((item) => ({
      ...item,
      selected: !item.already_imported,
      custom_title: item.clean_title,
      chosen_exe: item.suggested_exe,
    }))
    if (res.count === 0) {
      store.notify('未在该目录下发现一级游戏子目录', 'warning')
    }
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '目录扫描失败', 'error')
  } finally {
    scanning.value = false
  }
}

async function submitBatchImport() {
  const chosen = scanCandidates.value.filter((c) => c.selected)
  if (chosen.length === 0) {
    store.notify('请至少勾选一款待导入的游戏', 'warning')
    return
  }
  batchImporting.value = true
  try {
    const res = await libraryApi.batchImport(
      chosen.map((c) => ({
        title: c.custom_title.trim() || c.clean_title,
        folder_path: c.folder_path,
        exe_path: c.chosen_exe,
        launch_mode: 'direct',
        save_dir: c.detected_save_dir,
        screenshot_dir: c.detected_screenshot_dir,
        edition: 'collector',
      })),
      autoScrapeOnBatch.value,
    )
    await store.refreshGames()
    if (res.imported_ids.length > 0) {
      await store.selectGame(res.imported_ids[res.imported_ids.length - 1], { switchToDetail: true })
    }
    store.notify(`批量导入完成：成功入库 ${res.imported_count} 款游戏`, 'success')
    store.showImportModal = false
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '批量导入失败', 'error')
  } finally {
    batchImporting.value = false
  }
}

async function pickForLocal(target: 'exe' | 'save' | 'ss' | 'scan' | 'draft_exe') {
  if (target === 'exe') {
    const p = await pickNativeFile('选择游戏主程序 (.exe / .lnk)')
    if (p) localForm.exe_path = p
  } else if (target === 'draft_exe' && previewDraft.value) {
    const p = await pickNativeFile('选择游戏主程序 (.exe / .lnk)')
    if (p) previewDraft.value.exe_path = p
  } else if (target === 'save') {
    const p = await pickNativeFolder('选择存档目录')
    if (p) localForm.save_dir = p
  } else if (target === 'ss') {
    const p = await pickNativeFolder('选择截图目录')
    if (p) localForm.screenshot_dir = p
  } else if (target === 'scan') {
    const p = await pickNativeFolder('选择存放多个游戏文件夹的总目录')
    if (p) {
      scanRootDir.value = p
      void runBatchScan()
    }
  }
}
</script>

<template>
  <div class="modal-backdrop" @click.self="store.showImportModal = false">
    <div class="modal-card import-card">
      <div class="modal-head">
        <div class="head-left">
          <h2>导入游戏</h2>
          <div class="top-mode-pills">
            <button
              type="button"
              class="mode-pill"
              :class="{ active: topMode === 'online' }"
              @click="topMode = 'online'"
            >
              在线资料刮削
            </button>
            <button
              type="button"
              class="mode-pill"
              :class="{ active: topMode === 'local' }"
              @click="topMode = 'local'"
            >
              本地 / 批量
            </button>
          </div>
        </div>
        <div class="modal-head-actions">
          <button class="close-icon-btn" aria-label="关闭" @click="store.showImportModal = false">
            <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" />
            </svg>
          </button>
        </div>
      </div>

      <div class="modal-body">
        <!-- ══════════ 1. 在线多源刮削模式 ══════════ -->
        <template v-if="topMode === 'online'">
          <!-- 搜索输入 + 单行数据源切换胶囊 -->
          <div class="search-control-stack">
            <div class="search-bar-row">
              <input
                v-model="keyword"
                class="input search-input"
                placeholder="输入游戏名，或直接粘贴 Steam / VNDB / Bangumi / YMGal / Kungal 链接或 RJ 编号"
                @keydown.enter="runSearch"
              />
              <button class="btn btn-primary" :disabled="searching || !keyword.trim()" @click="runSearch">
                {{ searching ? '检索中…' : '搜索' }}
              </button>
            </div>

            <div v-if="detectedDirectHint" class="direct-hint-bar">
              <span class="direct-dot" />
              <span>已识别直查目标：<strong>{{ detectedDirectHint.sourceLabel }}</strong> · <code>{{ detectedDirectHint.id }}</code>（回车直查）</span>
            </div>

            <!-- 单行胶囊：综合推荐 + 各单源切换 -->
            <div class="source-filter-pills" role="tablist" aria-label="数据源切换">
              <button
                v-for="chip in sourceFilterChips"
                :key="chip.id"
                type="button"
                role="tab"
                class="src-filter-pill"
                :class="{ active: activeSourceFilter === chip.id, primary: chip.id === 'all' }"
                :aria-selected="activeSourceFilter === chip.id"
                @click="switchSourceFilter(chip.id)"
              >
                {{ chip.label }}
              </button>
            </div>
          </div>

          <!-- 非阻塞部分源异常提示 -->
          <div v-if="sourceErrorSummary && !previewDraft && !loadingDetail" class="partial-error-bar">
            部分源暂未响应：{{ sourceErrorSummary }}（其余数据源已正常返回）
          </div>

          <!-- 加载详情状态 -->
          <div v-if="loadingDetail" class="center-loading">
            <div class="spinner" />
            <span>正在加载详情…</span>
          </div>

          <!-- 第二步：入库前详情确认与跨源补全 -->
          <div v-else-if="previewDraft" class="preview-editor">
            <div class="preview-top">
              <button class="btn btn-sm btn-ghost" @click="previewDraft = null">← 返回候选列表</button>
              <div class="matched-pills">
                <span class="muted">当前来源</span>
                <span v-for="s in matchedSources" :key="s" class="src-pill">{{ formatSourceLabel(s) }}</span>
              </div>
            </div>

            <!-- 视觉资产预览条 -->
            <div class="visual-strip">
              <div class="vis-box cover">
                <img v-if="previewDraft.cover_url" :src="assetProxyUrl(previewDraft.cover_url)" alt="Cover" />
                <span v-else>无竖版封面</span>
                <span class="vis-tag">封面 Cover</span>
              </div>
              <div class="vis-box hero">
                <img v-if="previewDraft.hero_bg_url" :src="assetProxyUrl(previewDraft.hero_bg_url)" alt="Hero" />
                <span v-else>无 Hero 宽幅背景</span>
                <span class="vis-tag">宽幅 Hero</span>
              </div>
              <div class="vis-box logo">
                <img v-if="previewDraft.logo_url" :src="assetProxyUrl(previewDraft.logo_url)" alt="Logo" />
                <span v-else>无透明 Logo（将用衬线标题）</span>
                <span class="vis-tag">透明 Logo</span>
              </div>
            </div>

            <!-- 跨源字段补全快捷条（换源补全简介 / 更换高清封面含 SteamGridDB） -->
            <div class="enrich-bar">
              <div class="enrich-bar-actions">
                <button
                  type="button"
                  class="btn btn-sm enrich-btn"
                  :class="{ active: enrichOpenMode === 'description' }"
                  :disabled="enrichLoading"
                  @click="openEnrichDrawer('description')"
                >
                  {{ enrichLoading && enrichOpenMode === 'description' ? '补全检索中…' : '换源补全简介 / 信息' }}
                </button>
                <button
                  type="button"
                  class="btn btn-sm enrich-btn"
                  :class="{ active: enrichOpenMode === 'covers' }"
                  :disabled="enrichLoading"
                  @click="openEnrichDrawer('covers')"
                >
                  {{
                    enrichLoading && enrichOpenMode === 'covers'
                      ? '检索中…'
                      : '更换封面 / 背景'
                  }}
                </button>
                <button
                  v-if="enrichLoaded && enrichOpenMode"
                  type="button"
                  class="btn btn-sm btn-ghost"
                  :disabled="enrichLoading"
                  @click="openEnrichDrawer(enrichOpenMode, true)"
                >
                  刷新
                </button>
              </div>
              <button
                v-if="enrichOpenMode"
                type="button"
                class="enrich-close-btn"
                @click="enrichOpenMode = null"
              >
                收起
              </button>
            </div>

            <!-- 跨源补全展开面板 -->
            <div v-if="enrichOpenMode" class="enrich-drawer">
              <div v-if="enrichLoading" class="enrich-loading">
                <div class="spinner small" />
                <span>正在检索其他数据源…</span>
              </div>

              <!-- 模式 A：跨源简介与字段补全 -->
              <template v-else-if="enrichOpenMode === 'description'">
                <div v-if="enrichDescriptions.length > 0" class="enrich-desc-list">
                  <div
                    v-for="cand in enrichDescriptions"
                    :key="`${cand.source}-${cand.source_id}`"
                    class="enrich-desc-card"
                  >
                    <div class="enrich-desc-head">
                      <div class="enrich-desc-title-row">
                        <span class="cand-source-inline" :class="sourceBadgeClass(cand.source)">
                          {{ cand.source_name }}
                        </span>
                        <span class="enrich-desc-title">{{ cand.title }}</span>
                        <span v-if="cand.has_chinese && cand.description" class="zh-chip">中文简介</span>
                        <span v-if="cand.release_date" class="enrich-year tabular-nums">
                          {{ extractYear(cand.release_date) }}
                        </span>
                      </div>
                      <div class="enrich-desc-btns">
                        <button
                          v-if="cand.description"
                          type="button"
                          class="btn btn-sm"
                          @click="applyEnrichDescription(cand)"
                        >
                          采用简介
                        </button>
                        <button
                          type="button"
                          class="btn btn-sm btn-ghost"
                          @click="applyEnrichMissingFields(cand)"
                        >
                          补全空缺
                        </button>
                      </div>
                    </div>
                    <p class="enrich-desc-text">
                      {{ cand.description || '该源暂无简介，可点击「补全空缺」提取开发商、标签或关联 ID。' }}
                    </p>
                  </div>
                </div>
                <div v-else class="enrich-empty">
                  未在其他已启用源中匹配到同作品简介。
                </div>
              </template>

              <!-- 模式 B：多源 & SteamGridDB 高清封面/背景挑选 -->
              <template v-else>
                <div class="enrich-vis-head">
                  <div class="opt-source-pills">
                    <button
                      type="button"
                      class="opt-src-pill"
                      :class="{ active: enrichVisualTab === 'covers' }"
                      @click="enrichVisualTab = 'covers'"
                    >
                      竖版封面 ({{ enrichCovers.length }})
                    </button>
                    <button
                      type="button"
                      class="opt-src-pill"
                      :class="{ active: enrichVisualTab === 'backgrounds' }"
                      @click="enrichVisualTab = 'backgrounds'"
                    >
                      宽屏背景 Hero ({{ enrichBackgrounds.length }})
                    </button>
                    <button
                      type="button"
                      class="opt-src-pill"
                      :class="{ active: enrichVisualTab === 'logos' }"
                      @click="enrichVisualTab = 'logos'"
                    >
                      透明 Logo ({{ enrichLogos.length }})
                    </button>
                  </div>

                  <span v-if="!sgdbConfigured" class="sgdb-subtle-status">
                    <span>SteamGridDB 未配置</span>
                    <button
                      type="button"
                      class="sgdb-subtle-btn"
                      @click="openSgdbSettingsShortcut"
                    >
                      去设置
                    </button>
                  </span>
                </div>

                <div
                  v-if="activeEnrichVisuals.length > 0"
                  class="enrich-vis-grid"
                  :class="enrichVisualTab"
                >
                  <button
                    v-for="v in activeEnrichVisuals"
                    :key="v.id"
                    type="button"
                    class="enrich-vis-card"
                    :class="{
                      selected:
                        (enrichVisualTab === 'covers' && previewDraft.cover_url === v.url) ||
                        (enrichVisualTab === 'backgrounds' && previewDraft.hero_bg_url === v.url) ||
                        (enrichVisualTab === 'logos' && previewDraft.logo_url === v.url),
                    }"
                    @click="applyEnrichVisual(v)"
                  >
                    <img
                      v-if="!brokenEnrichImgs.has(v.id)"
                      :src="assetProxyUrl(v.thumb_url || v.url)"
                      alt=""
                      loading="lazy"
                      @error="markEnrichImgBroken(v.id)"
                    />
                    <span v-else class="cand-no-img">{{ v.source_name }}</span>
                    <div class="enrich-vis-meta">
                      <span>{{ v.source_name }}</span>
                      <span v-if="v.width && v.height" class="tabular-nums">{{ v.width }}×{{ v.height }}</span>
                    </div>
                  </button>
                </div>
                <div v-else class="enrich-empty">
                  暂无可用候选图片。
                </div>
              </template>
            </div>

            <div class="field-grid">
              <div class="field">
                <label>主标题 *</label>
                <input v-model="previewDraft.title" class="input" />
              </div>
              <div class="field">
                <label>原名 / 副标题</label>
                <input v-model="previewDraft.sub_title" class="input" />
              </div>
            </div>

            <div class="field-grid three">
              <div class="field">
                <label>开发商</label>
                <input v-model="previewDraft.developer" class="input" />
              </div>
              <div class="field">
                <label>发行商</label>
                <input v-model="previewDraft.publisher" class="input" />
              </div>
              <div class="field">
                <label>发售日期</label>
                <input v-model="previewDraft.release_date" class="input tabular-nums" />
              </div>
            </div>

            <div class="field-grid">
              <div class="field">
                <label>初始进度</label>
                <select v-model="previewDraft.status" class="select">
                  <option value="todo">未开始</option>
                  <option value="playing">攻略中</option>
                  <option value="done">已通关</option>
                </select>
              </div>
              <div class="field">
                <label>宣传片地址</label>
                <input v-model="previewDraft.pv_url" class="input" placeholder="Steam .m3u8 或 .mp4 链接" />
              </div>
            </div>

            <div class="field">
              <label>标签（逗号分隔）</label>
              <input v-model="previewDraft.tagsText" class="input" />
            </div>

            <div class="field">
              <label>剧情简介</label>
              <textarea v-model="previewDraft.synopsis" class="textarea" rows="3" />
            </div>

            <div class="field-grid">
              <div class="field">
                <label>本地启动程序 (.exe / steam://，可选)</label>
                <div class="row-with-btn">
                  <input v-model="previewDraft.exe_path" class="input" placeholder="可入库后再配置" />
                  <button v-if="hasBridge" class="btn btn-sm" @click="pickForLocal('draft_exe')">浏览…</button>
                </div>
              </div>
              <div class="field">
                <label>启动模式</label>
                <select v-model="previewDraft.launch_mode" class="select">
                  <option value="direct">直接运行</option>
                  <option value="le">Locale Emulator 转区</option>
                  <option value="cli">自定义命令行 / URI</option>
                </select>
              </div>
            </div>

            <!-- 附带影音（可选）：宣传片 PV 与主题曲 OP -->
            <div class="optional-media-box">
              <div class="optional-media-head">
                <button
                  type="button"
                  class="optional-toggle"
                  @click="optionalMediaOpen = !optionalMediaOpen"
                >
                  <svg
                    class="opt-chevron"
                    :class="{ open: optionalMediaOpen }"
                    viewBox="0 0 16 16"
                    width="12"
                    height="12"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                  >
                    <path d="M6 4l4 4-4 4" stroke-linecap="round" stroke-linejoin="round" />
                  </svg>
                  <span class="opt-title">附带影音（可选）</span>
                  <span v-if="selectedPv" class="opt-chosen-pill">
                    PV · {{ selectedPv.source }}
                    <button type="button" class="opt-clear" aria-label="取消选择 PV" @click.stop="selectedPv = null">×</button>
                  </span>
                  <span v-if="selectedBgm" class="opt-chosen-pill">
                    OP · {{ selectedBgm.source }}
                    <button type="button" class="opt-clear" aria-label="取消选择主题曲" @click.stop="selectedBgm = null">×</button>
                  </span>
                </button>

                <div class="optional-quick-btns">
                  <button
                    type="button"
                    class="btn btn-sm"
                    :disabled="pvSearching"
                    @click="searchOptionalPv()"
                  >
                    {{ pvSearching ? '查找中…' : '查找 PV' }}
                  </button>
                  <button
                    type="button"
                    class="btn btn-sm"
                    :disabled="bgmSearching"
                    @click="searchOptionalBgm()"
                  >
                    {{ bgmSearching ? '查找中…' : '查找 OP' }}
                  </button>
                </div>
              </div>

              <!-- 三选一保存策略：仅保留链接 / 下载到本地 / 不附带 -->
              <div class="opt-mode-panel">
                <div class="opt-mode-row">
                  <div class="opt-mode-label">
                    <span>宣传片 PV</span>
                    <span
                      v-if="pvMode !== 'none' && (selectedPv || previewDraft.pv_url.trim())"
                      class="opt-mode-ready"
                    >
                      {{ selectedPv ? `已选 ${selectedPv.source}` : '已带官方链接' }}
                    </span>
                    <span v-else-if="pvMode !== 'none'" class="opt-mode-hint-tag">
                      请点击「查找 PV」选择
                    </span>
                  </div>
                  <div class="opt-mode-segment" role="radiogroup" aria-label="宣传片保存方式">
                    <button
                      v-for="opt in MEDIA_MODE_OPTIONS"
                      :key="`pv-${opt.key}`"
                      type="button"
                      class="opt-mode-btn"
                      :class="{ active: pvMode === opt.key }"
                      @click="setPvMode(opt.key)"
                    >
                      {{ opt.label }}
                    </button>
                  </div>
                </div>

                <div class="opt-mode-row">
                  <div class="opt-mode-label">
                    <span>主题曲 OP</span>
                    <span v-if="opMode !== 'none' && selectedBgm" class="opt-mode-ready">
                      已选 {{ selectedBgm.source }}
                    </span>
                    <span v-else-if="opMode !== 'none'" class="opt-mode-hint-tag">
                      未手选时入库后自动匹配
                    </span>
                  </div>
                  <div class="opt-mode-segment" role="radiogroup" aria-label="主题曲保存方式">
                    <button
                      v-for="opt in MEDIA_MODE_OPTIONS"
                      :key="`op-${opt.key}`"
                      type="button"
                      class="opt-mode-btn"
                      :class="{ active: opMode === opt.key }"
                      @click="setOpMode(opt.key)"
                    >
                      {{ opt.label }}
                    </button>
                  </div>
                </div>

                <p class="opt-mode-note">
                  <strong>仅保留链接</strong>可节省空间；<strong>下载到本地</strong>支持离线播放，已有本地文件时优先播放本地。
                </p>
              </div>

              <div v-if="optionalMediaOpen" class="optional-media-body">
                <!-- PV 候选 -->
                <div class="opt-col">
                  <div class="opt-col-head">
                    <span>宣传片 PV</span>
                    <button v-if="selectedPv" type="button" class="opt-clear-text" @click="selectedPv = null">
                      取消选择
                    </button>
                  </div>

                  <div class="opt-source-pills" role="tablist" aria-label="PV 平台选择">
                    <button
                      v-for="opt in PV_SOURCE_OPTIONS"
                      :key="opt.key"
                      type="button"
                      class="opt-src-pill"
                      :class="{ active: pvSource === opt.key }"
                      :disabled="pvSearching"
                      @click="searchOptionalPv(opt.key)"
                    >
                      {{ opt.label }}
                    </button>
                  </div>

                  <form class="opt-search-row" @submit.prevent="searchOptionalPv()">
                    <input
                      v-model="pvQuery"
                      class="input opt-search-input"
                      placeholder="微调 PV 搜索词…"
                    />
                    <button type="submit" class="btn btn-sm opt-search-btn" :disabled="pvSearching">
                      {{ pvSearching ? '…' : '搜' }}
                    </button>
                  </form>

                  <div v-if="pvSteamEmpty && pvSource === 'auto' && !pvSearching" class="opt-hint-bar">
                    <span>未在 Steam 找到官方宣传片，可切换</span>
                    <button type="button" class="opt-inline-link" @click="searchOptionalPv('bilibili')">Bilibili</button>
                    <span>/</span>
                    <button type="button" class="opt-inline-link" @click="searchOptionalPv('youtube')">YouTube</button>
                  </div>

                  <div v-if="pvCandidates.length > 0" class="opt-cand-list">
                    <button
                      v-for="item in pvCandidates"
                      :key="item.id"
                      type="button"
                      class="opt-cand-row"
                      :class="{ selected: selectedPv?.id === item.id }"
                      @click="toggleSelectPv(item)"
                    >
                      <div class="opt-thumb wide">
                        <img v-if="item.thumb_url" :src="assetProxyUrl(item.thumb_url)" alt="" loading="lazy" decoding="async" />
                        <span v-else>PV</span>
                      </div>
                      <div class="opt-cand-info">
                        <div class="opt-cand-title" :title="item.title">{{ item.title }}</div>
                        <div class="opt-cand-meta">
                          <span
                            v-if="item.is_official || item.source === 'Steam'"
                            class="opt-official-badge"
                          >
                            Steam 官方
                          </span>
                          <span v-else>{{ item.platform || item.source }}</span>
                          <span v-if="formatDurationSec(item.duration)" class="tabular-nums">
                            {{ formatDurationSec(item.duration) }}
                          </span>
                        </div>
                      </div>
                      <span class="opt-check">{{ selectedPv?.id === item.id ? '已选' : '选择' }}</span>
                    </button>
                  </div>
                  <div v-else-if="pvSearchedOnce && !pvSearching" class="opt-empty">
                    <span>未找到宣传片候选</span>
                    <div class="opt-empty-links">
                      <button
                        v-if="pvSource !== 'bilibili'"
                        type="button"
                        class="opt-inline-link"
                        @click="searchOptionalPv('bilibili')"
                      >
                        切换 Bilibili
                      </button>
                      <button
                        v-if="pvSource !== 'youtube'"
                        type="button"
                        class="opt-inline-link"
                        @click="searchOptionalPv('youtube')"
                      >
                        切换 YouTube
                      </button>
                    </div>
                  </div>
                  <div v-else-if="!pvSearching" class="opt-empty">
                    点击「查找 PV」优先获取 Steam 官方宣传片
                  </div>
                </div>

                <!-- 主题曲 OP 候选 -->
                <div class="opt-col">
                  <div class="opt-col-head">
                    <span>主题曲 OP</span>
                    <button v-if="selectedBgm" type="button" class="opt-clear-text" @click="selectedBgm = null">
                      取消选择
                    </button>
                  </div>

                  <div class="opt-source-pills" role="tablist" aria-label="OP 平台选择">
                    <button
                      v-for="opt in BGM_SOURCE_OPTIONS"
                      :key="opt.key"
                      type="button"
                      class="opt-src-pill"
                      :class="{ active: bgmSource === opt.key }"
                      :disabled="bgmSearching"
                      @click="searchOptionalBgm(opt.key)"
                    >
                      {{ opt.label }}
                    </button>
                  </div>

                  <form class="opt-search-row" @submit.prevent="searchOptionalBgm()">
                    <input
                      v-model="bgmQuery"
                      class="input opt-search-input"
                      placeholder="微调主题曲搜索词…"
                    />
                    <button type="submit" class="btn btn-sm opt-search-btn" :disabled="bgmSearching">
                      {{ bgmSearching ? '…' : '搜' }}
                    </button>
                  </form>

                  <div v-if="bgmCandidates.length > 0" class="opt-cand-list">
                    <button
                      v-for="item in bgmCandidates"
                      :key="item.id"
                      type="button"
                      class="opt-cand-row"
                      :class="{ selected: selectedBgm?.id === item.id }"
                      @click="toggleSelectBgm(item)"
                    >
                      <div class="opt-thumb square">
                        <img v-if="item.thumbnail" :src="assetProxyUrl(item.thumbnail)" alt="" loading="lazy" decoding="async" />
                        <span v-else>OP</span>
                      </div>
                      <div class="opt-cand-info">
                        <div class="opt-cand-title" :title="item.title">{{ item.title }}</div>
                        <div class="opt-cand-meta">
                          <span>{{ item.source }}</span>
                          <span v-if="formatDurationSec(item.duration)" class="tabular-nums">
                            {{ formatDurationSec(item.duration) }}
                          </span>
                        </div>
                      </div>
                      <span class="opt-check">{{ selectedBgm?.id === item.id ? '已选' : '选择' }}</span>
                    </button>
                  </div>
                  <div v-else-if="bgmSearchedOnce && !bgmSearching" class="opt-empty">
                    未找到主题曲候选，可修改搜索词或切换平台重试
                  </div>
                  <div v-else-if="!bgmSearching" class="opt-empty">
                    点击「查找 OP」挑选主题曲，或在上方切换 OP 保存方式
                  </div>
                </div>
              </div>
            </div>

            <div class="preview-actions">
              <div class="preview-toggles">
                <label class="nsfw-inline">
                  <input v-model="previewDraft.is_nsfw" type="checkbox" class="native-switch" />
                  <span>成人向条目 (R18)</span>
                </label>
              </div>
              <button class="btn btn-primary" :disabled="importing" @click="confirmScrapedImport">
                {{ importing ? '入库中…' : '确认导入' }}
              </button>
            </div>
          </div>

          <!-- 第一步：多源候选卡片列表 -->
          <div v-else class="candidate-grid">
            <button
              v-for="(item, idx) in searchResults"
              :key="`${item.source}-${item.source_id || item.external_id}-${idx}`"
              class="candidate-card"
              :class="{ 'in-library': item.already_in_library, 'direct-hit': item.direct_hit }"
              @click="selectCandidate(item)"
            >
              <div class="cand-cover">
                <img
                  v-if="item.cover_url && !brokenCardCovers.has(`${item.source}-${item.source_id || item.external_id}-${idx}`)"
                  :src="assetProxyUrl(item.cover_url)"
                  alt=""
                  loading="lazy"
                  @error="markCardCoverBroken(`${item.source}-${item.source_id || item.external_id}-${idx}`)"
                />
                <span v-else class="cand-no-img">{{ formatSourceLabel(item.source) }}</span>
                <span class="cand-source" :class="sourceBadgeClass(item.source)">
                  {{ item.source_label || formatSourceLabel(item.source) }}
                </span>
              </div>

              <div class="cand-body">
                <div class="cand-title-row">
                  <span class="cand-title" :title="item.title">{{ item.title }}</span>
                  <span v-if="item.direct_hit" class="direct-badge">直查命中</span>
                  <span v-if="item.already_in_library" class="in-lib-badge">已入库</span>
                </div>

                <div
                  v-if="(item.original_title || item.sub_title) && (item.original_title || item.sub_title) !== item.title"
                  class="cand-orig"
                  :title="item.original_title || item.sub_title"
                >
                  {{ item.original_title || item.sub_title }}
                </div>

                <div class="cand-meta-line">
                  <span v-if="item.developers?.length || item.developer" class="cand-dev">
                    {{ item.developers?.length ? item.developers[0] : item.developer }}
                  </span>
                  <span v-if="extractYear(item.release_date)" class="cand-year tabular-nums">
                    {{ extractYear(item.release_date) }}
                  </span>
                  <span v-if="item.source_id || item.external_id" class="cand-id tabular-nums">
                    {{ item.source_id || item.external_id }}
                  </span>
                </div>

                <div class="cand-tags">
                  <span v-for="t in (item.tags || []).slice(0, 3)" :key="t">{{ t }}</span>
                </div>
              </div>
            </button>

            <div v-if="searchedOnce && !searching && searchResults.length === 0" class="empty-search">
              <template v-if="directMatchInfo">
                未在 {{ formatSourceLabel(directMatchInfo.source) }} 找到编号 {{ directMatchInfo.source_id }} 对应的条目，请检查链接或编号是否正确。
              </template>
              <template v-else>
                没有找到匹配结果，可尝试更换原名/英文名、粘贴作品链接或 RJ / VNDB 编号，或切换至「本地 / 批量」手动添加。
              </template>
            </div>
            <div v-if="!searchedOnce" class="empty-search">
              输入游戏名，或粘贴 <strong>Steam / VNDB / Bangumi / YMGal / Kungal</strong> 链接及 <strong>RJ</strong> 编号直查。
            </div>
          </div>
        </template>

        <!-- ══════════ 2. 本地自定义 + 批量目录扫描 ══════════ -->
        <template v-else>
          <div class="local-mode-switch">
            <button :class="{ active: localMode === 'single' }" @click="localMode = 'single'">
              单款手动录入
            </button>
            <button :class="{ active: localMode === 'batch' }" @click="localMode = 'batch'">
              批量目录扫描
            </button>
          </div>

          <!-- 单款手动录入 -->
          <div v-if="localMode === 'single'" class="local-form">
            <div class="field-grid">
              <div class="field">
                <label>游戏主标题 *</label>
                <input v-model="localForm.title" class="input" placeholder="例如：Summer Pockets REFLECTION BLUE" />
              </div>
              <div class="field">
                <label>原名 / 副标题</label>
                <input v-model="localForm.sub_title" class="input" />
              </div>
            </div>

            <div class="field-grid three">
              <div class="field">
                <label>开发商</label>
                <input v-model="localForm.developer" class="input" placeholder="如 Key / Yuzusoft" />
              </div>
              <div class="field">
                <label>发行商</label>
                <input v-model="localForm.publisher" class="input" />
              </div>
              <div class="field">
                <label>发售日期</label>
                <input v-model="localForm.release_date" class="input tabular-nums" placeholder="2020-06-26" />
              </div>
            </div>

            <div class="field-grid">
              <div class="field">
                <label>启动方式</label>
                <select v-model="localForm.launch_mode" class="select">
                  <option value="direct">直接运行 .exe</option>
                  <option value="le">Locale Emulator 转区</option>
                  <option value="cli">自定义命令行 / URI</option>
                </select>
              </div>
              <div class="field">
                <label>攻略进度</label>
                <select v-model="localForm.status" class="select">
                  <option value="todo">未开始</option>
                  <option value="playing">攻略中</option>
                  <option value="done">已通关</option>
                </select>
              </div>
            </div>

            <div class="field">
              <label>游戏主程序路径 (.exe / .lnk / steam://)</label>
              <div class="row-with-btn">
                <input v-model="localForm.exe_path" class="input" placeholder="/games/sample/Game.exe 或 D:\Games\Game.exe" />
                <button v-if="hasBridge" class="btn btn-sm" @click="pickForLocal('exe')">浏览…</button>
              </div>
            </div>

            <div class="field-grid">
              <div class="field">
                <label>存档目录（可选）</label>
                <div class="row-with-btn">
                  <input v-model="localForm.save_dir" class="input" />
                  <button v-if="hasBridge" class="btn btn-sm" @click="pickForLocal('save')">浏览…</button>
                </div>
              </div>
              <div class="field">
                <label>截图目录（可选）</label>
                <div class="row-with-btn">
                  <input v-model="localForm.screenshot_dir" class="input" />
                  <button v-if="hasBridge" class="btn btn-sm" @click="pickForLocal('ss')">浏览…</button>
                </div>
              </div>
            </div>

            <div class="field">
              <label>标签（逗号分隔）</label>
              <input v-model="localForm.tagsText" class="input" placeholder="Galgame, 纯爱, 校园" />
            </div>

            <div class="field">
              <label>剧情简介</label>
              <textarea v-model="localForm.synopsis" class="textarea" rows="3" />
            </div>

            <div class="preview-actions">
              <label class="nsfw-inline">
                <input v-model="localForm.is_nsfw" type="checkbox" class="native-switch" />
                <span>NSFW 成人向条目</span>
              </label>
              <button class="btn btn-primary" :disabled="importing" @click="submitLocalCustom">
                {{ importing ? '正在入库…' : '创建条目' }}
              </button>
            </div>
          </div>

          <!-- 批量目录扫描 -->
          <div v-else class="batch-panel">
            <div class="search-bar-row">
              <input
                v-model="scanRootDir"
                class="input search-input"
                placeholder="输入存放游戏文件夹的总目录（如 D:\Galgame 或 /mnt/games）"
                @keydown.enter="runBatchScan"
              />
              <button v-if="hasBridge" class="btn" @click="pickForLocal('scan')">选择目录…</button>
              <button class="btn btn-primary" :disabled="scanning" @click="runBatchScan">
                {{ scanning ? '扫描中…' : '扫描目录' }}
              </button>
            </div>

            <div v-if="scanCandidates.length > 0" class="batch-list">
              <div class="batch-toolbar">
                <label class="nsfw-inline">
                  <input v-model="autoScrapeOnBatch" type="checkbox" class="native-switch" />
                  <span>导入时自动刮削封面、简介与标签</span>
                </label>
                <button
                  class="btn btn-primary btn-sm tabular-nums"
                  :disabled="batchImporting"
                  @click="submitBatchImport"
                >
                  {{
                    batchImporting
                      ? '正在批量导入…'
                      : `导入已选 (${scanCandidates.filter((c) => c.selected).length})`
                  }}
                </button>
              </div>

              <div v-for="c in scanCandidates" :key="c.folder_path" class="batch-row">
                <input v-model="c.selected" type="checkbox" class="batch-checkbox" />
                <div class="batch-fields">
                  <div class="batch-title-row">
                    <input v-model="c.custom_title" class="input batch-title-input" />
                    <span v-if="c.already_imported" class="imported-tag">库中已有</span>
                  </div>
                  <div class="batch-exe-row">
                    <select v-if="c.candidate_exes.length > 0" v-model="c.chosen_exe" class="select">
                      <option v-for="exe in c.candidate_exes" :key="exe" :value="exe">{{ exe }}</option>
                    </select>
                    <input v-else v-model="c.chosen_exe" class="input" placeholder="未检测到主 .exe（可留空）" />
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="empty-search">
              选择游戏根目录，扫描一级子文件夹并识别可执行程序。
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.import-card {
  max-width: 960px;
}

.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 24px 14px;
  border-bottom: 1px solid var(--divider-subtle);
  gap: 12px;
}

.head-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.modal-head h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
}

.top-mode-pills {
  display: inline-flex;
  padding: 3px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.05);
}

.mode-pill {
  border: none;
  border-radius: 999px;
  padding: 5px 13px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12.5px;
  font-weight: 500;
  transition: background-color 140ms ease, color 140ms ease;
}

.mode-pill:hover {
  color: var(--text-primary);
}

.mode-pill.active {
  background: rgba(255, 255, 255, 0.14);
  color: #ffffff;
}

.modal-head-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.close-icon-btn {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.close-icon-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.modal-body {
  padding: 16px 24px 22px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.search-control-stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.search-bar-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

.search-input {
  flex: 1;
}

.direct-hint-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  border-radius: 9px;
  background: rgba(52, 211, 153, 0.1);
  border: 1px solid rgba(52, 211, 153, 0.22);
  color: var(--emerald-text);
  font-size: 12px;
}

.direct-hint-bar code {
  font-family: var(--font-mono);
  font-size: 11.5px;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.25);
}

.direct-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}

.source-filter-pills {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.src-filter-pill {
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 999px;
  padding: 5px 12px;
  background: rgba(255, 255, 255, 0.03);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  transition: background-color 140ms ease, color 140ms ease, border-color 140ms ease;
}

.src-filter-pill:hover {
  background: rgba(255, 255, 255, 0.09);
  color: var(--text-primary);
}

.src-filter-pill.active {
  background: #f5f5f7;
  border-color: #f5f5f7;
  color: #0a0a0c;
  font-weight: 600;
}

.partial-error-bar {
  padding: 7px 12px;
  border-radius: 9px;
  background: rgba(245, 158, 11, 0.09);
  color: var(--amber-text);
  font-size: 11.5px;
}

/* 候选卡片网格 */
.candidate-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.candidate-card {
  display: flex;
  gap: 12px;
  padding: 10px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  background: rgba(255, 255, 255, 0.03);
  text-align: left;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    border-color var(--duration-fast) var(--ease-out-expo),
    transform var(--duration-fast) var(--ease-out-expo);
}

.candidate-card:hover {
  background: rgba(255, 255, 255, 0.075);
  border-color: rgba(255, 255, 255, 0.14);
  transform: translateY(-1px);
}

.candidate-card.direct-hit {
  border-color: rgba(52, 211, 153, 0.38);
  background: rgba(52, 211, 153, 0.055);
}

.candidate-card.in-library {
  opacity: 0.82;
}

.cand-cover {
  position: relative;
  width: 68px;
  height: 96px;
  border-radius: 7px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.05);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.cand-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cand-no-img {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
}

.cand-source {
  position: absolute;
  bottom: 4px;
  left: 4px;
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 600;
  padding: 2px 5px;
  border-radius: 4px;
  background: rgba(10, 10, 12, 0.84);
  color: var(--text-primary);
}

.cand-source-inline {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 5px;
  flex-shrink: 0;
}

.badge-ymgal {
  background: rgba(139, 92, 246, 0.88);
  color: #ffffff;
}

.badge-kungal {
  background: rgba(14, 165, 233, 0.88);
  color: #ffffff;
}

.badge-touchgal {
  background: rgba(236, 72, 153, 0.88);
  color: #ffffff;
}

.badge-dlsite {
  background: rgba(217, 119, 6, 0.9);
  color: #ffffff;
}

.badge-vndb {
  background: rgba(16, 185, 129, 0.88);
  color: #ffffff;
}

.badge-bangumi {
  background: rgba(244, 63, 94, 0.88);
  color: #ffffff;
}

.badge-steam {
  background: rgba(37, 99, 235, 0.88);
  color: #ffffff;
}

.badge-igdb {
  background: rgba(99, 102, 241, 0.88);
  color: #ffffff;
}

.badge-default {
  background: rgba(39, 39, 42, 0.9);
  color: #f4f4f5;
}

.cand-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cand-title-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.cand-title {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 500;
  color: var(--text-primary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.35;
}

.direct-badge {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--emerald-bg);
  color: var(--emerald-text);
}

.in-lib-badge {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--amber-bg);
  color: var(--amber-text);
}

.cand-orig {
  font-size: 11.5px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cand-meta-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
  color: var(--text-secondary);
  min-width: 0;
}

.cand-dev {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cand-year {
  flex-shrink: 0;
  font-family: var(--font-mono);
  color: var(--text-primary);
  opacity: 0.85;
}

.cand-id {
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
}

.cand-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: auto;
}

.cand-tags span {
  font-size: 10.5px;
  padding: 2px 6px;
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.055);
  color: var(--text-muted);
}

.empty-search {
  grid-column: 1 / -1;
  padding: 42px 20px;
  text-align: center;
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.75;
}

.empty-search strong {
  color: var(--text-secondary);
  font-weight: 500;
}

.center-loading {
  padding: 56px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--text-secondary);
}

.spinner {
  width: 24px;
  height: 24px;
  border: 2px solid rgba(255, 255, 255, 0.14);
  border-top-color: var(--text-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.spinner.small {
  width: 16px;
  height: 16px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* 第二步详情预览 & 跨源补全区 */
.preview-editor,
.local-form,
.batch-panel {
  display: flex;
  flex-direction: column;
  gap: 13px;
}

.preview-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.matched-pills {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 12px;
}

.muted {
  color: var(--text-muted);
}

.src-pill {
  font-family: var(--font-mono);
  font-size: 10.5px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--emerald-bg);
  color: var(--emerald-text);
}

.visual-strip {
  display: grid;
  grid-template-columns: 120px 1fr 1fr;
  gap: 12px;
}

.vis-box {
  position: relative;
  height: 146px;
  border-radius: 11px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.035);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11.5px;
  color: var(--text-muted);
  text-align: center;
  padding: 8px;
}

.vis-box img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.vis-box.logo img {
  object-fit: contain;
  padding: 12px;
}

.vis-tag {
  position: absolute;
  bottom: 6px;
  left: 6px;
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 5px;
  background: rgba(10, 10, 12, 0.78);
  color: var(--text-primary);
}

.enrich-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.enrich-bar-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.enrich-btn.active {
  background: #f5f5f7;
  color: #0a0a0c;
  font-weight: 600;
}

.enrich-close-btn {
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 12px;
  padding: 4px 8px;
}

.enrich-close-btn:hover {
  color: var(--text-primary);
}

.enrich-drawer {
  padding: 12px;
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.028);
  border: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.enrich-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 20px 10px;
  font-size: 12.5px;
  color: var(--text-secondary);
}

.enrich-desc-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 240px;
  overflow-y: auto;
}

.enrich-desc-card {
  padding: 10px 12px;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.03);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.enrich-desc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.enrich-desc-title-row {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  flex: 1;
}

.enrich-desc-title {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.zh-chip {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--emerald-bg);
  color: var(--emerald-text);
  flex-shrink: 0;
}

.enrich-year {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.enrich-desc-btns {
  display: inline-flex;
  gap: 6px;
  flex-shrink: 0;
}

.enrich-desc-text {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: var(--text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.enrich-vis-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.enrich-vis-grid {
  display: grid;
  gap: 8px;
  max-height: 250px;
  overflow-y: auto;
}

.enrich-vis-grid.covers {
  grid-template-columns: repeat(auto-fill, minmax(94px, 1fr));
}

.enrich-vis-grid.backgrounds,
.enrich-vis-grid.logos {
  grid-template-columns: repeat(auto-fill, minmax(175px, 1fr));
}

.enrich-vis-card {
  position: relative;
  border-radius: 8px;
  overflow: hidden;
  border: 2px solid transparent;
  background: rgba(255, 255, 255, 0.04);
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 140ms ease, transform 140ms ease;
}

.enrich-vis-grid.covers .enrich-vis-card {
  aspect-ratio: 2 / 3;
}

.enrich-vis-grid.backgrounds .enrich-vis-card,
.enrich-vis-grid.logos .enrich-vis-card {
  aspect-ratio: 16 / 9;
}

.enrich-vis-card:hover {
  border-color: rgba(255, 255, 255, 0.3);
}

.enrich-vis-card.selected {
  border-color: #34d399;
}

.enrich-vis-card img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.enrich-vis-grid.logos .enrich-vis-card img {
  object-fit: contain;
  padding: 10px;
}

.enrich-vis-meta {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 3px 6px;
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.82));
  display: flex;
  justify-content: space-between;
  font-size: 9.5px;
  color: #f4f4f5;
}

.enrich-empty {
  padding: 18px;
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.field label {
  font-size: 12px;
  color: var(--text-secondary);
}

.field-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.field-grid.three {
  grid-template-columns: repeat(3, 1fr);
}

.row-with-btn {
  display: flex;
  gap: 8px;
}

.preview-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--divider-subtle);
}

.preview-toggles {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
}

.bgm-opt-check {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
}

.bgm-opt-check:hover {
  color: var(--text-secondary);
}

.opt-checkbox {
  width: 14px;
  height: 14px;
  accent-color: #f4f4f5;
  cursor: pointer;
}

.nsfw-inline {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  color: var(--text-secondary);
  cursor: pointer;
}

/* Segmented Switch for Local Single vs Batch */
.local-mode-switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  padding: 3px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.045);
}

.local-mode-switch button {
  padding: 8px 12px;
  border-radius: 8px;
  border: none;
  background: transparent;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  transition: background-color 140ms ease, color 140ms ease;
}

.local-mode-switch button:hover {
  color: var(--text-primary);
}

.local-mode-switch button.active {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.batch-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.035);
  margin-bottom: 8px;
}

.batch-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.batch-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.03);
}

.batch-checkbox {
  margin-top: 10px;
  width: 16px;
  height: 16px;
  accent-color: #f4f4f5;
  cursor: pointer;
}

.batch-fields {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.batch-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.batch-title-input {
  flex: 1;
}

.imported-tag {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 999px;
  background: var(--amber-bg);
  color: var(--amber-text);
  white-space: nowrap;
}

/* 附带影音（可选）内联折叠区 */
.optional-media-box {
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.028);
  border: 1px solid rgba(255, 255, 255, 0.06);
  overflow: hidden;
}

.optional-media-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 14px;
}

.optional-toggle {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  border: none;
  background: transparent;
  padding: 0;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 500;
}

.opt-chevron {
  color: var(--text-muted);
  transition: transform var(--duration-fast) var(--ease-out-expo);
}

.opt-chevron.open {
  transform: rotate(90deg);
  color: var(--text-primary);
}

.opt-chosen-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.12);
  color: #f5f5f7;
  font-size: 11px;
  font-weight: 500;
}

.opt-clear {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1;
}

.opt-clear:hover {
  color: #ffffff;
}

.optional-quick-btns {
  display: inline-flex;
  gap: 6px;
  flex-shrink: 0;
}

.opt-mode-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 14px 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.055);
  background: rgba(255, 255, 255, 0.014);
}

.opt-mode-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.opt-mode-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

.opt-mode-ready {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(52, 211, 153, 0.14);
  color: #6ee7b7;
}

.opt-mode-hint-tag {
  font-size: 11px;
  color: var(--text-muted);
}

.opt-mode-segment {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.045);
}

.opt-mode-btn {
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  font-size: 11.5px;
  padding: 4px 9px;
  cursor: pointer;
  transition: background-color 140ms ease, color 140ms ease;
}

.opt-mode-btn:hover {
  color: var(--text-primary);
}

.opt-mode-btn.active {
  background: rgba(255, 255, 255, 0.14);
  color: #f5f5f7;
  font-weight: 500;
}

.opt-mode-note {
  margin: 2px 0 0;
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--text-muted);
}

.opt-mode-note strong {
  color: var(--text-secondary);
  font-weight: 500;
}

.optional-media-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  padding: 12px 14px 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.opt-col {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.opt-col-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11.5px;
  color: var(--text-secondary);
}

.opt-clear-text {
  border: none;
  background: transparent;
  padding: 0;
  font-size: 11px;
  color: var(--text-muted);
}

.opt-clear-text:hover {
  color: var(--text-primary);
}

.opt-cand-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
  max-height: 186px;
  overflow-y: auto;
}

.opt-cand-row {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 6px 8px;
  border: none;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  text-align: left;
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.opt-cand-row:hover {
  background: rgba(255, 255, 255, 0.07);
}

.opt-cand-row.selected {
  background: rgba(255, 255, 255, 0.13);
}

.opt-thumb {
  border-radius: 5px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.opt-thumb.wide {
  width: 58px;
  height: 34px;
}

.opt-thumb.square {
  width: 34px;
  height: 34px;
}

.opt-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.opt-cand-info {
  flex: 1;
  min-width: 0;
}

.opt-cand-title {
  font-size: 12px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.opt-cand-meta {
  display: flex;
  gap: 8px;
  font-size: 10.5px;
  color: var(--text-muted);
  margin-top: 2px;
}

.opt-check {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
  flex-shrink: 0;
}

.opt-cand-row.selected .opt-check {
  background: #f5f5f7;
  color: #0a0a0c;
  font-weight: 600;
}

.opt-empty {
  padding: 14px 8px;
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.02);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.opt-source-pills {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 3px;
  padding: 2px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.035);
  width: fit-content;
}

.opt-src-pill {
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  font-size: 11px;
  padding: 3px 8px;
  cursor: pointer;
  transition: background-color 140ms ease, color 140ms ease;
}

.opt-src-pill:hover:not(:disabled) {
  color: var(--text-primary);
}

.opt-src-pill.active {
  background: rgba(255, 255, 255, 0.14);
  color: #f5f5f7;
  font-weight: 500;
}

.opt-search-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.opt-search-input {
  height: 28px;
  padding: 0 9px;
  font-size: 11.5px;
  border-radius: 7px;
}

.opt-search-btn {
  height: 28px;
  padding: 0 10px;
  font-size: 11.5px;
  flex-shrink: 0;
}

.opt-hint-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  font-size: 11px;
  color: var(--text-muted);
  padding: 5px 8px;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.03);
}

.opt-empty-links {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.opt-inline-link {
  border: none;
  background: transparent;
  padding: 0;
  color: #f4f4f5;
  font-size: 11px;
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
  opacity: 0.85;
}

.opt-inline-link:hover {
  opacity: 1;
}

.sgdb-subtle-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-muted);
}

.sgdb-subtle-btn {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
}

.sgdb-subtle-btn:hover {
  color: var(--text-primary);
}

.opt-official-badge {
  display: inline-flex;
  align-items: center;
  padding: 0 5px;
  border-radius: 4px;
  background: rgba(244, 244, 245, 0.14);
  color: #f5f5f7;
  font-size: 10px;
  font-weight: 500;
}

@media (max-width: 720px) {
  .candidate-grid,
  .optional-media-body,
  .visual-strip {
    grid-template-columns: 1fr;
  }
}
</style>
