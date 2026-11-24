import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import {
  collectionsApi,
  gamesApi,
  libraryApi,
  scraperApi,
  settingsApi,
  systemApi,
} from '@/api/client'
import { useAudioStore } from '@/stores/audio'
import type {
  ActiveStatusFilter,
  AppSettings,
  CollectionItem,
  CollectionItemInput,
  CollectionType,
  DroppedFileInfo,
  ExternalImportSource,
  Game,
  GameUpdatePayload,
  HealthInfo,
  ImportTab,
  LibrarySortBy,
  LibrarySortOrder,
  RunningStatus,
  SettingsSectionId,
  ShelfBgMode,
  ShelfViewMode,
  ToastMessage,
} from '@/types'
import {
  getSortOption,
  normalizeSortBy,
  normalizeSortOrder,
  sortGames,
} from '@/utils/sortGames'

const SORT_BY_LS_KEY = 'tsumugi:library:sort_by'
const SORT_ORDER_LS_KEY = 'tsumugi:library:sort_order'

function loadStoredSortBy(): LibrarySortBy {
  try {
    return normalizeSortBy(window.localStorage.getItem(SORT_BY_LS_KEY))
  } catch {
    return 'series_name'
  }
}

function loadStoredSortOrder(): LibrarySortOrder {
  try {
    const raw = window.localStorage.getItem(SORT_ORDER_LS_KEY)
    return raw ? normalizeSortOrder(raw) : 'asc'
  } catch {
    return 'asc'
  }
}

function normalizeStatusFilter(raw: string): ActiveStatusFilter {
  const s = (raw || 'all').trim().toLowerCase()
  if (s === 'playing') return 'playing'
  if (s === 'unplayed' || s === 'todo') return 'unplayed'
  if (s === 'completed' || s === 'done') return 'completed'
  return 'all'
}

export function matchesStatusFilter(gameStatus: string, filter: ActiveStatusFilter): boolean {
  if (filter === 'all') return true
  const s = (gameStatus || 'todo').trim().toLowerCase()
  if (filter === 'playing') return s === 'playing'
  if (filter === 'unplayed') return s === 'unplayed' || s === 'todo'
  if (filter === 'completed') return s === 'completed' || s === 'done'
  return true
}

const DEFAULT_SETTINGS: AppSettings = {
  last_active_game_id: null,
  shelf_view_mode: 'showcase',
  shelf_bg_mode: 'linked',
  bgm_autoplay: true,
  gallery_particles: true,
  proxy_url: '',
  le_exe_path: '',
  api_keys: {
    steamgriddb: '',
    touchgal: '',
    bangumi: '',
  },
  allow_nsfw_scrape: true,
  privacy_blur_mode: false,
  library_sort_by: loadStoredSortBy(),
  library_sort_order: loadStoredSortOrder(),
}

const DEFAULT_RUNNING: RunningStatus = {
  running: false,
  game_id: null,
  title: '',
  elapsed_seconds: 0,
  total_seconds: 0,
  pid: null,
  is_mock: true,
  started_at: null,
  platform: '',
}

export const useLibraryStore = defineStore('library', () => {
  const games = ref<Game[]>([])
  const collections = ref<CollectionItem[]>([])
  const activeCollectionId = ref<number | null>(null)
  const settings = ref<AppSettings>({ ...DEFAULT_SETTINGS })
  const activeGameId = ref<number | null>(null)
  const viewMode = ref<'detail' | 'shelf'>('detail')
  const activeStatus = ref<ActiveStatusFilter>('all')
  const filterStatus = computed<ActiveStatusFilter>(() => activeStatus.value)
  const filterTag = ref<string>('')
  const running = ref<RunningStatus>({ ...DEFAULT_RUNNING })
  const launching = ref<boolean>(false)
  const audioStore = useAudioStore()
  const health = ref<HealthInfo | null>(null)

  watch(
    () => running.value.running || launching.value,
    (suppressed) => {
      audioStore.setAutoplaySuppressed(suppressed)
    },
    { immediate: true },
  )
  const loading = ref<boolean>(false)
  const isInitialized = ref<boolean>(false)
  const assetVersion = ref<number>(Date.now())

  // 全局弹窗状态
  const showImportModal = ref(false)
  const importInitialTab = ref<ImportTab>('aggregated')
  const importInitialLocalMode = ref<'single' | 'batch'>('single')
  const droppedFileInfo = ref<DroppedFileInfo | null>(null)
  const showExternalImportModal = ref(false)
  const externalImportSource = ref<ExternalImportSource>('playnite')
  const showQuickSearch = ref(false)
  const showSettingsModal = ref(false)
  const settingsInitialSection = ref<SettingsSectionId>('general')
  const settingsInitialExpandSource = ref<string | null>(null)
  const showEditModal = ref(false)
  const editInitialTab = ref<'meta' | 'media' | 'launch'>('meta')
  const showTimeLedger = ref(false)
  const showCollectionModal = ref(false)
  const collectionModalMode = ref<'create' | 'edit'>('create')
  const collectionModalTargetId = ref<number | null>(null)

  // 全局轻量通知（最多同时保留 3 条）
  const toasts = ref<ToastMessage[]>([])
  let nextToastId = 1
  let tickTimer: number | null = null
  let syncTimer: number | null = null

  function notify(
    message: string,
    type: ToastMessage['type'] = 'info',
    durationMs = 3600,
    action?: { label: string; onClick: () => void },
  ) {
    const id = nextToastId++
    const nextItem: ToastMessage = {
      id,
      message,
      type,
      actionLabel: action?.label,
      onAction: action?.onClick,
    }
    const list = [...toasts.value, nextItem]
    toasts.value = list.length > 3 ? list.slice(list.length - 3) : list
    window.setTimeout(() => {
      toasts.value = toasts.value.filter((t) => t.id !== id)
    }, durationMs)
  }

  function dismissToast(id: number) {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }

  function openSettings(
    section: SettingsSectionId = 'general',
    expandSource: string | null = null,
  ) {
    settingsInitialSection.value = section
    settingsInitialExpandSource.value = expandSource
    showSettingsModal.value = true
  }

  function openEditModal(initialTab: 'meta' | 'media' | 'launch' = 'meta') {
    editInitialTab.value = initialTab
    showEditModal.value = true
  }

  const activeCollection = computed<CollectionItem | null>(() => {
    if (activeCollectionId.value === null) return null
    return collections.value.find((c) => c.id === activeCollectionId.value) || null
  })

  const activeCollectionGameIdSet = computed<Set<number> | null>(() => {
    const col = activeCollection.value
    if (!col) return null
    return new Set(col.game_ids)
  })

  const sortBy = computed<LibrarySortBy>(() => normalizeSortBy(settings.value.library_sort_by))
  const sortOrder = computed<LibrarySortOrder>(() =>
    normalizeSortOrder(settings.value.library_sort_order),
  )

  const filteredGames = computed(() => {
    const colSet = activeCollectionGameIdSet.value
    const matched = games.value.filter((g) => {
      if (colSet && !colSet.has(g.id)) {
        return false
      }
      if (!matchesStatusFilter(g.status, activeStatus.value)) {
        return false
      }
      if (filterTag.value && !(g.tags || []).includes(filterTag.value)) {
        return false
      }
      return true
    })
    return sortGames(matched, sortBy.value, sortOrder.value)
  })

  const activeGame = computed<Game | null>(() => {
    if (activeGameId.value != null) {
      const found = games.value.find((g) => g.id === activeGameId.value)
      if (found) return found
    }
    return filteredGames.value[0] || games.value[0] || null
  })

  const statusCounts = computed(() => {
    let unplayed = 0
    let playing = 0
    let completed = 0
    for (const g of games.value) {
      const s = (g.status || 'todo').toLowerCase()
      if (s === 'playing') playing++
      else if (s === 'done' || s === 'completed') completed++
      else unplayed++
    }
    return {
      all: games.value.length,
      unplayed,
      todo: unplayed,
      playing,
      completed,
      done: completed,
    }
  })

  const collectionStatusCounts = computed(() => {
    const colSet = activeCollectionGameIdSet.value
    const base = colSet ? games.value.filter((g) => colSet.has(g.id)) : games.value
    let unplayed = 0
    let playing = 0
    let completed = 0
    for (const g of base) {
      const s = (g.status || 'todo').toLowerCase()
      if (s === 'playing') playing++
      else if (s === 'done' || s === 'completed') completed++
      else unplayed++
    }
    return {
      all: base.length,
      playing,
      unplayed,
      completed,
    }
  })

  const allTags = computed(() => {
    const map = new Map<string, number>()
    for (const g of games.value) {
      for (const t of g.tags || []) {
        if (!t) continue
        map.set(t, (map.get(t) || 0) + 1)
      }
    }
    return Array.from(map.entries())
      .map(([tag, count]) => ({ tag, count }))
      .sort((a, b) => b.count - a.count)
  })

  const privacyBlurMode = computed(() => Boolean(settings.value.privacy_blur_mode))
  const shelfViewMode = computed<ShelfViewMode>(() =>
    settings.value.shelf_view_mode === 'spine' ? 'spine' : 'showcase',
  )
  const shelfBgMode = computed<ShelfBgMode>(() => {
    const raw = settings.value.shelf_bg_mode
    if (raw === 'random' || raw === 'minimal') return raw
    return 'linked'
  })
  const bgmAutoplay = computed(() => settings.value.bgm_autoplay !== false)
  const galleryParticles = computed(() => settings.value.gallery_particles !== false)

  function shouldBlurGame(game?: Game | null): boolean {
    if (!game) return false
    return privacyBlurMode.value && Boolean(game.is_nsfw)
  }

  function _startRunningTimers() {
    _stopRunningTimers()
    tickTimer = window.setInterval(() => {
      if (running.value.running) {
        running.value.elapsed_seconds += 1
        running.value.total_seconds += 1
      }
    }, 1000)
    syncTimer = window.setInterval(() => {
      void syncRunningStatus()
    }, 5000)
  }

  function _stopRunningTimers() {
    if (tickTimer !== null) {
      clearInterval(tickTimer)
      tickTimer = null
    }
    if (syncTimer !== null) {
      clearInterval(syncTimer)
      syncTimer = null
    }
  }

  async function syncRunningStatus() {
    const wasRunning = running.value.running
    const prevGameId = running.value.game_id
    const prevTitle = running.value.title

    try {
      const st = await libraryApi.running()
      running.value = st
      if (st.running) {
        if (!tickTimer) _startRunningTimers()
      } else {
        _stopRunningTimers()
        if (wasRunning && prevGameId != null) {
          await refreshGame(prevGameId)
          activeGameId.value = prevGameId
          viewMode.value = 'detail'
          notify(`《${prevTitle}》已退出，游玩时长已自动落盘`, 'success')
        }
      }
    } catch {
      // ignore transient poll failures
    }
  }

  async function initialize() {
    loading.value = true
    try {
      const [cfgRes, listRes, colRes, runRes, healthRes] = await Promise.allSettled([
        settingsApi.getAll(),
        gamesApi.list(),
        collectionsApi.list(),
        libraryApi.running(),
        systemApi.health(),
      ])

      if (cfgRes.status === 'fulfilled') {
        const cfg = cfgRes.value
        settings.value = {
          ...DEFAULT_SETTINGS,
          ...cfg,
          api_keys: { ...DEFAULT_SETTINGS.api_keys, ...(cfg.api_keys || {}) },
        }
      }

      const list = listRes.status === 'fulfilled' ? listRes.value : []
      if (listRes.status === 'rejected') {
        const err = listRes.reason
        notify(err instanceof Error ? err.message : '初始化游戏库失败', 'error')
      }
      games.value = list

      if (colRes.status === 'fulfilled') {
        collections.value = colRes.value
      }

      const runSt = runRes.status === 'fulfilled' ? runRes.value : { ...DEFAULT_RUNNING }
      running.value = runSt

      if (healthRes.status === 'fulfilled') {
        health.value = healthRes.value
      }

      if (runSt.running && runSt.game_id != null && list.some((g) => g.id === runSt.game_id)) {
        activeGameId.value = runSt.game_id
      } else if (
        settings.value.last_active_game_id != null &&
        list.some((g) => g.id === settings.value.last_active_game_id)
      ) {
        activeGameId.value = settings.value.last_active_game_id
      } else {
        activeGameId.value = filteredGames.value[0]?.id ?? list[0]?.id ?? null
      }

      viewMode.value = 'detail'
      if (runSt.running) {
        _startRunningTimers()
      }
    } finally {
      loading.value = false
      isInitialized.value = true
    }
  }

  async function refreshGames() {
    const list = await gamesApi.list()
    games.value = list
    if (activeGameId.value != null && !list.some((g) => g.id === activeGameId.value)) {
      activeGameId.value = list[0]?.id ?? null
    }
  }

  async function refreshGame(gameId: number) {
    try {
      const fresh = await gamesApi.get(gameId, false)
      const idx = games.value.findIndex((g) => g.id === gameId)
      if (idx >= 0) {
        games.value[idx] = fresh
      } else {
        games.value.push(fresh)
      }
      assetVersion.value = Date.now()
      return fresh
    } catch {
      return null
    }
  }

  async function selectGame(
    gameId: number,
    options: { switchToDetail?: boolean; recordActive?: boolean } = {},
  ) {
    activeGameId.value = gameId
    if (options.switchToDetail) {
      viewMode.value = 'detail'
    }
    if (options.recordActive !== false) {
      try {
        const fresh = await gamesApi.get(gameId, true)
        const idx = games.value.findIndex((g) => g.id === gameId)
        if (idx >= 0) games.value[idx] = fresh
        settings.value.last_active_game_id = gameId
      } catch {
        // ignore
      }
    }
  }

  function setViewMode(mode: 'detail' | 'shelf') {
    viewMode.value = mode
  }

  function setActiveStatus(status: ActiveStatusFilter | 'todo' | 'done') {
    activeStatus.value = normalizeStatusFilter(status)
    if (
      filteredGames.value.length > 0 &&
      !filteredGames.value.some((g) => g.id === activeGameId.value)
    ) {
      void selectGame(filteredGames.value[0].id, { recordActive: false })
    }
  }

  function setFilterStatus(status: ActiveStatusFilter | 'todo' | 'done') {
    setActiveStatus(status)
  }

  function setFilterTag(tag: string) {
    filterTag.value = filterTag.value === tag ? '' : tag
  }

  let sortPersistTimer: number | null = null

  function _persistSortPreference(by: LibrarySortBy, order: LibrarySortOrder) {
    try {
      window.localStorage.setItem(SORT_BY_LS_KEY, by)
      window.localStorage.setItem(SORT_ORDER_LS_KEY, order)
    } catch {
      // ignore storage errors
    }
    if (sortPersistTimer !== null) {
      clearTimeout(sortPersistTimer)
    }
    sortPersistTimer = window.setTimeout(() => {
      sortPersistTimer = null
      void Promise.all([
        settingsApi.update('library_sort_by', by).catch(() => null),
        settingsApi.update('library_sort_order', order).catch(() => null),
      ])
    }, 240)
  }

  function setSort(by: LibrarySortBy, order?: LibrarySortOrder) {
    const nextBy = normalizeSortBy(by)
    const nextOrder: LibrarySortOrder =
      order ??
      (nextBy === sortBy.value
        ? sortOrder.value === 'asc'
          ? 'desc'
          : 'asc'
        : getSortOption(nextBy).defaultOrder)

    settings.value = {
      ...settings.value,
      library_sort_by: nextBy,
      library_sort_order: nextOrder,
    }
    _persistSortPreference(nextBy, nextOrder)
  }

  function toggleSortOrder() {
    const nextOrder: LibrarySortOrder = sortOrder.value === 'asc' ? 'desc' : 'asc'
    settings.value = {
      ...settings.value,
      library_sort_order: nextOrder,
    }
    _persistSortPreference(sortBy.value, nextOrder)
  }

  function setActiveCollection(collectionId: number | null) {
    activeCollectionId.value = collectionId
    if (
      filteredGames.value.length > 0 &&
      !filteredGames.value.some((g) => g.id === activeGameId.value)
    ) {
      void selectGame(filteredGames.value[0].id, { recordActive: false })
    }
  }

  // ─────────────── 系列合集 / 分组 CRUD（双向同步单一数据源） ───────────────

  function _syncActiveGameCollectionsCache() {
    const activeId = activeGameId.value
    if (activeId == null) return
    const idx = games.value.findIndex((g) => g.id === activeId)
    if (idx < 0) return
    const memberships = collections.value
      .filter((col) => (col.items || []).some((it) => it.game_id === activeId) || col.game_ids.includes(activeId))
      .map((col) => {
        const entry = (col.items || []).find((it) => it.game_id === activeId)
        return {
          id: col.id,
          name: col.name,
          description: col.description || '',
          collection_type: col.collection_type || 'series',
          relation_label: entry?.relation_label || '',
          position: entry?.position ?? 0,
          total_count: col.total_count ?? col.game_ids.length,
          completed_count: col.completed_count ?? 0,
          items: col.items || [],
        }
      })
    games.value[idx] = {
      ...games.value[idx],
      collections: memberships,
    }
  }

  async function fetchCollections() {
    collections.value = await collectionsApi.list()
    if (
      activeCollectionId.value !== null &&
      !collections.value.some((c) => c.id === activeCollectionId.value)
    ) {
      activeCollectionId.value = null
    }
    _syncActiveGameCollectionsCache()
  }

  function _upsertCollection(col: CollectionItem) {
    const idx = collections.value.findIndex((c) => c.id === col.id)
    if (idx >= 0) {
      collections.value[idx] = col
    } else {
      collections.value.push(col)
    }
    _syncActiveGameCollectionsCache()
  }

  async function createCollection(
    nameOrOpts:
      | string
      | {
          name: string
          description?: string
          collection_type?: CollectionType
          game_ids?: number[]
          items?: CollectionItemInput[]
        },
    gameIds: number[] = [],
    activate = false,
  ) {
    const payload =
      typeof nameOrOpts === 'string'
        ? { name: nameOrOpts, game_ids: gameIds }
        : nameOrOpts
    const created = await collectionsApi.create(payload)
    _upsertCollection(created)
    if (activate) {
      setActiveCollection(created.id)
    }
    notify(`已创建合集「${created.name}」`, 'success')
    return created
  }

  async function updateCollectionMeta(
    collectionId: number,
    patch: {
      name?: string
      description?: string
      collection_type?: CollectionType
      sort_order?: number
    },
  ) {
    const updated = await collectionsApi.update(collectionId, patch)
    _upsertCollection(updated)
    return updated
  }

  async function renameCollection(collectionId: number, name: string) {
    const updated = await collectionsApi.update(collectionId, { name })
    _upsertCollection(updated)
    notify(`合集已重命名为「${updated.name}」`, 'info')
    return updated
  }

  async function deleteCollection(collectionId: number) {
    const target = collections.value.find((c) => c.id === collectionId)
    await collectionsApi.remove(collectionId)
    collections.value = collections.value.filter((c) => c.id !== collectionId)
    if (activeCollectionId.value === collectionId) {
      activeCollectionId.value = null
    }
    _syncActiveGameCollectionsCache()
    notify(`已删除合集「${target?.name || ''}」（游戏本体已保留）`, 'info')
  }

  async function setCollectionItems(collectionId: number, items: CollectionItemInput[]) {
    const updated = await collectionsApi.replaceItems(collectionId, items)
    _upsertCollection(updated)
    if (
      activeCollectionId.value === collectionId &&
      filteredGames.value.length > 0 &&
      !filteredGames.value.some((g) => g.id === activeGameId.value)
    ) {
      void selectGame(filteredGames.value[0].id, { recordActive: false })
    }
    return updated
  }

  async function addCollectionItem(
    collectionId: number,
    gameId: number,
    relationLabel = '',
  ) {
    const updated = await collectionsApi.addItem(collectionId, {
      game_id: gameId,
      relation_label: relationLabel,
    })
    _upsertCollection(updated)
    return updated
  }

  async function removeCollectionItem(collectionId: number, gameId: number) {
    const updated = await collectionsApi.removeItem(collectionId, gameId)
    _upsertCollection(updated)
    return updated
  }

  async function setCollectionGames(collectionId: number, gameIds: number[]) {
    const updated = await collectionsApi.replaceGames(collectionId, gameIds)
    _upsertCollection(updated)
    if (
      activeCollectionId.value === collectionId &&
      filteredGames.value.length > 0 &&
      !filteredGames.value.some((g) => g.id === activeGameId.value)
    ) {
      void selectGame(filteredGames.value[0].id, { recordActive: false })
    }
    return updated
  }

  async function toggleGameInCollection(collectionId: number, gameId: number) {
    const col = collections.value.find((c) => c.id === collectionId)
    if (!col) return
    const exists = col.game_ids.includes(gameId)
    const updated = exists
      ? await collectionsApi.removeItem(collectionId, gameId)
      : await collectionsApi.addItem(collectionId, { game_id: gameId })
    _upsertCollection(updated)
    return updated
  }

  function openCreateCollectionModal() {
    collectionModalMode.value = 'create'
    collectionModalTargetId.value = null
    showCollectionModal.value = true
  }

  function openEditCollectionModal(collectionId: number) {
    collectionModalMode.value = 'edit'
    collectionModalTargetId.value = collectionId
    showCollectionModal.value = true
  }

  // ─────────────── 设置与游戏操作 ───────────────

  async function updateSetting<K extends keyof AppSettings>(key: K, value: AppSettings[K]) {
    settings.value = { ...settings.value, [key]: value }
    try {
      await settingsApi.update(key, value)
    } catch (err) {
      notify(err instanceof Error ? err.message : '保存设置失败', 'error')
    }
  }

  async function togglePrivacyBlur() {
    const next = !settings.value.privacy_blur_mode
    await updateSetting('privacy_blur_mode', next)
    notify(next ? '已开启隐私模式' : '已关闭隐私模式', 'info')
  }

  async function toggleShelfViewMode(mode?: ShelfViewMode) {
    const next: ShelfViewMode = mode ?? (shelfViewMode.value === 'showcase' ? 'spine' : 'showcase')
    await updateSetting('shelf_view_mode', next)
  }

  async function launchGame(gameId: number) {
    // 零延迟抑制自动播放并淡出暂停全部 BGM / OP / PV（不等后端接口返回）
    launching.value = true
    audioStore.setAutoplaySuppressed(true)
    void audioStore.pauseAllMedia({ fadeOutMs: 250 })
    try {
      const res = await gamesApi.launch(gameId)
      running.value = res.tracker
      activeGameId.value = gameId
      await refreshGame(gameId)
      _startRunningTimers()
      notify(res.message || `已启动《${res.title}》`, 'success')
    } catch (err) {
      notify(err instanceof Error ? err.message : '启动游戏失败', 'error')
    } finally {
      launching.value = false
      audioStore.setAutoplaySuppressed(Boolean(running.value.running))
    }
  }

  async function stopRunningGame(terminateProcess = false) {
    try {
      const res = await libraryApi.stopRunning(terminateProcess)
      _stopRunningTimers()
      running.value = {
        ...DEFAULT_RUNNING,
        is_mock: running.value.is_mock,
        platform: running.value.platform,
      }
      if (res.game_id != null) {
        await refreshGame(res.game_id)
        activeGameId.value = res.game_id
        viewMode.value = 'detail'
      }
      notify(res.message || '游戏已结束，时长已落盘', 'success')
    } catch (err) {
      notify(err instanceof Error ? err.message : '停止游戏失败', 'error')
    }
  }

  async function updateGamePatch(gameId: number, patch: GameUpdatePayload) {
    const updated = await gamesApi.update(gameId, patch)
    const idx = games.value.findIndex((g) => g.id === gameId)
    if (idx >= 0) {
      games.value[idx] = updated
    }
    if (patch.media) {
      assetVersion.value = Date.now()
    }
    if (patch.status !== undefined || patch.title !== undefined || patch.is_nsfw !== undefined) {
      void fetchCollections().catch(() => {})
    }
    return updated
  }

  async function deleteGameById(gameId: number) {
    await gamesApi.remove(gameId)
    games.value = games.value.filter((g) => g.id !== gameId)
    void fetchCollections().catch(() => {})
    if (activeGameId.value === gameId) {
      activeGameId.value = games.value[0]?.id ?? null
    }
    notify('已从游戏库中删除该游戏及本地资产', 'info')
  }

  async function refreshMetadata(gameId: number) {
    const updated = await scraperApi.refresh(gameId)
    const idx = games.value.findIndex((g) => g.id === gameId)
    if (idx >= 0) {
      games.value[idx] = updated
    }
    assetVersion.value = Date.now()
    notify('已完成多源刮削刷新（已自动跳过锁定字段）', 'success')
    return updated
  }

  function addOrFocusGame(game: Game) {
    const idx = games.value.findIndex((g) => g.id === game.id)
    if (idx >= 0) {
      games.value[idx] = game
    } else {
      games.value.push(game)
    }
    activeGameId.value = game.id
    settings.value.last_active_game_id = game.id
    viewMode.value = 'detail'
    assetVersion.value = Date.now()
  }

  function openImport(
    tab: ImportTab = 'aggregated',
    localMode: 'single' | 'batch' = 'single',
    dropped: DroppedFileInfo | null = null,
  ) {
    importInitialTab.value = tab
    importInitialLocalMode.value = localMode
    droppedFileInfo.value = dropped
    showImportModal.value = true
  }

  function openExternalImport(source: ExternalImportSource = 'playnite') {
    externalImportSource.value = source
    showImportModal.value = false
    showSettingsModal.value = false
    showExternalImportModal.value = true
  }

  function syncGameFromServer(updated: Game, options: { bumpAsset?: boolean } = {}) {
    const idx = games.value.findIndex((g) => g.id === updated.id)
    if (idx >= 0) {
      games.value[idx] = updated
    } else {
      games.value.push(updated)
    }
    if (options.bumpAsset !== false) {
      assetVersion.value = Date.now()
    }
  }

  function setGameNotesCount(gameId: number, count: number) {
    const idx = games.value.findIndex((g) => g.id === gameId)
    if (idx >= 0) {
      games.value[idx] = {
        ...games.value[idx],
        notes_count: Math.max(0, count),
      }
    }
  }

  function bumpAssetVersion() {
    assetVersion.value = Date.now()
  }

  return {
    games,
    collections,
    activeCollectionId,
    activeCollection,
    settings,
    activeGameId,
    viewMode,
    activeStatus,
    filterStatus,
    filterTag,
    sortBy,
    sortOrder,
    running,
    health,
    loading,
    isInitialized,
    assetVersion,
    showImportModal,
    importInitialTab,
    importInitialLocalMode,
    droppedFileInfo,
    showExternalImportModal,
    externalImportSource,
    showQuickSearch,
    showSettingsModal,
    settingsInitialSection,
    settingsInitialExpandSource,
    showEditModal,
    editInitialTab,
    showTimeLedger,
    showCollectionModal,
    collectionModalMode,
    collectionModalTargetId,
    toasts,
    filteredGames,
    activeGame,
    statusCounts,
    collectionStatusCounts,
    allTags,
    privacyBlurMode,
    shelfViewMode,
    shelfBgMode,
    bgmAutoplay,
    galleryParticles,
    notify,
    dismissToast,
    openSettings,
    openEditModal,
    shouldBlurGame,
    initialize,
    refreshGames,
    refreshGame,
    selectGame,
    setViewMode,
    setActiveStatus,
    setFilterStatus,
    setFilterTag,
    setSort,
    toggleSortOrder,
    setActiveCollection,
    fetchCollections,
    createCollection,
    updateCollectionMeta,
    renameCollection,
    deleteCollection,
    setCollectionItems,
    addCollectionItem,
    removeCollectionItem,
    setCollectionGames,
    toggleGameInCollection,
    openCreateCollectionModal,
    openEditCollectionModal,
    updateSetting,
    togglePrivacyBlur,
    toggleShelfViewMode,
    launchGame,
    stopRunningGame,
    syncRunningStatus,
    updateGamePatch,
    deleteGameById,
    refreshMetadata,
    addOrFocusGame,
    openImport,
    openExternalImport,
    syncGameFromServer,
    setGameNotesCount,
    bumpAssetVersion,
  }
})
