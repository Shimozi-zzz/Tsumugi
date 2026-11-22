<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  isDesktopBridgeAvailable,
  pickNativeFile,
  scraperApi,
  systemApi,
} from '@/api/client'
import { SCRAPER_SOURCES, type ScraperSourceConfig } from '@/config/scraperSources'
import { useLibraryStore } from '@/stores/library'
import type {
  AppVersionInfo,
  BangumiMeResponse,
  SettingsSectionId,
  StorageUsageResponse,
  UpdateCheckResponse,
} from '@/types'

const DEFAULT_SOURCE_LINKS: Record<string, string> = {
  bangumi: 'https://next.bgm.tv/demo/access-token',
  steamgriddb: 'https://www.steamgriddb.com/profile/preferences/api',
}

const store = useLibraryStore()
const saving = ref(false)
const hasDesktopBridge = isDesktopBridgeAvailable()
const activeSection = ref<SettingsSectionId>(store.settingsInitialSection || 'general')

const navSections: { id: SettingsSectionId; label: string }[] = [
  { id: 'general', label: '常规与隐私' },
  { id: 'network', label: '网络与启动' },
  { id: 'sources', label: '数据源管理' },
  { id: 'environment', label: '运行环境' },
]

const initialApiKeys: Record<string, string> = {
  ...(store.settings.api_keys || {}),
}
if (!initialApiKeys.bangumi && store.settings.bangumi_token) {
  initialApiKeys.bangumi = store.settings.bangumi_token
}
for (const src of SCRAPER_SOURCES) {
  if (src.keyField && initialApiKeys[src.keyField] == null) {
    initialApiKeys[src.keyField] = ''
  }
}

const form = reactive({
  proxy_url: store.settings.proxy_url || '',
  le_exe_path: store.settings.le_exe_path || '',
  allow_nsfw_scrape: Boolean(store.settings.allow_nsfw_scrape),
  privacy_blur_mode: Boolean(store.settings.privacy_blur_mode),
  bgm_autoplay: store.settings.bgm_autoplay !== false,
  gallery_particles: store.settings.gallery_particles !== false,
  api_keys: initialApiKeys,
})

const expandedSourceId = ref<string | null>(store.settingsInitialExpandSource || null)
const revealedKeys = reactive<Record<string, boolean>>({})

// Bangumi Token 验证状态
const verifyingBgm = ref(false)
const bgmVerifyResult = ref<BangumiMeResponse | null>(null)

// 运行环境：版本与更新检查状态
const versionInfo = ref<AppVersionInfo | null>(null)
const checkingUpdate = ref(false)
const updateResult = ref<UpdateCheckResponse | null>(null)

// 运行环境存储治理状态
const storageLoading = ref(false)
const storageStats = ref<StorageUsageResponse | null>(null)
const cleaningStorage = ref(false)
const convertingWebp = ref(false)

const sourceLinks = computed<Record<string, string | undefined>>(() => ({
  ...DEFAULT_SOURCE_LINKS,
  ...(store.settings.source_links || {}),
}))

function getSourceDocUrl(srcId: string): string {
  return sourceLinks.value[srcId] || ''
}

function getSourceLinkLabel(srcId: string): string {
  return srcId === 'bangumi' ? '获取 Token ↗' : '获取 API Key ↗'
}

async function handleVerifyBangumi() {
  if (verifyingBgm.value) return
  verifyingBgm.value = true
  bgmVerifyResult.value = null
  try {
    const token = (form.api_keys.bangumi || '').trim()
    bgmVerifyResult.value = await scraperApi.verifyBangumiMe(token)
  } catch (err) {
    bgmVerifyResult.value = {
      valid: false,
      detail: err instanceof Error ? err.message : '验证请求失败',
    }
  } finally {
    verifyingBgm.value = false
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
  key: keyof Pick<StorageUsageResponse, 'videos' | 'audios' | 'images' | 'backups' | 'database' | 'orphans'>
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
    { key: 'videos', label: '宣传片视频', color: '#6088b8' },
    { key: 'audios', label: '主题曲音频', color: '#4f9c88' },
    { key: 'images', label: '图片资产', color: '#c49a5c' },
    { key: 'backups', label: '存档备份', color: '#7b8794' },
    { key: 'database', label: '数据库', color: '#a1a1aa' },
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

const hasReleasableOrphans = computed(() => {
  const o = storageStats.value?.orphans
  return Boolean(o && (o.bytes > 0 || o.files > 0 || (o.dirs || 0) > 0))
})

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
    if (sec === 'environment') {
      if (!versionInfo.value) {
        void loadVersionInfo()
      }
      if (!storageStats.value) {
        void loadStorageStats()
      }
    }
  },
  { immediate: true },
)

onMounted(() => {
  store.settingsInitialSection = 'general'
  store.settingsInitialExpandSource = null
})

function toggleSourceAccordion(src: ScraperSourceConfig) {
  if (src.authType === 'none') return
  expandedSourceId.value = expandedSourceId.value === src.id ? null : src.id
}

function toggleKeyVisibility(field: string) {
  revealedKeys[field] = !revealedKeys[field]
}

function getSourceStatus(src: ScraperSourceConfig): {
  label: string
  tone: 'free' | 'ok' | 'missing' | 'optional'
} {
  if (src.authType === 'none') {
    return { label: '免密直连', tone: 'free' }
  }
  const hasVal = Boolean(src.keyField && (form.api_keys[src.keyField] || '').trim())
  if (hasVal) {
    return { label: '已配置', tone: 'ok' }
  }
  return {
    label: '未配置',
    tone: src.authType === 'required' ? 'missing' : 'optional',
  }
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
    const cleanedKeys: Record<string, string> = {}
    for (const [k, v] of Object.entries(form.api_keys)) {
      cleanedKeys[k] = (v || '').trim()
    }

    await Promise.all([
      store.updateSetting('proxy_url', form.proxy_url.trim()),
      store.updateSetting('le_exe_path', form.le_exe_path.trim()),
      store.updateSetting('allow_nsfw_scrape', form.allow_nsfw_scrape),
      store.updateSetting('privacy_blur_mode', form.privacy_blur_mode),
      store.updateSetting('bgm_autoplay', form.bgm_autoplay),
      store.updateSetting('gallery_particles', form.gallery_particles),
      store.updateSetting('api_keys', {
        steamgriddb: cleanedKeys.steamgriddb || '',
        touchgal: cleanedKeys.touchgal || '',
        bangumi: cleanedKeys.bangumi || '',
        ...cleanedKeys,
      }),
    ])
    store.notify('设置已保存', 'success')
    store.showSettingsModal = false
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

            <!-- 3. 数据源管理：合并式原生分组手风琴 -->
            <div v-else-if="activeSection === 'sources'" class="pane-section">
              <div class="grouped-card">
                <div
                  v-for="src in SCRAPER_SOURCES"
                  :key="src.id"
                  class="group-row source-item"
                  :class="{
                    expandable: src.authType !== 'none',
                    expanded: expandedSourceId === src.id,
                  }"
                >
                  <button
                    type="button"
                    class="source-row"
                    :disabled="src.authType === 'none'"
                    @click="toggleSourceAccordion(src)"
                  >
                    <div class="source-meta">
                      <span class="row-title">{{ src.name }}</span>
                      <span class="row-desc">{{ src.description }}</span>
                    </div>

                    <div class="source-right">
                      <span class="status-capsule" :class="`tone-${getSourceStatus(src).tone}`">
                        {{ getSourceStatus(src).label }}
                      </span>

                      <svg
                        v-if="src.authType !== 'none'"
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
                    </div>
                  </button>

                  <div
                    v-if="src.authType !== 'none' && src.keyField && expandedSourceId === src.id"
                    class="source-body"
                  >
                    <div class="source-input-row">
                      <div class="secret-input-wrap">
                        <input
                          v-model="form.api_keys[src.keyField]"
                          class="input secret-input"
                          :type="revealedKeys[src.keyField] ? 'text' : 'password'"
                          autocomplete="off"
                          :placeholder="src.placeholder || '输入 API Key'"
                          @input="src.id === 'bangumi' && (bgmVerifyResult = null)"
                        />
                        <button
                          type="button"
                          class="eye-btn"
                          :title="revealedKeys[src.keyField] ? '隐藏' : '显示'"
                          @click="toggleKeyVisibility(src.keyField)"
                        >
                          <svg
                            v-if="revealedKeys[src.keyField]"
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
                        v-if="src.id === 'bangumi'"
                        type="button"
                        class="btn btn-sm verify-btn"
                        :disabled="verifyingBgm"
                        @click="handleVerifyBangumi"
                      >
                        {{ verifyingBgm ? '验证中…' : '验证' }}
                      </button>
                    </div>

                    <div
                      v-if="src.id === 'bangumi' && bgmVerifyResult"
                      class="verify-feedback"
                      :class="bgmVerifyResult.valid ? 'ok' : 'err'"
                    >
                      <template v-if="bgmVerifyResult.valid">
                        已验证：{{ bgmVerifyResult.nickname || bgmVerifyResult.username }}
                      </template>
                      <template v-else>
                        {{ bgmVerifyResult.detail || 'Access Token 无效或已过期' }}
                      </template>
                    </div>

                    <div class="source-hint-row">
                      <span v-if="src.docHint" class="source-hint">{{ src.docHint }}</span>
                      <a
                        v-if="getSourceDocUrl(src.id)"
                        :href="getSourceDocUrl(src.id)"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="source-ext-link"
                      >
                        {{ getSourceLinkLabel(src.id) }}
                      </a>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 4. 运行环境与存储治理 -->
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
    </div>
  </div>
</template>

<style scoped>
.settings-window {
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

.source-row {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 16px;
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
