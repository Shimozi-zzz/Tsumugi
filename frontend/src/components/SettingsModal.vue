<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  isDesktopBridgeAvailable,
  pickBackupOpenPath,
  pickBackupSavePath,
  pickNativeFile,
  scraperApi,
  systemApi,
} from '@/api/client'
import {
  FREE_SCRAPER_SOURCES,
  KEY_SCRAPER_SOURCES,
  type ScraperFieldConfig,
  type ScraperSourceConfig,
} from '@/config/scraperSources'
import { useLibraryStore } from '@/stores/library'
import type {
  AppVersionInfo,
  AutoSnapshotItem,
  BangumiMeResponse,
  ScraperSettingsResponse,
  ScraperTestResponse,
  SettingsSectionId,
  StorageUsageResponse,
  UpdateCheckResponse,
} from '@/types'

const DEFAULT_SOURCE_LINKS: Record<string, string> = {
  ymgal: 'https://www.ymgal.games/developer',
  kungal: 'https://www.kungal.com',
  bangumi: 'https://next.bgm.tv/demo/access-token',
  touchgal: 'https://developer.touchgal.com',
  steamgriddb: 'https://www.steamgriddb.com/profile/preferences/api',
  igdb: 'https://dev.twitch.tv/console/apps',
}

const store = useLibraryStore()
const saving = ref(false)
const hasDesktopBridge = isDesktopBridgeAvailable()
const activeSection = ref<SettingsSectionId>(store.settingsInitialSection || 'general')

const navSections: { id: SettingsSectionId; label: string }[] = [
  { id: 'general', label: '常规与隐私' },
  { id: 'network', label: '网络与启动' },
  { id: 'sources', label: '元数据刮削源' },
  { id: 'data', label: '数据管理' },
  { id: 'environment', label: '运行环境' },
]

const SECRET_KEYS = new Set([
  'ymgal_client_secret',
  'kungal_token',
  'bangumi_token',
  'touchgal_api_key',
  'steamgriddb_api_key',
  'igdb_client_secret',
])

const form = reactive({
  proxy_url: store.settings.proxy_url || '',
  le_exe_path: store.settings.le_exe_path || '',
  allow_nsfw_scrape: Boolean(store.settings.allow_nsfw_scrape),
  privacy_blur_mode: Boolean(store.settings.privacy_blur_mode),
  bgm_autoplay: store.settings.bgm_autoplay !== false,
  gallery_particles: store.settings.gallery_particles !== false,
})

// 多源刮削配置（对应本地 DATA_DIR/settings.json，敏感字段脱敏管理）
const scraperLoading = ref(false)
const enabledSources = reactive<Record<string, boolean>>({
  ymgal: true,
  kungal: true,
  dlsite: true,
  vndb: true,
  bangumi: true,
  steam: true,
  touchgal: true,
  steamgriddb: true,
  igdb: true,
})
const scraperFields = reactive<Record<string, string>>({
  ymgal_client_id: '',
  ymgal_client_secret: '',
  kungal_base_url: 'https://www.kungal.com',
  kungal_token: '',
  bangumi_token: '',
  touchgal_api_key: '',
  steamgriddb_api_key: '',
  igdb_client_id: '',
  igdb_client_secret: '',
})
const maskedSecrets = reactive<Record<string, string>>({})
const configuredSecrets = reactive<Record<string, boolean>>({})
const clearedSecrets = reactive<Record<string, boolean>>({})

const expandedSourceId = ref<string | null>(store.settingsInitialExpandSource || null)
const revealedKeys = reactive<Record<string, boolean>>({})

// 单源连通性测试状态
const testingSource = reactive<Record<string, boolean>>({})
const testResults = reactive<Record<string, ScraperTestResponse | null>>({})

// Bangumi 账号验证状态
const verifyingBgm = ref(false)
const bgmVerifyResult = ref<BangumiMeResponse | null>(null)

function hydrateScraperSettings(cfg?: ScraperSettingsResponse | null) {
  if (!cfg) return
  if (cfg.enabled_sources) {
    for (const [k, v] of Object.entries(cfg.enabled_sources)) {
      enabledSources[k] = Boolean(v)
    }
  }
  scraperFields.ymgal_client_id = cfg.ymgal_client_id || ''
  scraperFields.kungal_base_url = cfg.kungal_base_url || 'https://www.kungal.com'
  scraperFields.igdb_client_id = cfg.igdb_client_id || ''

  const secValues: Record<string, string> = {
    ymgal_client_secret: cfg.ymgal_client_secret || '',
    kungal_token: cfg.kungal_token || '',
    bangumi_token: cfg.bangumi_token || '',
    touchgal_api_key: cfg.touchgal_api_key || '',
    steamgriddb_api_key: cfg.steamgriddb_api_key || '',
    igdb_client_secret: cfg.igdb_client_secret || '',
  }
  for (const k of Object.keys(secValues)) {
    maskedSecrets[k] = secValues[k]
    configuredSecrets[k] = Boolean(cfg.configured_secrets?.[k] ?? secValues[k])
    scraperFields[k] = ''
    clearedSecrets[k] = false
  }
}

hydrateScraperSettings(store.settings.scraper_settings)

async function loadScraperSettings() {
  scraperLoading.value = true
  try {
    const res = await systemApi.getScraperSettings()
    hydrateScraperSettings(res)
    store.settings = { ...store.settings, scraper_settings: res }
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '读取刮削源配置失败', 'warning')
  } finally {
    scraperLoading.value = false
  }
}

// 运行环境：版本与更新检查状态
const versionInfo = ref<AppVersionInfo | null>(null)
const checkingUpdate = ref(false)
const updateResult = ref<UpdateCheckResponse | null>(null)

// 运行环境存储治理与备份恢复状态
const storageLoading = ref(false)
const storageStats = ref<StorageUsageResponse | null>(null)
const cleaningStorage = ref(false)
const clearingThumbs = ref(false)
const convertingWebp = ref(false)

// 整库一键备份、恢复与自动快照回滚状态
const includeVideosInBackup = ref(false)
const exportingBackup = ref(false)
const restoringBackup = ref(false)
const snapshotsExpanded = ref(true)
const backupFileInputRef = ref<HTMLInputElement | null>(null)

interface PendingRestoreConfirmation {
  kind: 'zip-path' | 'zip-file' | 'snapshot'
  title: string
  targetLabel: string
  detail: string
  path?: string
  file?: File
  snapshotFilename?: string
}

const pendingRestoreConfirm = ref<PendingRestoreConfirmation | null>(null)

const sourceLinks = computed<Record<string, string | undefined>>(() => ({
  ...DEFAULT_SOURCE_LINKS,
  ...(store.settings.source_links || {}),
  ...(store.settings.scraper_settings?.source_links || {}),
}))

function getSourceDocUrl(src: ScraperSourceConfig): string {
  return sourceLinks.value[src.id] || src.docUrl || ''
}

function getFieldPlaceholder(field: ScraperFieldConfig): string {
  if (field.isSecret && configuredSecrets[field.key] && !clearedSecrets[field.key]) {
    return `已保存 (${maskedSecrets[field.key] || '••••••'})，输入新值替换`
  }
  return field.placeholder
}

function clearSecretField(fieldKey: string) {
  scraperFields[fieldKey] = ''
  clearedSecrets[fieldKey] = true
  configuredSecrets[fieldKey] = false
  maskedSecrets[fieldKey] = ''
}

async function handleVerifyBangumi() {
  if (verifyingBgm.value) return
  verifyingBgm.value = true
  bgmVerifyResult.value = null
  try {
    const token = (scraperFields.bangumi_token || '').trim()
    bgmVerifyResult.value = await scraperApi.verifyBangumiMe(token || undefined)
  } catch (err) {
    bgmVerifyResult.value = {
      valid: false,
      detail: err instanceof Error ? err.message : '验证请求失败',
    }
  } finally {
    verifyingBgm.value = false
  }
}

async function handleTestSource(src: ScraperSourceConfig) {
  if (testingSource[src.id]) return
  testingSource[src.id] = true
  testResults[src.id] = null
  try {
    const overrides: Record<string, string> = {}
    for (const f of src.fields || []) {
      const val = (scraperFields[f.key] || '').trim()
      if (val) {
        overrides[f.key] = val
      }
    }
    testResults[src.id] = await scraperApi.testSource(src.id, overrides)
  } catch (err) {
    testResults[src.id] = {
      ok: false,
      source: src.id,
      latency_ms: 0,
      detail: err instanceof Error ? err.message : '连通性测试失败',
    }
  } finally {
    testingSource[src.id] = false
  }
}

function formatBytes(bytes: number): string {
  const b = Math.max(0, Number(bytes) || 0)
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  if (b < 1024 * 1024 * 1024) return `${(b / (1024 * 1024)).toFixed(1)} MB`
  return `${(b / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

interface StorageSegment {
  key: 'database' | 'images' | 'videos' | 'audios' | 'thumbs' | 'backups' | 'orphans'
  label: string
  color: string
  bytes: number
  files: number
  percent: number
}

const storageSegments = computed<StorageSegment[]>(() => {
  const st = storageStats.value
  if (!st) return []
  const total = Math.max(st.total_bytes, 1)
  const defs: { key: StorageSegment['key']; label: string; color: string }[] = [
    { key: 'database', label: '数据库', color: '#a1a1aa' },
    { key: 'images', label: '封面与背景图', color: '#c49a5c' },
    { key: 'videos', label: '宣传片视频', color: '#6088b8' },
    { key: 'audios', label: '主题曲音频', color: '#4f9c88' },
    { key: 'thumbs', label: '缩略图缓存', color: '#8f7cc4' },
    { key: 'backups', label: '备份与快照', color: '#7b8794' },
    { key: 'orphans', label: '残留文件', color: '#b56565' },
  ]
  return defs.map((d) => {
    const bucket = st[d.key] || { bytes: 0, files: 0 }
    return {
      ...d,
      bytes: bucket.bytes || 0,
      files: bucket.files || 0,
      percent: st.total_bytes > 0 ? (bucket.bytes / total) * 100 : 0,
    }
  })
})

const thumbsCacheBytes = computed(() => {
  const st = storageStats.value
  if (!st) return 0
  return st.thumbs_bytes ?? st.thumbs?.bytes ?? 0
})

const localAvCacheBytes = computed(() => {
  const st = storageStats.value
  if (!st) return 0
  const v = st.videos_bytes ?? st.videos?.bytes ?? 0
  const a = st.audios_bytes ?? st.audios?.bytes ?? 0
  return v + a
})

const autoSnapshots = computed<AutoSnapshotItem[]>(() => storageStats.value?.snapshots || [])

const hasReleasableOrphans = computed(() => {
  const o = storageStats.value?.orphans
  return Boolean(o && (o.bytes > 0 || o.files > 0 || (o.dirs || 0) > 0))
})

function formatSnapshotTime(iso?: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function buildDefaultBackupName(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `Tsumugi-Backup-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}.zip`
}

function formatReleaseDate(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

async function loadVersionInfo() {
  try {
    versionInfo.value = await systemApi.version()
  } catch {
    // 忽略纯本地版本信息读取失败
  }
}

async function handleCheckUpdate() {
  if (checkingUpdate.value) return
  checkingUpdate.value = true
  try {
    updateResult.value = await systemApi.checkUpdate()
  } catch {
    updateResult.value = {
      status: 'error',
      current_version: versionInfo.value?.current_version || '0.9.0',
      message: '无法连接 GitHub，请检查网络或代理设置',
    }
  } finally {
    checkingUpdate.value = false
  }
}

async function loadStorageStats() {
  storageLoading.value = true
  try {
    storageStats.value = await systemApi.storage()
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '读取存储信息失败', 'warning')
  } finally {
    storageLoading.value = false
  }
}

async function handleCleanupOrphans() {
  if (cleaningStorage.value || !hasReleasableOrphans.value) return
  cleaningStorage.value = true
  try {
    const res = await systemApi.cleanupStorage()
    store.notify(
      res.freed_bytes > 0 || res.deleted_dirs > 0
        ? `已清理 ${res.deleted_files} 个残留文件，释放 ${formatBytes(res.freed_bytes)}`
        : '当前没有可清理的残留文件',
      'success',
    )
    await loadStorageStats()
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '清理失败', 'error')
  } finally {
    cleaningStorage.value = false
  }
}

async function handleClearThumbs() {
  if (clearingThumbs.value) return
  clearingThumbs.value = true
  try {
    const res = await systemApi.clearThumbs()
    store.notify(
      res.deleted_files > 0
        ? `已清理 ${res.deleted_files} 个缩略图缓存，释放 ${formatBytes(res.freed_bytes)}`
        : '当前缩略图缓存为空',
      res.deleted_files > 0 ? 'success' : 'info',
    )
    store.bumpAssetVersion()
    await loadStorageStats()
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '清理缩略图缓存失败', 'error')
  } finally {
    clearingThumbs.value = false
  }
}

async function handleExportLibraryBackup() {
  if (exportingBackup.value) return
  exportingBackup.value = true
  try {
    if (hasDesktopBridge) {
      const targetPath = await pickBackupSavePath(buildDefaultBackupName())
      if (targetPath !== null) {
        if (!targetPath) return
        const res = await systemApi.exportBackupToPath(includeVideosInBackup.value, targetPath)
        store.notify(
          `整库备份已导出：${res.filename}（${formatBytes(res.size_bytes)}）`,
          'success',
        )
        return
      }
    }
    const dl = await systemApi.downloadBackupZip(includeVideosInBackup.value)
    store.notify(`整库备份已导出：${dl.filename}（${formatBytes(dl.size_bytes)}）`, 'success')
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '导出整库备份失败', 'error')
  } finally {
    exportingBackup.value = false
  }
}

async function handleChooseRestoreBackup() {
  if (restoringBackup.value) return
  if (hasDesktopBridge) {
    const selected = await pickBackupOpenPath()
    if (selected !== null) {
      if (!selected) return
      const displayName = selected.split(/[\\/]/).pop() || selected
      pendingRestoreConfirm.value = {
        kind: 'zip-path',
        title: '确认从整库备份恢复？',
        targetLabel: displayName,
        detail: '恢复前会自动为当前游戏库留存安全快照，恢复后将刷新界面并重新加载数据。',
        path: selected,
      }
      return
    }
  }
  backupFileInputRef.value?.click()
}

function onBackupFileSelected(e: Event) {
  const input = e.target as HTMLInputElement | null
  const file = input?.files?.[0]
  if (input) input.value = ''
  if (!file) return
  pendingRestoreConfirm.value = {
    kind: 'zip-file',
    title: '确认从整库备份恢复？',
    targetLabel: file.name,
    detail: '恢复前会自动为当前游戏库留存安全快照，恢复后将刷新界面并重新加载数据。',
    file,
  }
}

function requestSnapshotRollback(snap: AutoSnapshotItem) {
  if (restoringBackup.value) return
  pendingRestoreConfirm.value = {
    kind: 'snapshot',
    title: '确认回滚到此数据库快照？',
    targetLabel: `${snap.filename}（${formatSnapshotTime(snap.created_at)}）`,
    detail: '回滚前会自动为当前游戏库留存安全快照，回滚完成后将立即刷新界面数据。',
    snapshotFilename: snap.filename,
  }
}

async function confirmPendingRestore() {
  const pending = pendingRestoreConfirm.value
  if (!pending || restoringBackup.value) return
  restoringBackup.value = true
  try {
    if (pending.kind === 'zip-path' && pending.path) {
      const res = await systemApi.restoreBackupFromPath(pending.path)
      store.notify(
        res.safety_snapshot
          ? `整库已恢复（已自动留存快照 ${res.safety_snapshot}）`
          : '整库已恢复完成',
        'success',
      )
    } else if (pending.kind === 'zip-file' && pending.file) {
      const res = await systemApi.restoreBackupFromFile(pending.file)
      store.notify(
        res.safety_snapshot
          ? `整库已恢复（已自动留存快照 ${res.safety_snapshot}）`
          : '整库已恢复完成',
        'success',
      )
    } else if (pending.kind === 'snapshot' && pending.snapshotFilename) {
      const res = await systemApi.restoreSnapshot(pending.snapshotFilename)
      store.notify(
        res.safety_snapshot
          ? `已回滚至 ${res.filename}（已留存当前快照 ${res.safety_snapshot}）`
          : `已回滚至 ${res.filename}`,
        'success',
      )
    }

    pendingRestoreConfirm.value = null
    await store.initialize()
    store.bumpAssetVersion()
    await loadStorageStats()
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '恢复失败，原数据未受影响', 'error')
  } finally {
    restoringBackup.value = false
  }
}

async function handleConvertWebp() {
  if (convertingWebp.value) return
  convertingWebp.value = true
  try {
    const res = await systemApi.convertWebp()
    if (res.converted_count > 0) {
      store.notify(
        `已转换 ${res.converted_count} 张图片，节省 ${formatBytes(res.saved_bytes)}`,
        'success',
      )
      await store.refreshGames()
      store.bumpAssetVersion()
    } else {
      store.notify('所有图片资产均已为 WebP 格式', 'info')
    }
    await loadStorageStats()
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '批量转换 WebP 失败', 'error')
  } finally {
    convertingWebp.value = false
  }
}

watch(
  activeSection,
  (sec) => {
    if (sec === 'sources') {
      void loadScraperSettings()
    } else if (sec === 'data') {
      void loadStorageStats()
    } else if (sec === 'environment') {
      if (!versionInfo.value) {
        void loadVersionInfo()
      }
    }
  },
  { immediate: true },
)

onMounted(() => {
  store.settingsInitialSection = 'general'
  store.settingsInitialExpandSource = null
})

function hasExpandableFields(src: ScraperSourceConfig): boolean {
  return Boolean(src.fields && src.fields.length > 0)
}

function toggleSourceAccordion(src: ScraperSourceConfig) {
  if (!hasExpandableFields(src)) return
  expandedSourceId.value = expandedSourceId.value === src.id ? null : src.id
}

function toggleKeyVisibility(field: string) {
  revealedKeys[field] = !revealedKeys[field]
}

function isSourceKeyReady(src: ScraperSourceConfig): boolean {
  if (src.id === 'touchgal') {
    return Boolean(
      (scraperFields.touchgal_api_key || '').trim() ||
        (configuredSecrets.touchgal_api_key && !clearedSecrets.touchgal_api_key),
    )
  }
  if (src.id === 'steamgriddb') {
    return Boolean(
      (scraperFields.steamgriddb_api_key || '').trim() ||
        (configuredSecrets.steamgriddb_api_key && !clearedSecrets.steamgriddb_api_key),
    )
  }
  if (src.id === 'igdb') {
    const hasId = Boolean((scraperFields.igdb_client_id || '').trim())
    const hasSec = Boolean(
      (scraperFields.igdb_client_secret || '').trim() ||
        (configuredSecrets.igdb_client_secret && !clearedSecrets.igdb_client_secret),
    )
    return hasId && hasSec
  }
  if (src.id === 'bangumi') {
    return Boolean(
      (scraperFields.bangumi_token || '').trim() ||
        (configuredSecrets.bangumi_token && !clearedSecrets.bangumi_token),
    )
  }
  if (src.id === 'ymgal') {
    const hasId = Boolean((scraperFields.ymgal_client_id || '').trim())
    const hasSec = Boolean(
      (scraperFields.ymgal_client_secret || '').trim() ||
        (configuredSecrets.ymgal_client_secret && !clearedSecrets.ymgal_client_secret),
    )
    return hasId && hasSec
  }
  if (src.id === 'kungal') {
    return Boolean(
      (scraperFields.kungal_token || '').trim() ||
        (configuredSecrets.kungal_token && !clearedSecrets.kungal_token),
    )
  }
  return false
}

function getSourceStatus(src: ScraperSourceConfig): {
  label: string
  tone: 'free' | 'ok' | 'missing' | 'optional'
} {
  if (!enabledSources[src.id]) {
    return { label: '已停用', tone: 'optional' }
  }
  if (src.group === 'key') {
    return isSourceKeyReady(src)
      ? { label: '已配置', tone: 'ok' }
      : { label: '未配置 Key', tone: 'missing' }
  }
  if (src.authType === 'optional' && isSourceKeyReady(src)) {
    return { label: '已配凭证', tone: 'ok' }
  }
  return { label: '默认可用', tone: 'free' }
}

async function browseLE() {
  const picked = await pickNativeFile('选择 Locale Emulator (LEProc.exe)', [
    'LEProc (*.exe)',
    'All files (*.*)',
  ])
  if (picked) form.le_exe_path = picked
}

async function saveAll() {
  saving.value = true
  try {
    const clearFields = Object.entries(clearedSecrets)
      .filter(([, cleared]) => cleared)
      .map(([k]) => k)

    const scraperPayload: Record<string, unknown> = {
      enabled_sources: { ...enabledSources },
      ymgal_client_id: (scraperFields.ymgal_client_id || '').trim(),
      kungal_base_url: (scraperFields.kungal_base_url || '').trim() || 'https://www.kungal.com',
      igdb_client_id: (scraperFields.igdb_client_id || '').trim(),
      clear_fields: clearFields,
    }
    for (const secKey of SECRET_KEYS) {
      const typed = (scraperFields[secKey] || '').trim()
      if (typed) {
        scraperPayload[secKey] = typed
      }
    }

    const [, , , , , , savedScraper] = await Promise.all([
      store.updateSetting('proxy_url', form.proxy_url.trim()),
      store.updateSetting('le_exe_path', form.le_exe_path.trim()),
      store.updateSetting('allow_nsfw_scrape', form.allow_nsfw_scrape),
      store.updateSetting('privacy_blur_mode', form.privacy_blur_mode),
      store.updateSetting('bgm_autoplay', form.bgm_autoplay),
      store.updateSetting('gallery_particles', form.gallery_particles),
      systemApi.updateScraperSettings(scraperPayload),
    ])

    hydrateScraperSettings(savedScraper)
    store.settings = {
      ...store.settings,
      scraper_settings: savedScraper,
      bangumi_token: savedScraper.bangumi_token,
      api_keys: {
        ...(store.settings.api_keys || { steamgriddb: '', touchgal: '', bangumi: '' }),
        touchgal: savedScraper.touchgal_api_key,
        steamgriddb: savedScraper.steamgriddb_api_key,
        bangumi: savedScraper.bangumi_token,
      },
    }

    store.notify('设置已保存（刮削源配置已持久化至 settings.json）', 'success')
    store.showSettingsModal = false
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '保存设置失败', 'error')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="modal-backdrop" @click.self="store.showSettingsModal = false">
    <div class="modal-card settings-window">
      <div class="settings-layout">
        <!-- 左侧固定 180px 分类导航 -->
        <aside class="settings-nav">
          <div class="nav-title">设置</div>

          <nav class="nav-items" aria-label="设置分类">
            <button
              v-for="item in navSections"
              :key="item.id"
              type="button"
              class="settings-nav-item"
              :class="{ active: activeSection === item.id }"
              @click="activeSection = item.id"
            >
              <svg
                v-if="item.id === 'general'"
                viewBox="0 0 20 20"
                width="15"
                height="15"
                fill="none"
                stroke="currentColor"
                stroke-width="1.65"
              >
                <path d="M10 3l6 2.5v4.6c0 3.7-2.6 6.4-6 7.4-3.4-1-6-3.7-6-7.4V5.5L10 3z" />
              </svg>
              <svg
                v-else-if="item.id === 'network'"
                viewBox="0 0 20 20"
                width="15"
                height="15"
                fill="none"
                stroke="currentColor"
                stroke-width="1.65"
              >
                <circle cx="10" cy="10" r="7" />
                <path d="M3.5 10h13M10 3a11 11 0 0 1 0 14M10 3a11 11 0 0 0 0 14" />
              </svg>
              <svg
                v-else-if="item.id === 'sources'"
                viewBox="0 0 20 20"
                width="15"
                height="15"
                fill="none"
                stroke="currentColor"
                stroke-width="1.65"
              >
                <ellipse cx="10" cy="5.5" rx="6" ry="2.5" />
                <path d="M4 5.5v9c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-9" />
                <path d="M4 10c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5" />
              </svg>
              <svg
                v-else-if="item.id === 'data'"
                viewBox="0 0 20 20"
                width="15"
                height="15"
                fill="none"
                stroke="currentColor"
                stroke-width="1.65"
              >
                <path d="M4 7.5V5.5A1.5 1.5 0 0 1 5.5 4h9A1.5 1.5 0 0 1 16 5.5v9a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 4 14.5v-2" />
                <path d="M3 10h8.5M8.5 7.5L11.5 10l-3 2.5" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
              <svg
                v-else
                viewBox="0 0 20 20"
                width="15"
                height="15"
                fill="none"
                stroke="currentColor"
                stroke-width="1.65"
              >
                <rect x="3" y="4" width="14" height="10" rx="2" />
                <path d="M7.5 17h5M10 14v3" />
              </svg>
              <span>{{ item.label }}</span>
            </button>
          </nav>
        </aside>

        <!-- 右侧内容区 -->
        <div class="settings-right">
          <div class="pane-topbar">
            <h2>{{ navSections.find((n) => n.id === activeSection)?.label }}</h2>
            <button
              type="button"
              class="close-icon-btn"
              aria-label="关闭设置"
              @click="store.showSettingsModal = false"
            >
              <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8">
                <path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" />
              </svg>
            </button>
          </div>

          <div class="pane-scroll">
            <!-- 1. 常规与隐私：原生分组列表 -->
            <div v-if="activeSection === 'general'" class="pane-section">
              <div class="group-block">
                <div class="group-label">体验</div>
                <div class="grouped-card">
                  <label class="group-row toggle-row">
                    <div class="toggle-text">
                      <div class="row-title">背景光尘</div>
                      <div class="row-desc">在回廊背景中显示微弱飘动的光点</div>
                    </div>
                    <input v-model="form.gallery_particles" type="checkbox" class="native-switch" />
                  </label>

                  <label class="group-row toggle-row">
                    <div class="toggle-text">
                      <div class="row-title">自动播放主题曲</div>
                      <div class="row-desc">选中已绑定音频的作品时自动播放</div>
                    </div>
                    <input v-model="form.bgm_autoplay" type="checkbox" class="native-switch" />
                  </label>
                </div>
              </div>

              <div class="group-block">
                <div class="group-label">内容与隐私</div>
                <div class="grouped-card">
                  <label class="group-row toggle-row">
                    <div class="toggle-text">
                      <div class="row-title">包含成人向内容</div>
                      <div class="row-desc">搜索和导入资料时显示 R18 作品与图片</div>
                    </div>
                    <input v-model="form.allow_nsfw_scrape" type="checkbox" class="native-switch" />
                  </label>

                  <label class="group-row toggle-row">
                    <div class="toggle-text">
                      <div class="row-title">隐私模式</div>
                      <div class="row-desc">对成人向作品的封面、背景与截图进行模糊遮挡</div>
                    </div>
                    <input v-model="form.privacy_blur_mode" type="checkbox" class="native-switch" />
                  </label>
                </div>
              </div>
            </div>

            <!-- 2. 网络与启动：原生分组列表 -->
            <div v-else-if="activeSection === 'network'" class="pane-section">
              <div class="grouped-card">
                <div class="group-row field-row">
                  <label class="row-title">代理地址</label>
                  <input
                    v-model="form.proxy_url"
                    class="input"
                    placeholder="http://127.0.0.1:7890（留空直连）"
                  />
                  <span class="row-desc">HTTP / SOCKS 代理，用于联网搜索资料与下载图片</span>
                </div>

                <div class="group-row field-row">
                  <label class="row-title">Locale Emulator 路径</label>
                  <div class="row-with-btn">
                    <input
                      v-model="form.le_exe_path"
                      class="input"
                      placeholder="D:\Tools\Locale.Emulator\LEProc.exe"
                    />
                    <button v-if="hasDesktopBridge" type="button" class="btn btn-sm" @click="browseLE">
                      浏览…
                    </button>
                  </div>
                  <span class="row-desc">Windows 环境下使用转区启动时需要指向 LEProc.exe</span>
                </div>
              </div>
            </div>

            <!-- 3. 元数据刮削源：内置数据源 + 可选扩展源 -->
            <div v-else-if="activeSection === 'sources'" class="pane-section">
              <div class="group-block">
                <div class="group-label">内置数据源（免 Key）</div>
                <div class="grouped-card">
                  <div
                    v-for="src in FREE_SCRAPER_SOURCES"
                    :key="src.id"
                    class="group-row source-item"
                    :class="{
                      expandable: hasExpandableFields(src),
                      expanded: expandedSourceId === src.id,
                    }"
                  >
                    <div class="source-row-wrap">
                      <button
                        type="button"
                        class="source-row"
                        :disabled="!hasExpandableFields(src)"
                        @click="toggleSourceAccordion(src)"
                      >
                        <div class="source-meta">
                          <span class="row-title">{{ src.name }}</span>
                          <span class="row-desc">{{ src.description }}</span>
                        </div>
                      </button>

                      <div class="source-right">
                        <span class="status-capsule" :class="`tone-${getSourceStatus(src).tone}`">
                          {{ getSourceStatus(src).label }}
                        </span>

                        <button
                          type="button"
                          class="btn btn-sm source-test-btn"
                          :disabled="testingSource[src.id]"
                          @click.stop="handleTestSource(src)"
                        >
                          {{ testingSource[src.id] ? '测试中…' : '测试' }}
                        </button>

                        <input
                          v-model="enabledSources[src.id]"
                          type="checkbox"
                          class="native-switch"
                          :title="`启用或停用 ${src.name}`"
                          @click.stop
                        />

                        <button
                          v-if="hasExpandableFields(src)"
                          type="button"
                          class="accordion-btn"
                          :aria-label="`展开 ${src.name} 高级配置`"
                          @click.stop="toggleSourceAccordion(src)"
                        >
                          <svg
                            class="accordion-chevron"
                            :class="{ open: expandedSourceId === src.id }"
                            viewBox="0 0 16 16"
                            width="14"
                            height="14"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="1.7"
                          >
                            <path d="M4.5 6.25L8 9.75l3.5-3.5" stroke-linecap="round" stroke-linejoin="round" />
                          </svg>
                        </button>
                      </div>
                    </div>

                    <!-- 连通性测试即时反馈 -->
                    <div
                      v-if="testResults[src.id]"
                      class="source-test-feedback"
                      :class="testResults[src.id]?.ok ? 'ok' : 'err'"
                    >
                      <span>{{ testResults[src.id]?.detail }}</span>
                      <span v-if="testResults[src.id]?.latency_ms" class="tabular-nums">
                        · {{ testResults[src.id]?.latency_ms }}ms
                      </span>
                    </div>

                    <!-- 可选高级配置展开区 -->
                    <div v-if="hasExpandableFields(src) && expandedSourceId === src.id" class="source-body">
                      <div v-for="field in src.fields" :key="field.key" class="source-field-block">
                        <div class="source-field-head">
                          <label class="source-field-label">{{ field.label }}</label>
                          <button
                            v-if="field.isSecret && configuredSecrets[field.key] && !clearedSecrets[field.key]"
                            type="button"
                            class="clear-secret-btn"
                            @click="clearSecretField(field.key)"
                          >
                            清除已存密钥
                          </button>
                        </div>

                        <div class="source-input-row">
                          <div class="secret-input-wrap">
                            <input
                              v-model="scraperFields[field.key]"
                              class="input"
                              :class="{ 'secret-input': field.isSecret }"
                              :type="field.isSecret && !revealedKeys[field.key] ? 'password' : 'text'"
                              autocomplete="off"
                              :placeholder="getFieldPlaceholder(field)"
                              @input="
                                clearedSecrets[field.key] = false;
                                src.id === 'bangumi' && (bgmVerifyResult = null)
                              "
                            />
                            <button
                              v-if="field.isSecret"
                              type="button"
                              class="eye-btn"
                              :title="revealedKeys[field.key] ? '隐藏' : '显示'"
                              @click="toggleKeyVisibility(field.key)"
                            >
                              <svg
                                v-if="revealedKeys[field.key]"
                                viewBox="0 0 24 24"
                                width="15"
                                height="15"
                                fill="none"
                                stroke="currentColor"
                                stroke-width="1.8"
                              >
                                <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24M1 1l22 22" />
                              </svg>
                              <svg
                                v-else
                                viewBox="0 0 24 24"
                                width="15"
                                height="15"
                                fill="none"
                                stroke="currentColor"
                                stroke-width="1.8"
                              >
                                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                                <circle cx="12" cy="12" r="3" />
                              </svg>
                            </button>
                          </div>

                          <button
                            v-if="src.id === 'bangumi' && field.key === 'bangumi_token'"
                            type="button"
                            class="btn btn-sm verify-btn"
                            :disabled="verifyingBgm"
                            @click="handleVerifyBangumi"
                          >
                            {{ verifyingBgm ? '验证中…' : '验证账号' }}
                          </button>
                        </div>
                      </div>

                      <div
                        v-if="src.id === 'bangumi' && bgmVerifyResult"
                        class="verify-feedback"
                        :class="bgmVerifyResult.valid ? 'ok' : 'err'"
                      >
                        <template v-if="bgmVerifyResult.valid">
                          已验证账号：{{ bgmVerifyResult.nickname || bgmVerifyResult.username }}
                        </template>
                        <template v-else>
                          {{ bgmVerifyResult.detail || 'Access Token 无效或已过期' }}
                        </template>
                      </div>

                      <div class="source-hint-row">
                        <span v-if="src.docHint" class="source-hint">{{ src.docHint }}</span>
                        <a
                          v-if="getSourceDocUrl(src)"
                          :href="getSourceDocUrl(src)"
                          target="_blank"
                          rel="noopener noreferrer"
                          class="source-ext-link"
                        >
                          {{ src.docLinkLabel || '查看文档 ↗' }}
                        </a>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="group-block">
                <div class="group-label">可选扩展源（填写 Key 后可用，仅存于本地 data/settings.json）</div>
                <div class="grouped-card">
                  <div
                    v-for="src in KEY_SCRAPER_SOURCES"
                    :key="src.id"
                    class="group-row source-item expandable"
                    :class="{ expanded: expandedSourceId === src.id }"
                  >
                    <div class="source-row-wrap">
                      <button
                        type="button"
                        class="source-row"
                        @click="toggleSourceAccordion(src)"
                      >
                        <div class="source-meta">
                          <span class="row-title">{{ src.name }}</span>
                          <span class="row-desc">{{ src.description }}</span>
                        </div>
                      </button>

                      <div class="source-right">
                        <span class="status-capsule" :class="`tone-${getSourceStatus(src).tone}`">
                          {{ getSourceStatus(src).label }}
                        </span>

                        <button
                          type="button"
                          class="btn btn-sm source-test-btn"
                          :disabled="testingSource[src.id]"
                          @click.stop="handleTestSource(src)"
                        >
                          {{ testingSource[src.id] ? '测试中…' : '测试' }}
                        </button>

                        <input
                          v-model="enabledSources[src.id]"
                          type="checkbox"
                          class="native-switch"
                          :title="`启用或停用 ${src.name}`"
                          @click.stop
                        />

                        <button
                          type="button"
                          class="accordion-btn"
                          :aria-label="`展开 ${src.name} 密钥配置`"
                          @click.stop="toggleSourceAccordion(src)"
                        >
                          <svg
                            class="accordion-chevron"
                            :class="{ open: expandedSourceId === src.id }"
                            viewBox="0 0 16 16"
                            width="14"
                            height="14"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="1.7"
                          >
                            <path d="M4.5 6.25L8 9.75l3.5-3.5" stroke-linecap="round" stroke-linejoin="round" />
                          </svg>
                        </button>
                      </div>
                    </div>

                    <div
                      v-if="testResults[src.id]"
                      class="source-test-feedback"
                      :class="testResults[src.id]?.ok ? 'ok' : 'err'"
                    >
                      <span>{{ testResults[src.id]?.detail }}</span>
                      <span v-if="testResults[src.id]?.latency_ms" class="tabular-nums">
                        · {{ testResults[src.id]?.latency_ms }}ms
                      </span>
                    </div>

                    <div v-if="expandedSourceId === src.id" class="source-body">
                      <div v-for="field in src.fields" :key="field.key" class="source-field-block">
                        <div class="source-field-head">
                          <label class="source-field-label">{{ field.label }}</label>
                          <button
                            v-if="field.isSecret && configuredSecrets[field.key] && !clearedSecrets[field.key]"
                            type="button"
                            class="clear-secret-btn"
                            @click="clearSecretField(field.key)"
                          >
                            清除已存密钥
                          </button>
                        </div>

                        <div class="secret-input-wrap">
                          <input
                            v-model="scraperFields[field.key]"
                            class="input"
                            :class="{ 'secret-input': field.isSecret }"
                            :type="field.isSecret && !revealedKeys[field.key] ? 'password' : 'text'"
                            autocomplete="off"
                            :placeholder="getFieldPlaceholder(field)"
                            @input="clearedSecrets[field.key] = false"
                          />
                          <button
                            v-if="field.isSecret"
                            type="button"
                            class="eye-btn"
                            :title="revealedKeys[field.key] ? '隐藏' : '显示'"
                            @click="toggleKeyVisibility(field.key)"
                          >
                            <svg
                              v-if="revealedKeys[field.key]"
                              viewBox="0 0 24 24"
                              width="15"
                              height="15"
                              fill="none"
                              stroke="currentColor"
                              stroke-width="1.8"
                            >
                              <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24M1 1l22 22" />
                            </svg>
                            <svg
                              v-else
                              viewBox="0 0 24 24"
                              width="15"
                              height="15"
                              fill="none"
                              stroke="currentColor"
                              stroke-width="1.8"
                            >
                              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                              <circle cx="12" cy="12" r="3" />
                            </svg>
                          </button>
                        </div>
                      </div>

                      <div class="source-hint-row">
                        <span v-if="src.docHint" class="source-hint">{{ src.docHint }}</span>
                        <a
                          v-if="getSourceDocUrl(src)"
                          :href="getSourceDocUrl(src)"
                          target="_blank"
                          rel="noopener noreferrer"
                          class="source-ext-link"
                        >
                          {{ src.docLinkLabel || '获取 API Key ↗' }}
                        </a>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 4. 数据管理与数据迁移 -->
            <div v-else-if="activeSection === 'data'" class="pane-section">
              <div class="group-block">
                <div class="group-label">数据迁移</div>
                <div class="grouped-card">
                  <div class="group-row action-row">
                    <div class="toggle-text">
                      <div class="row-title">导入外部游戏库（Playnite / Vnite）</div>
                      <div class="row-desc">从 Playnite 或 Vnite 迁移游戏、游玩时长与封面</div>
                    </div>
                    <button
                      type="button"
                      class="btn btn-sm"
                      @click="store.openExternalImport('playnite')"
                    >
                      导入外部库
                    </button>
                  </div>
                </div>
              </div>

              <div class="group-block">
                <div class="group-label">存储空间</div>
                <div class="grouped-card">
                  <div class="group-row storage-overview-row">
                    <div class="storage-top-line">
                      <span class="row-title">本地数据占用</span>
                      <span class="storage-total tabular-nums">
                        {{ storageStats ? formatBytes(storageStats.total_bytes) : (storageLoading ? '计算中…' : '—') }}
                      </span>
                    </div>

                    <!-- macOS 风格横向分类占用条 -->
                    <div class="storage-bar" role="img" aria-label="存储分类占用分布">
                      <template v-if="storageStats && storageStats.total_bytes > 0">
                        <div
                          v-for="seg in storageSegments"
                          v-show="seg.bytes > 0"
                          :key="seg.key"
                          class="storage-seg"
                          :style="{
                            width: `${Math.max(seg.percent, 1.2)}%`,
                            backgroundColor: seg.color,
                          }"
                          :title="`${seg.label}：${formatBytes(seg.bytes)}`"
                        />
                      </template>
                    </div>

                    <!-- 双列图例明细 -->
                    <div v-if="storageStats" class="storage-legend">
                      <div v-for="seg in storageSegments" :key="seg.key" class="legend-item">
                        <span class="legend-left">
                          <span class="legend-dot" :style="{ backgroundColor: seg.color }" />
                          <span class="legend-name">{{ seg.label }}</span>
                        </span>
                        <span class="legend-val tabular-nums">{{ formatBytes(seg.bytes) }}</span>
                      </div>
                    </div>
                  </div>

                  <!-- 维护操作 0：清理缩略图缓存 -->
                  <div class="group-row action-row">
                    <div class="toggle-text">
                      <div class="row-title">缩略图缓存</div>
                      <div class="row-desc tabular-nums">
                        {{
                          storageStats
                            ? `当前占用 ${formatBytes(thumbsCacheBytes)}，清理后按需重建`
                            : 'WebP 缩略图缓存，清理后按需重建'
                        }}
                      </div>
                    </div>
                    <button
                      type="button"
                      class="btn btn-sm"
                      :disabled="clearingThumbs || (Boolean(storageStats) && thumbsCacheBytes === 0)"
                      @click="handleClearThumbs"
                    >
                      {{ clearingThumbs ? '清理中…' : '清理缓存' }}
                    </button>
                  </div>

                  <!-- 维护操作 1：清理残留文件 -->
                  <div class="group-row action-row">
                    <div class="toggle-text">
                      <div class="row-title">清理残留文件</div>
                      <div class="row-desc tabular-nums">
                        {{
                          storageStats
                            ? hasReleasableOrphans
                              ? `可释放 ${formatBytes(storageStats.orphans.bytes)}`
                              : '当前无可清理残留（0 B）'
                            : '扫描孤儿目录与未完成下载临时文件'
                        }}
                      </div>
                    </div>
                    <button
                      type="button"
                      class="btn btn-sm"
                      :disabled="cleaningStorage || !hasReleasableOrphans"
                      @click="handleCleanupOrphans"
                    >
                      {{ cleaningStorage ? '清理中…' : '清理' }}
                    </button>
                  </div>

                  <!-- 维护操作 2：旧图转为 WebP -->
                  <div class="group-row action-row">
                    <div class="toggle-text">
                      <div class="row-title">旧图转为 WebP</div>
                      <div class="row-desc">将存量 PNG / JPG 资产压缩为 WebP 并补齐封面缩略图</div>
                    </div>
                    <button
                      type="button"
                      class="btn btn-sm"
                      :disabled="convertingWebp"
                      @click="handleConvertWebp"
                    >
                      {{ convertingWebp ? '转换中…' : '开始转换' }}
                    </button>
                  </div>
                </div>
              </div>

              <!-- 整库一键备份与恢复 -->
              <div class="group-block">
                <div class="group-label">整库备份与恢复</div>
                <div class="grouped-card">
                  <label class="group-row backup-check-row">
                    <div class="backup-check-left">
                      <input
                        v-model="includeVideosInBackup"
                        type="checkbox"
                        class="backup-checkbox"
                      />
                      <div class="toggle-text">
                        <div class="row-title">同时包含本地 PV/OP 影音缓存</div>
                        <div class="row-desc tabular-nums">
                          默认仅含数据库、配置与图片（当前影音缓存 {{ formatBytes(localAvCacheBytes) }}）
                        </div>
                      </div>
                    </div>
                  </label>

                  <div class="group-row backup-actions-row">
                    <button
                      type="button"
                      class="btn btn-sm btn-primary"
                      :disabled="exportingBackup || restoringBackup"
                      @click="handleExportLibraryBackup"
                    >
                      {{ exportingBackup ? '导出中…' : '导出备份' }}
                    </button>
                    <button
                      type="button"
                      class="btn btn-sm"
                      :disabled="exportingBackup || restoringBackup"
                      @click="handleChooseRestoreBackup"
                    >
                      {{ restoringBackup ? '恢复中…' : '恢复备份' }}
                    </button>
                    <input
                      ref="backupFileInputRef"
                      type="file"
                      accept=".zip,application/zip"
                      class="sr-only-input"
                      @change="onBackupFileSelected"
                    />
                  </div>
                </div>
              </div>

              <!-- 自动数据库快照回滚 -->
              <div class="group-block">
                <div class="group-label-row">
                  <span class="group-label">自动数据库快照</span>
                  <button
                    type="button"
                    class="snap-collapse-btn tabular-nums"
                    @click="snapshotsExpanded = !snapshotsExpanded"
                  >
                    <span>{{ autoSnapshots.length }} 份</span>
                    <svg
                      class="snap-chevron"
                      :class="{ open: snapshotsExpanded }"
                      viewBox="0 0 16 16"
                      width="12"
                      height="12"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="1.8"
                    >
                      <path d="M4.5 6.5 8 10l3.5-3.5" stroke-linecap="round" stroke-linejoin="round" />
                    </svg>
                  </button>
                </div>

                <div v-if="snapshotsExpanded" class="grouped-card">
                  <div v-if="autoSnapshots.length === 0" class="group-row snap-empty-row">
                    <span class="row-desc">暂无自动快照，启动及恢复前会自动生成</span>
                  </div>
                  <div
                    v-for="snap in autoSnapshots"
                    :key="snap.filename"
                    class="group-row snap-item-row"
                  >
                    <div class="snap-meta">
                      <div class="snap-top-line">
                        <span class="snap-time tabular-nums">{{ formatSnapshotTime(snap.created_at) }}</span>
                        <span class="snap-tag" :class="`tag-${snap.tag}`">{{ snap.tag_label }}</span>
                      </div>
                      <div class="snap-sub tabular-nums">
                        <span class="snap-filename" :title="snap.filename">{{ snap.filename }}</span>
                        <span class="snap-size">{{ formatBytes(snap.size_bytes) }}</span>
                      </div>
                    </div>
                    <button
                      type="button"
                      class="btn btn-sm"
                      :disabled="restoringBackup"
                      @click="requestSnapshotRollback(snap)"
                    >
                      回滚
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <!-- 5. 运行环境 -->
            <div v-else class="pane-section">
              <div class="group-block">
                <div class="group-label">版本与更新</div>
                <div class="grouped-card">
                  <div class="group-row update-main-row">
                    <div class="update-meta">
                      <div class="update-title-line">
                        <span class="row-title">Tsumugi</span>
                        <span class="version-pill tabular-nums">
                          v{{ versionInfo?.current_version || '0.9.0' }}
                        </span>
                      </div>
                      <div
                        class="row-desc update-status-line"
                        :class="updateResult ? `status-${updateResult.status}` : ''"
                      >
                        <template v-if="updateResult">
                          {{ updateResult.message }}
                        </template>
                        <template v-else>
                          {{ versionInfo?.github_repo || '点击右侧按钮检查最新发行版' }}
                        </template>
                      </div>
                    </div>

                    <div class="update-actions">
                      <a
                        v-if="versionInfo?.repo_url"
                        :href="versionInfo.repo_url"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="github-ext-btn"
                        title="访问 GitHub 仓库"
                      >
                        <span>GitHub ↗</span>
                      </a>
                      <button
                        type="button"
                        class="btn btn-sm"
                        :disabled="checkingUpdate"
                        @click="handleCheckUpdate"
                      >
                        {{ checkingUpdate ? '检查中...' : '检查更新' }}
                      </button>
                    </div>
                  </div>

                  <!-- 发现新版本时原地平滑展开 -->
                  <div
                    v-if="updateResult && updateResult.status === 'update_available'"
                    class="group-row update-expand-row"
                  >
                    <div class="release-head">
                      <span class="release-ver tabular-nums">
                        v{{ updateResult.latest_version }}
                      </span>
                      <span v-if="updateResult.published_at" class="release-date tabular-nums">
                        {{ formatReleaseDate(updateResult.published_at) }}
                      </span>
                    </div>

                    <div class="release-notes">
                      {{ updateResult.release_notes || '暂无更新说明' }}
                    </div>

                    <div class="release-actions">
                      <a
                        v-if="updateResult.release_url"
                        :href="updateResult.release_url"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="release-primary-btn"
                      >
                        前往下载 ↗
                      </a>
                      <a
                        v-if="updateResult.download_url"
                        :href="updateResult.download_url"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="btn btn-sm btn-ghost release-dl-btn"
                      >
                        直接下载安装包
                      </a>
                    </div>
                  </div>
                </div>
              </div>

              <div class="group-block">
                <div class="group-label">系统信息</div>
                <div class="grouped-card">
                  <div class="group-row env-row">
                    <span class="env-label">版本</span>
                    <code class="env-val tabular-nums">
                      Tsumugi {{ versionInfo?.current_version || '0.9.0' }}
                    </code>
                  </div>
                  <div class="group-row env-row">
                    <span class="env-label">前端环境</span>
                    <code class="env-val">{{ hasDesktopBridge ? 'Desktop WebView' : 'Web Browser' }}</code>
                  </div>
                  <div class="group-row env-row">
                    <span class="env-label">系统适配</span>
                    <code class="env-val">{{ store.health?.os_adapter || '—' }}</code>
                  </div>
                  <div class="group-row env-row">
                    <span class="env-label">数据库路径</span>
                    <code class="env-val">{{ store.health?.db_file || './data/tsumugi.db' }}</code>
                  </div>
                  <div class="group-row env-row">
                    <span class="env-label">收藏总数</span>
                    <code class="env-val tabular-nums">{{ store.games.length }} 部</code>
                  </div>
                  <div class="group-row env-row">
                    <span class="env-label">数据表</span>
                    <code class="env-val">{{ store.health?.initialized_tables.join(', ') || '—' }}</code>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="settings-foot">
            <button type="button" class="btn btn-ghost" @click="store.showSettingsModal = false">
              取消
            </button>
            <button type="button" class="btn btn-primary" :disabled="saving" @click="saveAll">
              {{ saving ? '保存中…' : '保存' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 恢复 / 快照回滚二次确认框 -->
      <div
        v-if="pendingRestoreConfirm"
        class="restore-confirm-overlay"
        @click.self="!restoringBackup && (pendingRestoreConfirm = null)"
      >
        <div class="restore-confirm-card" role="alertdialog" aria-modal="true">
          <div class="restore-confirm-title">{{ pendingRestoreConfirm.title }}</div>
          <div class="restore-confirm-target">{{ pendingRestoreConfirm.targetLabel }}</div>
          <p class="restore-confirm-desc">{{ pendingRestoreConfirm.detail }}</p>
          <div class="restore-confirm-actions">
            <button
              type="button"
              class="btn btn-sm btn-ghost"
              :disabled="restoringBackup"
              @click="pendingRestoreConfirm = null"
            >
              取消
            </button>
            <button
              type="button"
              class="btn btn-sm btn-danger"
              :disabled="restoringBackup"
              @click="confirmPendingRestore"
            >
              {{ restoringBackup ? '正在恢复…' : '确认恢复' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-window {
  position: relative;
  width: 760px;
  max-width: calc(100vw - 48px);
  height: 540px;
  max-height: calc(100vh - 48px);
}

.settings-layout {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* Left Fixed Navigation Sidebar (180px) */
.settings-nav {
  width: 180px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  padding: 20px 10px 16px;
  background: rgba(255, 255, 255, 0.015);
  border-right: 1px solid var(--divider-subtle);
}

.nav-title {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--text-primary);
  padding: 0 10px 14px;
}

.nav-items {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.settings-nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 8px 10px 8px 12px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 450;
  text-align: left;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.settings-nav-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 7px;
  bottom: 7px;
  width: 2px;
  border-radius: 2px;
  background: var(--active-bar);
  opacity: 0;
  transform: scaleY(0.5);
  transition:
    opacity var(--duration-fast) var(--ease-out-expo),
    transform var(--duration-fast) var(--ease-out-expo);
}

.settings-nav-item:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.settings-nav-item.active {
  background: var(--surface-active);
  color: var(--text-primary);
  font-weight: 500;
}

.settings-nav-item.active::before {
  opacity: 1;
  transform: scaleY(1);
}

.settings-nav-item svg {
  opacity: 0.72;
  flex-shrink: 0;
}

.settings-nav-item.active svg {
  opacity: 1;
}

/* Right Content Column */
.settings-right {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.pane-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px 14px 26px;
  border-bottom: 1px solid var(--divider-subtle);
  flex-shrink: 0;
}

.pane-topbar h2 {
  margin: 0;
  font-size: 15.5px;
  font-weight: 600;
  color: var(--text-primary);
}

.close-icon-btn {
  width: 28px;
  height: 28px;
  border-radius: 7px;
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

.pane-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 26px 24px;
}

.pane-section {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.group-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.group-label {
  font-size: 11.5px;
  font-weight: 500;
  letter-spacing: 0.04em;
  color: var(--text-muted);
  padding-left: 4px;
}

/* macOS / Raycast 原生分组卡片容器 */
.grouped-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  overflow: hidden;
}

.group-row {
  padding: 14px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.group-row:last-child {
  border-bottom: none;
}

.toggle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.toggle-row:hover {
  background: rgba(255, 255, 255, 0.025);
}

.row-title {
  font-size: 13.5px;
  font-weight: 500;
  color: var(--text-primary);
}

.row-desc {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
  line-height: 1.45;
}

.field-row {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.row-with-btn {
  display: flex;
  gap: 8px;
}

/* Sources Accordion inside Grouped Card */
.source-item {
  padding: 0;
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.source-item.expandable:hover {
  background: rgba(255, 255, 255, 0.025);
}

.source-item.expanded {
  background: rgba(255, 255, 255, 0.035);
}

.source-row-wrap {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
}

.source-row {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  padding: 0;
  border: none;
  background: transparent;
  text-align: left;
  cursor: default;
}

.source-item.expandable .source-row {
  cursor: pointer;
}

.source-meta {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.source-right {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.source-test-btn {
  height: 26px;
  padding: 0 9px;
  font-size: 11px;
}

.accordion-btn {
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 6px;
  background: transparent;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
}

.accordion-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
}

.source-test-feedback {
  padding: 0 16px 10px;
  font-size: 11.5px;
  line-height: 1.4;
}

.source-test-feedback.ok {
  color: var(--emerald-text);
}

.source-test-feedback.err {
  color: var(--danger-text);
}

.source-field-block {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.source-field-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.source-field-label {
  font-size: 11.5px;
  color: var(--text-secondary);
}

.clear-secret-btn {
  border: none;
  background: transparent;
  padding: 0;
  font-size: 11px;
  color: var(--danger-text);
  opacity: 0.85;
  cursor: pointer;
}

.clear-secret-btn:hover {
  opacity: 1;
  text-decoration: underline;
}

.status-capsule {
  font-size: 11px;
  font-weight: 500;
  padding: 3px 8px;
  border-radius: 999px;
  white-space: nowrap;
}

.status-capsule.tone-free {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-secondary);
}

.status-capsule.tone-ok {
  background: var(--emerald-bg);
  color: var(--emerald-text);
}

.status-capsule.tone-missing {
  background: var(--amber-bg);
  color: var(--amber-text);
}

.status-capsule.tone-optional {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-muted);
}

.accordion-chevron {
  color: var(--text-muted);
  transition: transform var(--duration-fast) var(--ease-out-expo);
}

.accordion-chevron.open {
  transform: rotate(180deg);
  color: var(--text-primary);
}

.source-body {
  padding: 0 16px 14px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.secret-input-wrap {
  position: relative;
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
}

.source-input-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.verify-btn {
  height: 37px;
  padding: 0 14px;
  flex-shrink: 0;
}

.verify-feedback {
  font-size: 12px;
  line-height: 1.4;
}

.verify-feedback.ok {
  color: var(--emerald-text);
}

.verify-feedback.err {
  color: var(--danger-text);
}

.source-hint-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.source-ext-link {
  font-size: 11.5px;
  color: var(--text-primary);
  opacity: 0.78;
  text-decoration: none;
  white-space: nowrap;
  transition: opacity var(--duration-fast) var(--ease-out-expo);
}

.source-ext-link:hover {
  opacity: 1;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.secret-input {
  padding-right: 38px;
}

.eye-btn {
  position: absolute;
  right: 6px;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.eye-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.source-hint {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--text-muted);
}

/* 版本与更新（GitHub Releases） */
.update-main-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.update-meta {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.update-title-line {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.version-pill {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 500;
  line-height: 1;
  padding: 3px 7px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-secondary);
}

.update-status-line.status-up_to_date {
  color: var(--emerald-text);
}

.update-status-line.status-update_available {
  color: var(--text-primary);
}

.update-status-line.status-not_published,
.update-status-line.status-rate_limited {
  color: var(--amber-text);
}

.update-status-line.status-error {
  color: var(--danger-text);
}

.update-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.github-ext-btn {
  display: inline-flex;
  align-items: center;
  height: 30px;
  padding: 0 9px;
  border-radius: 7px;
  color: var(--text-muted);
  font-size: 12px;
  text-decoration: none;
  white-space: nowrap;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.github-ext-btn:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-primary);
}

.update-expand-row {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: rgba(255, 255, 255, 0.018);
  animation: update-reveal 200ms var(--ease-out-expo);
}

@keyframes update-reveal {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.release-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.release-ver {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.release-date {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-muted);
}

.release-notes {
  max-height: 160px;
  overflow-y: auto;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.24);
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

.release-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 2px;
}

.release-primary-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 30px;
  padding: 0 13px;
  border-radius: 8px;
  background: #f5f5f7;
  color: #0a0a0c;
  font-size: 12px;
  font-weight: 600;
  text-decoration: none;
  transition: opacity var(--duration-fast) var(--ease-out-expo);
}

.release-primary-btn:hover {
  opacity: 0.9;
}

.release-dl-btn {
  text-decoration: none;
}

/* 存储占用面板（macOS 风格分类占用条） */
.storage-overview-row {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.storage-top-line {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.storage-total {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.storage-bar {
  width: 100%;
  height: 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  overflow: hidden;
  display: flex;
  gap: 2px;
}

.storage-seg {
  height: 100%;
  transition: width 320ms var(--ease-out-expo);
}

.storage-seg:first-child {
  border-top-left-radius: 999px;
  border-bottom-left-radius: 999px;
}

.storage-seg:last-child {
  border-top-right-radius: 999px;
  border-bottom-right-radius: 999px;
}

.storage-legend {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 7px 18px;
}

.legend-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}

.legend-left {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.legend-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.legend-name {
  color: var(--text-secondary);
}

.legend-val {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-muted);
}

.action-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

/* Backup & Snapshot Cards */
.backup-check-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
}

.backup-check-left {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.backup-checkbox {
  width: 15px;
  height: 15px;
  margin-top: 2px;
  accent-color: #f5f5f7;
  cursor: pointer;
  flex-shrink: 0;
}

.backup-actions-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.sr-only-input {
  display: none;
}

.group-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-right: 4px;
}

.snap-collapse-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 11.5px;
  padding: 2px 6px;
  border-radius: 6px;
  transition: color var(--duration-fast) var(--ease-out-expo), background-color var(--duration-fast) var(--ease-out-expo);
}

.snap-collapse-btn:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.06);
}

.snap-chevron {
  transition: transform var(--duration-fast) var(--ease-out-expo);
}

.snap-chevron.open {
  transform: rotate(180deg);
}

.snap-empty-row {
  padding-top: 14px;
  padding-bottom: 14px;
}

.snap-item-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.snap-meta {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.snap-top-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.snap-time {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-primary);
}

.snap-tag {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 7px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 500;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
}

.snap-tag.tag-pre_restore {
  background: rgba(245, 158, 11, 0.16);
  color: var(--amber-text);
}

.snap-tag.tag-pre_import {
  background: rgba(16, 185, 129, 0.16);
  color: var(--emerald-text);
}

.snap-sub {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  color: var(--text-muted);
}

.snap-filename {
  font-family: var(--font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 280px;
}

.snap-size {
  font-family: var(--font-mono);
  flex-shrink: 0;
}

/* Secondary Restore Confirmation Dialog */
.restore-confirm-overlay {
  position: absolute;
  inset: 0;
  z-index: 20;
  background: rgba(4, 4, 6, 0.72);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.restore-confirm-card {
  width: 100%;
  max-width: 400px;
  padding: 20px 22px;
  border-radius: 14px;
  background: rgba(20, 20, 25, 0.96);
  border: 1px solid rgba(255, 255, 255, 0.12);
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.72);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.restore-confirm-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.restore-confirm-target {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--amber-text);
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.2);
  border-radius: 8px;
  padding: 7px 10px;
  word-break: break-all;
}

.restore-confirm-desc {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--text-secondary);
}

.restore-confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 6px;
}

/* Environment Rows */
.env-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  font-size: 12.5px;
}

.env-label {
  color: var(--text-muted);
  flex-shrink: 0;
}

.env-val {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-secondary);
  text-align: right;
  word-break: break-all;
}

/* Fixed Bottom Action Footer */
.settings-foot {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  padding: 14px 24px;
  border-top: 1px solid var(--divider-subtle);
  flex-shrink: 0;
}

@media (max-width: 680px) {
  .settings-window {
    height: auto;
    max-height: 88vh;
  }
  .settings-layout {
    flex-direction: column;
  }
  .settings-nav {
    width: 100%;
    border-right: none;
    border-bottom: 1px solid var(--divider-subtle);
    padding: 12px;
  }
  .nav-items {
    flex-direction: row;
    overflow-x: auto;
  }
}
</style>
