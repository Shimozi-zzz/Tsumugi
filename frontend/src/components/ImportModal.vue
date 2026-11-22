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
  ImportTab,
  MusicCandidate,
  ScrapedGameItem,
} from '@/types'
import { normalizePlatformBadge } from '@/utils/platform'

const store = useLibraryStore()
const taskStore = useTaskStore()
const hasBridge = isDesktopBridgeAvailable()

const tabs: { id: ImportTab; label: string; badge: string }[] = [
  { id: 'aggregated', label: '推荐聚合导入', badge: 'MULTI' },
  { id: 'bgm', label: 'Bangumi', badge: 'BGM' },
  { id: 'vndb', label: 'VNDB', badge: 'VNDB' },
  { id: 'steam', label: 'Steam & SGDB', badge: 'STEAM' },
  { id: 'tgal', label: 'TouchGal', badge: 'TGAL' },
  { id: 'local', label: '本地 / 批量', badge: 'LOCAL' },
]

const activeTab = ref<ImportTab>(store.importInitialTab || 'aggregated')
const steamSubSource = ref<'steam' | 'sgdb'>('steam')
const localMode = ref<'single' | 'batch'>(store.importInitialLocalMode || 'single')

// 在线检索状态
const keyword = ref('')
const searching = ref(false)
const searchResults = ref<ScrapedGameItem[]>([])
const searchedOnce = ref(false)
const sgdbConfigured = ref(true)

// 预览微调状态
const aggregating = ref(false)
const importing = ref(false)
const matchedSources = ref<string[]>([])
const AUTO_BGM_KEY = 'tsumugi:import:auto_fetch_bgm'
const autoFetchBgm = ref(
  (() => {
    try {
      return window.localStorage.getItem(AUTO_BGM_KEY) === '1'
    } catch {
      return false
    }
  })(),
)

function toggleAutoFetchBgm(ev: Event) {
  const checked = (ev.target as HTMLInputElement).checked
  autoFetchBgm.value = checked
  try {
    window.localStorage.setItem(AUTO_BGM_KEY, checked ? '1' : '0')
  } catch {
    // ignore
  }
}
const previewDraft = ref<{
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

// 附带影音（可选）折叠挑选项
const optionalMediaOpen = ref(false)
const pvSearching = ref(false)
const pvSearchedOnce = ref(false)
const pvCandidates = ref<AssetCandidate[]>([])
const selectedPv = ref<AssetCandidate | null>(null)

const bgmSearching = ref(false)
const bgmSearchedOnce = ref(false)
const bgmCandidates = ref<MusicCandidate[]>([])
const selectedBgm = ref<MusicCandidate | null>(null)

function resetOptionalMedia() {
  optionalMediaOpen.value = false
  pvSearching.value = false
  pvSearchedOnce.value = false
  pvCandidates.value = []
  selectedPv.value = null
  bgmSearching.value = false
  bgmSearchedOnce.value = false
  bgmCandidates.value = []
  selectedBgm.value = null
}

function formatDurationSec(sec: number | null | undefined): string {
  if (!sec || sec <= 0) return ''
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

async function searchOptionalPv() {
  const d = previewDraft.value
  const q = (d?.sub_title || d?.title || '').trim()
  if (!q || pvSearching.value) return
  optionalMediaOpen.value = true
  pvSearching.value = true
  pvSearchedOnce.value = true
  try {
    const res = await scraperApi.searchAssets('pv', q, 'all')
    pvCandidates.value = res.items || []
  } catch (err) {
    pvCandidates.value = []
    store.notify(err instanceof Error ? err.message : 'PV 查找失败', 'warning')
  } finally {
    pvSearching.value = false
  }
}

async function searchOptionalBgm() {
  const d = previewDraft.value
  const q = (d?.sub_title || d?.title || '').trim()
  if (!q || bgmSearching.value) return
  optionalMediaOpen.value = true
  bgmSearching.value = true
  bgmSearchedOnce.value = true
  try {
    const res = await scraperApi.searchMusic(q)
    bgmCandidates.value = res.items || []
  } catch (err) {
    bgmCandidates.value = []
    store.notify(err instanceof Error ? err.message : '主题曲查找失败', 'warning')
  } finally {
    bgmSearching.value = false
  }
}

function toggleSelectPv(item: AssetCandidate) {
  selectedPv.value = selectedPv.value?.id === item.id ? null : item
}

function toggleSelectBgm(item: MusicCandidate) {
  selectedBgm.value = selectedBgm.value?.id === item.id ? null : item
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

const effectiveSource = computed(() => {
  if (activeTab.value === 'steam') return steamSubSource.value
  return activeTab.value
})

onMounted(() => {
  if (store.droppedFileInfo) {
    const info = store.droppedFileInfo
    if (info.kind === 'folder') {
      activeTab.value = 'local'
      localMode.value = 'batch'
      scanRootDir.value = info.folder_path
      void runBatchScan()
    } else {
      activeTab.value = 'local'
      localMode.value = 'single'
      localForm.title = info.suggested_title
      localForm.exe_path = info.exe_path
      keyword.value = info.suggested_title
    }
    store.droppedFileInfo = null
  }
})

function switchTab(t: ImportTab) {
  activeTab.value = t
  previewDraft.value = null
  searchResults.value = []
  searchedOnce.value = false
}

async function runSearch() {
  const q = keyword.value.trim()
  if (!q) return
  searching.value = true
  searchedOnce.value = true
  previewDraft.value = null
  try {
    const res = await scraperApi.search(q, effectiveSource.value, 10)
    searchResults.value = res.items
    sgdbConfigured.value = res.sgdb_configured
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '检索失败，请检查网络或代理设置', 'error')
  } finally {
    searching.value = false
  }
}

function buildDraftFromItem(item: ScrapedGameItem) {
  resetOptionalMedia()
  const extIds = { ...(item.extra_ids || {}) }
  previewDraft.value = {
    title: item.title,
    sub_title: item.sub_title,
    developer: item.developer,
    publisher: item.publisher,
    release_date: item.release_date,
    synopsis: item.synopsis,
    tagsText: (item.tags || []).join(', '),
    status: 'todo',
    edition: 'collector',
    is_nsfw: item.is_nsfw,
    source_platform: normalizePlatformBadge(item.source, item.extra_ids) || 'PC',
    bangumi_id: (item.bangumi_id || extIds.bgm || extIds.bangumi || '').trim(),
    external_ids: extIds,
    cover_url: item.cover_url,
    logo_url: item.logo_url,
    hero_bg_url: item.hero_bg_url,
    pv_url: item.pv_url,
    screenshots: [...(item.screenshots || [])],
    exe_path: localForm.exe_path || '',
    launch_mode: 'direct',
    launch_args: '',
    save_dir: '',
    screenshot_dir: '',
  }
}

async function selectCandidate(item: ScrapedGameItem) {
  aggregating.value = true
  matchedSources.value = []
  try {
    if (activeTab.value === 'aggregated') {
      const res = await scraperApi.aggregate(item.title, item.extra_ids || {})
      matchedSources.value = res.matched_sources
      buildDraftFromItem(res.item)
    } else {
      const src = effectiveSource.value
      const detail = item.external_id
        ? await scraperApi.detail(src, item.external_id).catch(() => item)
        : item
      matchedSources.value = [src]
      buildDraftFromItem(detail)
    }
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '拉取完整详情失败', 'error')
    buildDraftFromItem(item)
  } finally {
    aggregating.value = false
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

    const pvPicked = selectedPv.value
    const bgmPicked = selectedBgm.value
    const bgmPickedUrl = bgmPicked ? (bgmPicked.source_url || bgmPicked.preview_url || '') : ''

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
      pv_url: d.pv_url,
      selected_pv_url: pvPicked ? pvPicked.url : null,
      selected_pv_source: pvPicked ? pvPicked.source : null,
      selected_pv_mime_hint: pvPicked ? pvPicked.mime_hint : null,
      selected_bgm_url: bgmPickedUrl || null,
      screenshots: d.screenshots,
      download_screenshots: true,
      auto_fetch_bgm: bgmPickedUrl ? false : autoFetchBgm.value,
      exe_path: d.exe_path.trim(),
      launch_mode: d.launch_mode,
      launch_args: d.launch_args.trim(),
      save_dir: d.save_dir.trim(),
      screenshot_dir: d.screenshot_dir.trim(),
    })

    store.addOrFocusGame(created)

    const queuedPvUrl = pvPicked?.url || (d.pv_url.trim().startsWith('http') ? d.pv_url.trim() : '')
    if (queuedPvUrl) {
      taskStore.trackTask(
        {
          game_id: created.id,
          asset_type: 'pv',
          status: 'queued',
          progress: 0,
          message: '等待下载宣传片…',
        },
        {
          url: queuedPvUrl,
          source: pvPicked?.source || '',
          mime_hint: pvPicked?.mime_hint || '',
        },
      )
    }
    if (bgmPickedUrl || autoFetchBgm.value) {
      taskStore.trackTask({
        game_id: created.id,
        asset_type: 'bgm',
        status: 'queued',
        progress: 0,
        message: '等待下载主题曲…',
      })
    }

    store.notify(
      queuedPvUrl || bgmPickedUrl
        ? `《${created.title}》已入库，影音正在后台下载`
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
        <div>
          <h2>导入游戏</h2>
        </div>
        <button class="close-icon-btn" aria-label="关闭" @click="store.showImportModal = false">
          <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" />
          </svg>
        </button>
      </div>

      <!-- 无边框药丸标签页导航 -->
      <div class="import-tabs">
        <button
          v-for="t in tabs"
          :key="t.id"
          class="tab-btn"
          :class="{ active: activeTab === t.id }"
          @click="switchTab(t.id)"
        >
          <span>{{ t.label }}</span>
          <span class="tab-badge">{{ t.badge }}</span>
        </button>
      </div>

      <div class="modal-body">
        <!-- 在线刮削标签页（前 5 个 Tab） -->
        <template v-if="activeTab !== 'local'">
          <div class="search-bar-row">
            <div v-if="activeTab === 'steam'" class="sub-toggle">
              <button :class="{ active: steamSubSource === 'steam' }" @click="steamSubSource = 'steam'">
                Steam
              </button>
              <button :class="{ active: steamSubSource === 'sgdb' }" @click="steamSubSource = 'sgdb'">
                SteamGridDB
              </button>
            </div>
            <input
              v-model="keyword"
              class="input search-input"
              placeholder="输入中文名、日文原名或英文名（如 Summer Pockets、CLANNAD、Elden Ring）"
              @keydown.enter="runSearch"
            />
            <button class="btn btn-primary" :disabled="searching" @click="runSearch">
              {{ searching ? '检索中…' : '搜索' }}
            </button>
          </div>

          <div v-if="activeTab === 'steam' && steamSubSource === 'sgdb' && !sgdbConfigured" class="tip-banner">
            尚未配置 SteamGridDB API Key，请前往「全局设置」填写后启用高清透明 Logo 与宽幅 Hero 检索。
          </div>

          <!-- 入库前预览与微调表单 -->
          <div v-if="aggregating" class="center-loading">
            <div class="spinner" />
            <span>正在并发拉取多源详情与高清视觉资产…</span>
          </div>

          <div v-else-if="previewDraft" class="preview-editor">
            <div class="preview-top">
              <button class="btn btn-sm btn-ghost" @click="previewDraft = null">← 返回候选列表</button>
              <div class="matched-pills">
                <span class="muted">命中源</span>
                <span v-for="s in matchedSources" :key="s" class="src-pill">{{ s.toUpperCase() }}</span>
              </div>
            </div>

            <!-- 视觉资产预览条 -->
            <div class="visual-strip">
              <div class="vis-box cover">
                <img v-if="previewDraft.cover_url" :src="previewDraft.cover_url" alt="Cover" />
                <span v-else>无竖版封面</span>
                <span class="vis-tag">封面 Cover</span>
              </div>
              <div class="vis-box hero">
                <img v-if="previewDraft.hero_bg_url" :src="previewDraft.hero_bg_url" alt="Hero" />
                <span v-else>无 Hero 宽幅背景</span>
                <span class="vis-tag">宽幅 Hero</span>
              </div>
              <div class="vis-box logo">
                <img v-if="previewDraft.logo_url" :src="previewDraft.logo_url" alt="Logo" />
                <span v-else>无透明 Logo（将用衬线标题）</span>
                <span class="vis-tag">透明 Logo</span>
              </div>
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
                    @click="searchOptionalPv"
                  >
                    {{ pvSearching ? '查找中…' : '查找 PV' }}
                  </button>
                  <button
                    type="button"
                    class="btn btn-sm"
                    :disabled="bgmSearching"
                    @click="searchOptionalBgm"
                  >
                    {{ bgmSearching ? '查找中…' : '查找 OP' }}
                  </button>
                </div>
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
                          <span>{{ item.source }}</span>
                          <span v-if="formatDurationSec(item.duration)" class="tabular-nums">
                            {{ formatDurationSec(item.duration) }}
                          </span>
                        </div>
                      </div>
                      <span class="opt-check">{{ selectedPv?.id === item.id ? '已选' : '选择' }}</span>
                    </button>
                  </div>
                  <div v-else-if="pvSearchedOnce && !pvSearching" class="opt-empty">
                    未找到宣传片候选
                  </div>
                  <div v-else-if="!pvSearching" class="opt-empty">
                    点击「查找 PV」挑选并后台下载
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
                    未找到主题曲候选
                  </div>
                  <div v-else-if="!bgmSearching" class="opt-empty">
                    点击「查找 OP」手选，或勾选下方自动匹配
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
                <label v-if="!selectedBgm" class="bgm-opt-check">
                  <input
                    type="checkbox"
                    class="opt-checkbox"
                    :checked="autoFetchBgm"
                    @change="toggleAutoFetchBgm"
                  />
                  <span>自动匹配主题曲 (OP)</span>
                </label>
              </div>
              <button class="btn btn-primary" :disabled="importing" @click="confirmScrapedImport">
                {{ importing ? '入库中…' : '确认导入' }}
              </button>
            </div>
          </div>

          <!-- 候选卡片列表 -->
          <div v-else class="candidate-grid">
            <button
              v-for="(item, idx) in searchResults"
              :key="`${item.source}-${item.external_id}-${idx}`"
              class="candidate-card"
              @click="selectCandidate(item)"
            >
              <div class="cand-cover">
                <img v-if="item.cover_url" :src="item.cover_url" alt="" loading="lazy" />
                <span v-else class="cand-no-img">{{ item.source }}</span>
                <span class="cand-source">{{ item.source }}</span>
              </div>
              <div class="cand-body">
                <div class="cand-title">{{ item.title }}</div>
                <div class="cand-sub">{{ item.sub_title || item.developer || item.release_date || '点击查看详情' }}</div>
                <div class="cand-tags">
                  <span v-for="t in (item.tags || []).slice(0, 3)" :key="t">{{ t }}</span>
                </div>
              </div>
            </button>

            <div v-if="searchedOnce && !searching && searchResults.length === 0" class="empty-search">
              没有找到匹配结果，可尝试更换原名或英文名，或切换至「本地 / 批量」手动添加。
            </div>
            <div v-if="!searchedOnce" class="empty-search">
              输入游戏名称并按回车搜索资料。
            </div>
          </div>
        </template>

        <!-- Tab 6: 本地自定义 + 批量目录扫描 -->
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
                  <span>入库时自动并发刮削封面、简介与标签</span>
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
  max-width: 940px;
}

.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 20px 24px 12px;
}

.modal-head h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
}

.modal-desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-muted);
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

/* Borderless Pill Tabs */
.import-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  padding: 0 24px 14px;
  border-bottom: 1px solid var(--divider-subtle);
}

.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border-radius: 999px;
  border: none;
  background: transparent;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-secondary);
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.tab-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.tab-btn.active {
  background: var(--surface-active);
  color: #ffffff;
}

.tab-badge {
  font-family: var(--font-mono);
  font-size: 9.5px;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-muted);
}

.tab-btn.active .tab-badge {
  background: rgba(255, 255, 255, 0.14);
  color: var(--text-primary);
}

.modal-body {
  padding: 18px 24px 22px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.search-bar-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

.search-input {
  flex: 1;
}

.sub-toggle {
  display: flex;
  padding: 3px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.05);
}

.sub-toggle button {
  padding: 6px 12px;
  border: none;
  border-radius: 7px;
  background: transparent;
  font-size: 12px;
  color: var(--text-secondary);
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.sub-toggle button.active {
  background: rgba(255, 255, 255, 0.13);
  color: #ffffff;
}

.tip-banner {
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--amber-bg);
  color: var(--amber-text);
  font-size: 12.5px;
}

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
  border: none;
  background: rgba(255, 255, 255, 0.03);
  text-align: left;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    transform var(--duration-fast) var(--ease-out-expo);
}

.candidate-card:hover {
  background: rgba(255, 255, 255, 0.08);
  transform: translateY(-1px);
}

.cand-cover {
  position: relative;
  width: 66px;
  height: 92px;
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
  font-size: 11px;
  color: var(--text-muted);
}

.cand-source {
  position: absolute;
  bottom: 4px;
  left: 4px;
  font-family: var(--font-mono);
  font-size: 9px;
  padding: 2px 5px;
  border-radius: 4px;
  background: rgba(10, 10, 12, 0.78);
  color: var(--text-primary);
}

.cand-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.cand-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.cand-sub {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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
  padding: 44px 20px;
  text-align: center;
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.75;
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

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

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
  transition: color var(--duration-fast) var(--ease-out-expo);
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
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
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
  padding: 16px 8px;
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.02);
}

@media (max-width: 720px) {
  .optional-media-body {
    grid-template-columns: 1fr;
  }
}
</style>
