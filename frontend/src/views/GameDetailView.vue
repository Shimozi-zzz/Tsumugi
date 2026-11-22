<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ApiError, assetUrl, gamesApi, libraryApi, mediaApi, thumbUrl } from '@/api/client'
import BangumiBindModal from '@/components/BangumiBindModal.vue'
import BindExeModal from '@/components/BindExeModal.vue'
import LightboxModal from '@/components/LightboxModal.vue'
import LocalVideoPlayer from '@/components/LocalVideoPlayer.vue'
import PhonographPill from '@/components/PhonographPill.vue'
import { useLibraryStore } from '@/stores/library'
import { useTaskStore } from '@/stores/tasks'
import type { BackupItem, PlaySession, ScreenshotItem } from '@/types'
import { normalizePlatformBadge } from '@/utils/platform'

const store = useLibraryStore()
const taskStore = useTaskStore()

const game = computed(() => store.activeGame)
const blurred = computed(() => store.shouldBlurGame(game.value))
const displayPlatform = computed(() =>
  game.value ? normalizePlatformBadge(game.value.source_platform, game.value.external_ids) : '',
)

const synopsisExpanded = ref(false)
const screenshots = ref<ScreenshotItem[]>([])
const sessions = ref<PlaySession[]>([])
const backups = ref<BackupItem[]>([])
const showBackups = ref(false)
const showSessions = ref(false)
const showBindExeModal = ref(false)
const showBangumiBindModal = ref(false)
const syncingBangumi = ref(false)
const refreshingMeta = ref(false)
const creatingBackup = ref(false)
const lightboxIndex = ref<number | null>(null)
const belowFoldRef = ref<HTMLElement | null>(null)

const pvTask = computed(() => taskStore.getTask(game.value?.id, 'pv'))
const showPvTaskBar = computed(
  () => Boolean(pvTask.value && pvTask.value.status !== 'done'),
)

const bangumiTargetLabel = computed(() => {
  const s = (game.value?.status || 'todo').toLowerCase()
  if (s === 'playing') return '在玩'
  if (s === 'done' || s === 'completed') return '玩过'
  return '想玩'
})

const hasHeroBg = computed(() => Boolean(game.value?.media?.hero_bg_path))

const heroImageUrl = computed(() => {
  const m = game.value?.media
  if (!m) return ''
  return assetUrl(m.hero_bg_path || m.cover_path || m.cover_thumb_path, store.assetVersion)
})

const coverImageUrl = computed(() => {
  const m = game.value?.media
  if (!m) return ''
  return assetUrl(m.cover_path || m.cover_thumb_path, store.assetVersion)
})

const logoImageUrl = computed(() => {
  const m = game.value?.media
  if (!m?.logo_path) return ''
  return assetUrl(m.logo_path, store.assetVersion)
})

const isThisGameRunning = computed(
  () => store.running.running && store.running.game_id === game.value?.id,
)
const isAnotherGameRunning = computed(
  () => store.running.running && store.running.game_id !== game.value?.id,
)

const displayTotalSeconds = computed(() => {
  if (isThisGameRunning.value) {
    return store.running.total_seconds
  }
  return game.value?.play_record?.total_seconds || 0
})

function formatClock(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  return [h, m, r].map((n) => String(n).padStart(2, '0')).join(':')
}

function formatDurationHuman(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  if (s === 0) return '尚未游玩'
  if (s < 60) return `${s} 秒`
  const mins = Math.floor(s / 60)
  if (mins < 60) return `${mins} 分钟`
  const hours = (s / 3600).toFixed(1)
  return `${hours} 小时`
}

function formatDateTime(iso?: string | null): string {
  if (!iso) return '从未启动'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

const statusLabelMap: Record<string, string> = {
  todo: '未开始',
  unplayed: '未开始',
  playing: '攻略中',
  done: '已通关',
  completed: '已通关',
}

function statusDotClass(status: string): string {
  if (status === 'playing') return 'status-dot-playing'
  if (status === 'done' || status === 'completed') return 'status-dot-done'
  return 'status-dot-todo'
}

const launchModeLabelMap: Record<string, string> = {
  direct: '直接启动 .exe',
  le: 'Locale Emulator 转区',
  cli: '自定义 CLI / URI',
}

async function loadSupplementalData(gameId: number) {
  synopsisExpanded.value = false
  showBackups.value = false
  showSessions.value = false
  try {
    const [ssRes, sessRes, bkRes] = await Promise.all([
      mediaApi.screenshots(gameId).catch(() => ({ game_id: gameId, items: [] })),
      gamesApi.sessions(gameId, 15).catch(() => []),
      libraryApi.listBackups(gameId).catch(() => ({ game_id: gameId, items: [] })),
    ])
    if (game.value?.id !== gameId) return
    screenshots.value = ssRes.items
    sessions.value = sessRes
    backups.value = bkRes.items
  } catch {
    screenshots.value = []
    sessions.value = []
    backups.value = []
  }
}

watch(
  () => game.value?.id,
  (id) => {
    if (id != null) {
      void loadSupplementalData(id)
    } else {
      screenshots.value = []
      sessions.value = []
      backups.value = []
    }
  },
  { immediate: true },
)

// 当游戏结束落盘后刷新会话明细
watch(
  () => store.running.running,
  (isNowRunning, wasRunning) => {
    if (wasRunning && !isNowRunning && game.value) {
      void loadSupplementalData(game.value.id)
    }
  },
)

async function handleStatusChange(ev: Event) {
  if (!game.value) return
  const nextStatus = (ev.target as HTMLSelectElement).value
  await store.updateGamePatch(game.value.id, { status: nextStatus })
  store.notify(`进度已更新为「${statusLabelMap[nextStatus] || nextStatus}」`, 'info')
}

async function handleRefreshMeta() {
  if (!game.value || refreshingMeta.value) return
  refreshingMeta.value = true
  try {
    await store.refreshMetadata(game.value.id)
    await loadSupplementalData(game.value.id)
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '重新刮削失败', 'error')
  } finally {
    refreshingMeta.value = false
  }
}

async function openFolder(target: 'save' | 'screenshot' | 'game') {
  if (!game.value) return
  try {
    const res = await mediaApi.openFolder(game.value.id, target)
    store.notify(`已唤起目录 (${res.adapter})：${res.path}`, 'success')
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '打开目录失败', 'warning')
  }
}

async function createSnapshotBackup() {
  if (!game.value || creatingBackup.value) return
  creatingBackup.value = true
  try {
    const bk = await libraryApi.createBackup(game.value.id)
    backups.value = [bk, ...backups.value]
    showBackups.value = true
    store.notify(`存档快照已创建：${bk.filename} (${formatBytes(bk.size_bytes)})`, 'success')
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '创建存档备份失败', 'warning')
  } finally {
    creatingBackup.value = false
  }
}

async function restoreBackup(filename: string) {
  if (!game.value) return
  try {
    const res = await libraryApi.restoreBackup(game.value.id, filename)
    const refreshed = await libraryApi.listBackups(game.value.id)
    backups.value = refreshed.items
    store.notify(`已恢复 ${res.restored_files} 个存档文件（并自动保留恢复前备份）`, 'success')
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '恢复备份失败', 'error')
  }
}

async function deleteBackup(filename: string) {
  if (!game.value) return
  try {
    await libraryApi.deleteBackup(game.value.id, filename)
    backups.value = backups.value.filter((b) => b.filename !== filename)
    store.notify('已删除该存档快照', 'info')
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '删除备份失败', 'error')
  }
}

function jumpByTag(tag: string) {
  store.setFilterTag(tag)
  store.setViewMode('shelf')
}

function jumpToShelfFocused() {
  if (game.value) {
    store.activeGameId = game.value.id
  }
  store.setViewMode('shelf')
}

function scrollToBelowFold() {
  belowFoldRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function handleLaunchClick() {
  if (!game.value) return
  const exePath = (game.value.media?.exe_path || '').trim()
  const hasCliArgs =
    game.value.media?.launch_mode === 'cli' && Boolean((game.value.media?.launch_args || '').trim())
  if (!exePath && !hasCliArgs) {
    showBindExeModal.value = true
    return
  }
  void store.launchGame(game.value.id)
}

async function handleSyncBangumi() {
  if (!game.value || syncingBangumi.value) return
  syncingBangumi.value = true
  try {
    const res = await gamesApi.syncBangumi(game.value.id)
    store.notify(`已同步至 Bangumi · ${res.bangumi_type_label}`, 'success')
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.code === 'MISSING_BANGUMI_TOKEN') {
        store.notify('尚未配置 Bangumi Access Token', 'warning', 5000, {
          label: '前往设置',
          onClick: () => store.openSettings('sources', 'bangumi'),
        })
        return
      }
      if (err.code === 'MISSING_BANGUMI_ID') {
        showBangumiBindModal.value = true
        return
      }
    }
    store.notify(err instanceof Error ? err.message : '同步至 Bangumi 失败', 'error')
  } finally {
    syncingBangumi.value = false
  }
}
</script>

<template>
  <!-- 游戏全屏沉浸详情页 -->
  <main v-if="game" class="detail-root">
    <!-- 清晰主视觉背景 + 电影级两段非线性暗角 + 极微弱胶片噪点 -->
    <div class="ambient-backdrop">
      <Transition name="bg-fade" mode="out-in">
        <div
          :key="`${game.id}-${heroImageUrl}`"
          class="ambient-img-layer"
          :class="{
            'is-cover-fallback': !hasHeroBg,
            'privacy-blur-img': blurred,
          }"
          :style="heroImageUrl ? { backgroundImage: `url('${heroImageUrl}')` } : undefined"
        />
      </Transition>
      <div class="ambient-scrim" />
      <svg class="film-grain" aria-hidden="true">
        <filter id="tsumugi-grain">
          <feTurbulence type="fractalNoise" baseFrequency="0.78" numOctaves="3" stitchTiles="stitch" />
        </filter>
        <rect width="100%" height="100%" filter="url(#tsumugi-grain)" />
      </svg>
    </div>

    <!-- 首屏英雄区（94vh，自然承接下方内容） -->
    <section class="hero-fold">
      <header class="hero-topbar">
        <div class="hero-top-tags">
          <span v-if="displayPlatform" class="micro-tag">{{ displayPlatform }}</span>
          <span v-if="game.is_nsfw" class="micro-tag micro-tag-nsfw">R18</span>
          <span v-if="blurred" class="micro-tag micro-tag-privacy">隐私模式</span>
        </div>

        <button class="shelf-ghost-btn" @click="jumpToShelfFocused">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.75">
            <path d="M4 19h16M6 5h3v14H6zM11 6h3v13h-3zM16 4l3 .8-2.5 14.2-3-.8z" />
          </svg>
          <span>回廊</span>
        </button>
      </header>

      <div class="hero-bottom-row">
        <!-- 左下角：艺术字 Logo / 精致衬线主标题 + 单行元信息 + 高对比操作组 -->
        <div class="hero-left">
          <div class="hero-brand-area">
            <img
              v-if="logoImageUrl"
              v-img-fade
              :src="logoImageUrl"
              :alt="game.title"
              class="hero-logo"
              decoding="async"
            />
            <h1 v-else class="hero-serif-title">{{ game.title }}</h1>
          </div>

          <div
            v-if="logoImageUrl || game.sub_title"
            class="hero-subtitle-row"
            :class="{ 'with-logo': Boolean(logoImageUrl) }"
          >
            <span v-if="logoImageUrl" class="hero-main-caption">{{ game.title }}</span>
            <span v-if="game.sub_title" class="hero-alt-caption">{{ game.sub_title }}</span>
          </div>

          <div class="hero-meta-line">
            <span class="meta-status">
              <span class="status-dot" :class="statusDotClass(game.status)" />
              <span>{{ statusLabelMap[game.status] || game.status }}</span>
            </span>
            <span v-if="game.developer" class="meta-item">{{ game.developer }}</span>
            <span v-if="game.release_date" class="meta-item tabular-nums">{{ game.release_date }}</span>
            <span class="meta-item tabular-nums">{{ formatDurationHuman(displayTotalSeconds) }}</span>
          </div>

          <!-- 核心操作按钮组 -->
          <div class="hero-action-bar">
            <!-- 运行中：沉稳翡翠绿深底 + 呼吸点 + 实时计时 -->
            <button
              v-if="isThisGameRunning"
              class="btn btn-emerald launch-btn running-state"
              disabled
            >
              <span class="live-dot" />
              <span class="tabular-nums">正在游玩 · {{ formatClock(store.running.elapsed_seconds) }}</span>
            </button>

            <!-- 启动主按钮：纯白底 + 墨黑字 -->
            <button
              v-else
              class="btn btn-primary launch-btn"
              :disabled="isAnotherGameRunning"
              @click="handleLaunchClick"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                <path d="M7.5 5.25v13.5l11-6.75-11-6.75z" />
              </svg>
              <span>
                {{
                  isAnotherGameRunning
                    ? `《${store.running.title}》运行中`
                    : '开始游戏'
                }}
              </span>
            </button>

            <!-- 手动结束落盘按钮 -->
            <button
              v-if="isThisGameRunning"
              class="btn btn-danger stop-btn"
              @click="store.stopRunningGame(false)"
            >
              {{ store.running.is_mock ? '模拟结束并落盘' : '结束计时' }}
            </button>

            <!-- 无边框磨砂进度切换 -->
            <div class="status-select-wrap">
              <select
                :value="game.status"
                class="hero-status-select"
                aria-label="切换攻略进度"
                @change="handleStatusChange"
              >
                <option value="todo">未开始</option>
                <option value="playing">攻略中</option>
                <option value="done">已通关</option>
              </select>
              <svg class="select-chevron" viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8">
                <path d="M4 6l4 4 4-4" />
              </svg>
            </div>

            <!-- 圆形半透明图标次按钮：编辑资料 -->
            <button
              class="hero-circle-btn"
              title="编辑元数据、资产与启动配置"
              @click="store.showEditModal = true"
            >
              <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8">
                <circle cx="12" cy="12" r="3" />
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.26.6.85 1 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
              </svg>
            </button>

            <!-- 圆形半透明图标次按钮：重新刮削 -->
            <button
              class="hero-circle-btn"
              :disabled="refreshingMeta"
              title="重新多源刮削刷新（自动跳过已锁定字段）"
              @click="handleRefreshMeta"
            >
              <svg
                viewBox="0 0 24 24"
                width="16"
                height="16"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                :class="{ spinning: refreshingMeta }"
              >
                <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
                <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
                <path d="M16 16h5v5" />
              </svg>
            </button>

            <!-- 克制次按钮：单向同步进度至 Bangumi -->
            <button
              class="hero-bgm-btn"
              :disabled="syncingBangumi"
              :title="`上传为「${bangumiTargetLabel}」至 Bangumi`"
              @click="handleSyncBangumi"
            >
              <svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7">
                <path d="M10 13.5V4.5M6.5 8L10 4.5 13.5 8" stroke-linecap="round" stroke-linejoin="round" />
                <path d="M4 13.5v1.5a1.5 1.5 0 0 0 1.5 1.5h9a1.5 1.5 0 0 0 1.5-1.5v-1.5" stroke-linecap="round" />
              </svg>
              <span>{{ syncingBangumi ? '同步中…' : '同步至 Bangumi' }}</span>
            </button>
          </div>
        </div>

        <!-- 右下角：实体收藏盒悬浮封面卡片（点击切换回廊并聚焦本作） -->
        <button
          class="floating-cover-card"
          title="在回廊中查看本作"
          @click="jumpToShelfFocused"
        >
          <div class="cover-hinge-line" />
          <img
            v-if="coverImageUrl"
            v-img-fade
            :src="coverImageUrl"
            :alt="game.title"
            :class="{ 'privacy-blur-img': blurred }"
            decoding="async"
          />
          <div v-else class="cover-fallback">
            <span>{{ game.title }}</span>
          </div>
          <div class="cover-gloss" />
          <div class="cover-sweep" />
          <div class="cover-hover-tip">回廊 ↗</div>
        </button>
      </div>

      <!-- 极克制微动向下小箭头（无文案） -->
      <button class="scroll-chevron-btn" aria-label="向下滚动" @click="scrollToBelowFold">
        <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M5.5 7.5L10 12l4.5-4.5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
    </section>

    <!-- 下滚双栏内容区（左 72% / 右 28%），无缝承接 #0a0a0c 画布 -->
    <section ref="belowFoldRef" class="below-fold">
      <div class="col-left">
        <!-- ① 优先媒体区：本地 PV 播放器 + 下载进度条 + 截图/CG 画廊 -->
        <div
          v-if="game.media?.pv_url_or_path || showPvTaskBar || screenshots.length > 0"
          class="section-stack"
        >
          <!-- PV 后台下载进度条 -->
          <div
            v-if="showPvTaskBar && pvTask"
            class="pv-task-card"
            :class="{ error: pvTask.status === 'error' }"
          >
            <div class="pv-task-top">
              <span class="pv-task-label">
                <template v-if="pvTask.status === 'error'">
                  {{ pvTask.message || '宣传片下载失败' }}
                </template>
                <template v-else>
                  正在下载宣传片
                  <span v-if="pvTask.progress != null" class="tabular-nums">{{ pvTask.progress }}%</span>
                </template>
              </span>
              <div class="pv-task-actions">
                <button
                  v-if="pvTask.status === 'error' && taskStore.canRetryPv(game.id)"
                  type="button"
                  class="btn btn-sm"
                  @click="taskStore.retryPvDownload(game.id)"
                >
                  重试
                </button>
                <button
                  v-if="pvTask.status === 'error'"
                  type="button"
                  class="btn btn-sm btn-ghost"
                  @click="taskStore.dismissTask(game.id, 'pv')"
                >
                  忽略
                </button>
              </div>
            </div>
            <div v-if="pvTask.status !== 'error'" class="pv-progress-track">
              <div
                class="pv-progress-fill"
                :class="{ indeterminate: pvTask.progress == null }"
                :style="pvTask.progress != null ? { width: `${pvTask.progress}%` } : undefined"
              />
            </div>
          </div>

          <LocalVideoPlayer
            v-if="game.media?.pv_url_or_path"
            :src="game.media.pv_url_or_path"
            :poster="heroImageUrl"
            :blurred="blurred"
            :cache-bust="store.assetVersion"
          />

          <div v-if="screenshots.length > 0" class="content-block">
            <div class="block-header">
              <h3>
                截图与画廊
                <span class="header-count tabular-nums">{{ screenshots.length }}</span>
              </h3>
              <button class="btn btn-sm btn-ghost" @click="openFolder('screenshot')">
                打开目录 ↗
              </button>
            </div>
            <div class="gallery-grid">
              <button
                v-for="(ss, idx) in screenshots"
                :key="ss.path"
                class="gallery-tile"
                @click="lightboxIndex = idx"
              >
                <img
                  v-img-fade
                  :src="thumbUrl(ss.path, 420)"
                  :alt="ss.name"
                  :class="{ 'privacy-blur-img': blurred }"
                  loading="lazy"
                  decoding="async"
                />
              </button>
            </div>
          </div>
        </div>

        <!-- ② 剧情简介 -->
        <div class="content-block">
          <div class="block-header">
            <h3>剧情简介</h3>
            <button
              v-if="(game.synopsis || '').length > 180"
              class="text-toggle-btn"
              @click="synopsisExpanded = !synopsisExpanded"
            >
              {{ synopsisExpanded ? '收起' : '展开全文' }}
            </button>
          </div>
          <p class="synopsis-body" :class="{ clamped: !synopsisExpanded }">
            {{ game.synopsis || '暂无剧情简介，可点击上方编辑按钮补充或重新刮削。' }}
          </p>
        </div>

        <!-- ③ 游玩统计与本地目录 / 存档工具 -->
        <div class="content-block">
          <div class="block-header">
            <h3>游玩记录与存档管理</h3>
            <span class="subtle-meta tabular-nums">
              最近游玩 {{ formatDateTime(game.play_record?.last_played_at) }}
            </span>
          </div>

          <div class="play-metrics-grid">
            <div class="metric-tile">
              <div class="metric-label">累计时长</div>
              <div class="metric-value tabular-nums">{{ formatDurationHuman(displayTotalSeconds) }}</div>
              <div class="metric-sub tabular-nums">{{ formatClock(displayTotalSeconds) }}</div>
            </div>
            <div class="metric-tile">
              <div class="metric-label">游玩次数</div>
              <div class="metric-value tabular-nums">{{ sessions.length }} 次</div>
              <button
                v-if="sessions.length > 0"
                class="metric-link"
                @click="showSessions = !showSessions"
              >
                {{ showSessions ? '收起明细' : '查看明细' }}
              </button>
            </div>
            <div class="metric-tile">
              <div class="metric-label">存档快照</div>
              <div class="metric-value tabular-nums">{{ backups.length }} 份</div>
              <button
                v-if="backups.length > 0"
                class="metric-link"
                @click="showBackups = !showBackups"
              >
                {{ showBackups ? '收起快照' : '管理快照' }}
              </button>
            </div>
          </div>

          <div class="ops-bar">
            <button class="btn btn-sm" @click="openFolder('save')">存档目录</button>
            <button class="btn btn-sm" @click="openFolder('screenshot')">截图目录</button>
            <button class="btn btn-sm" @click="openFolder('game')">安装目录</button>
            <button
              class="btn btn-sm backup-btn"
              :disabled="creatingBackup"
              @click="createSnapshotBackup"
            >
              {{ creatingBackup ? '正在打包…' : '创建存档快照 (.zip)' }}
            </button>
          </div>

          <!-- 游玩明细抽屉 -->
          <div v-if="showSessions && sessions.length > 0" class="sub-drawer">
            <div class="sub-drawer-title">最近游玩会话</div>
            <div v-for="s in sessions" :key="s.id" class="sub-row">
              <span class="tabular-nums">{{ formatDateTime(s.started_at) }}</span>
              <span class="mono-dim tabular-nums">
                {{ formatClock(s.duration_seconds) }} · {{ formatDurationHuman(s.duration_seconds) }}
              </span>
            </div>
          </div>

          <!-- 存档备份快照列表 -->
          <div v-if="showBackups && backups.length > 0" class="sub-drawer">
            <div class="sub-drawer-title tabular-nums">本地快照仓库 · ./data/backups/{{ game.id }}/</div>
            <div v-for="bk in backups" :key="bk.filename" class="sub-row">
              <div class="bk-info">
                <strong class="mono-name tabular-nums">{{ bk.filename }}</strong>
                <span class="subtle-meta tabular-nums">
                  {{ formatDateTime(bk.created_at) }} · {{ formatBytes(bk.size_bytes) }}
                </span>
              </div>
              <div class="bk-actions">
                <button class="btn btn-sm" @click="restoreBackup(bk.filename)">恢复</button>
                <button class="btn btn-danger btn-sm" @click="deleteBackup(bk.filename)">删除</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右栏 28%：作品档案 + 实体盒规格 + 标签 -->
      <aside class="col-right">
        <div class="content-block info-card">
          <h3>作品档案</h3>

          <dl class="meta-list">
            <div class="meta-row">
              <dt>开发商</dt>
              <dd>{{ game.developer || '—' }}</dd>
            </div>
            <div class="meta-row">
              <dt>发行商</dt>
              <dd>{{ game.publisher || '—' }}</dd>
            </div>
            <div class="meta-row">
              <dt>发售日期</dt>
              <dd class="tabular-nums">{{ game.release_date || '—' }}</dd>
            </div>
            <div class="meta-row">
              <dt>平台</dt>
              <dd>
                <span v-if="displayPlatform" class="mini-badge">{{ displayPlatform }}</span>
                <span v-else>—</span>
              </dd>
            </div>
            <div class="meta-row">
              <dt>启动方式</dt>
              <dd>{{ launchModeLabelMap[game.media?.launch_mode || 'direct'] || game.media?.launch_mode }}</dd>
            </div>
            <div class="meta-row">
              <dt>拼音索引</dt>
              <dd class="mono-dim">{{ game.pinyin_initials || '—' }}</dd>
            </div>
          </dl>

          <div v-if="(game.locked_fields || []).length > 0" class="locked-summary">
            <span class="sub-label">已锁定字段</span>
            <div class="locked-pills">
              <span v-for="f in game.locked_fields" :key="f">{{ f }}</span>
            </div>
          </div>

          <div class="divider" />

          <!-- 标签云 -->
          <div class="tags-block">
            <div class="sub-label">标签</div>
            <div v-if="(game.tags || []).length > 0" class="tag-cloud">
              <button
                v-for="tag in game.tags"
                :key="tag"
                class="cloud-tag"
                @click="jumpByTag(tag)"
              >
                {{ tag }}
              </button>
            </div>
            <div v-else class="subtle-meta">暂无标签</div>
          </div>
        </div>
      </aside>
    </section>

    <!-- 原图灯箱 -->
    <LightboxModal
      v-if="lightboxIndex !== null"
      :items="screenshots"
      :initial-index="lightboxIndex"
      @close="lightboxIndex = null"
    />

    <!-- 未绑定启动程序引导弹窗 -->
    <Transition name="modal-pop">
      <BindExeModal
        v-if="showBindExeModal && game"
        :game="game"
        @close="showBindExeModal = false"
      />
    </Transition>

    <!-- 关联 Bangumi 条目小窗 -->
    <Transition name="modal-pop">
      <BangumiBindModal
        v-if="showBangumiBindModal && game"
        :game="game"
        @close="showBangumiBindModal = false"
        @synced="showBangumiBindModal = false"
      />
    </Transition>

    <!-- 详情页留声机原声浮条（仅当绑定了 bgm_path 时轻盈浮现） -->
    <Transition name="fade">
      <div v-if="game.media?.bgm_path" class="detail-phono-dock">
        <PhonographPill :game="game" />
      </div>
    </Transition>
  </main>
</template>

<style scoped>
/* Detail Root */
.detail-root {
  position: relative;
  min-height: 100vh;
  background: var(--bg-canvas);
}

/* Clear Hero Backdrop + Dual Nonlinear Cinematic Scrim + Subtle Film Grain */
.ambient-backdrop {
  position: fixed;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  background: var(--bg-canvas);
}

.ambient-img-layer {
  position: absolute;
  inset: -16px;
  background-size: cover;
  background-position: center 20%;
  filter: brightness(0.92) saturate(1.04);
  transform: scale(1.01);
  transition: filter 0.45s var(--ease-out-expo);
}

/* 仅当完全缺失宽幅 Hero 图而使用竖版封面兜底时，施加极轻度柔化 */
.ambient-img-layer.is-cover-fallback {
  filter: blur(12px) brightness(0.76) saturate(1.06);
  transform: scale(1.06);
}

.ambient-scrim {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(
      to top,
      #0a0a0c 0%,
      rgba(10, 10, 12, 0.88) 18%,
      rgba(10, 10, 12, 0.35) 48%,
      rgba(10, 10, 12, 0.12) 100%
    ),
    linear-gradient(
      to right,
      rgba(10, 10, 12, 0.78) 0%,
      rgba(10, 10, 12, 0.28) 42%,
      transparent 78%
    );
  pointer-events: none;
}

.film-grain {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0.025;
  pointer-events: none;
}

/* Hero Fold (94vh) */
.hero-fold {
  position: relative;
  z-index: 2;
  min-height: 94vh;
  padding: calc(28px + var(--titlebar-safe-top, 0px)) 64px 20px 76px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.hero-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.hero-top-tags {
  display: flex;
  align-items: center;
  gap: 8px;
}

.micro-tag {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.08em;
  padding: 4px 10px;
  border-radius: 7px;
  background: rgba(10, 10, 12, 0.42);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: rgba(244, 244, 245, 0.9);
}

.micro-tag-nsfw {
  background: rgba(127, 29, 29, 0.56);
  border-color: rgba(252, 165, 165, 0.22);
  color: #fecaca;
}

.micro-tag-privacy {
  background: rgba(120, 53, 15, 0.56);
  border-color: rgba(252, 211, 77, 0.22);
  color: var(--amber-text);
}

/* 顶部返回回廊亚克力按钮（浅色/深色 Hero 背景均可清晰辨识） */
.shelf-ghost-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 14px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 999px;
  background: rgba(10, 10, 12, 0.42);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.02em;
  opacity: 0.92;
  transition:
    opacity var(--duration-base) var(--ease-out-expo),
    background-color var(--duration-base) var(--ease-out-expo),
    border-color var(--duration-base) var(--ease-out-expo);
}

.shelf-ghost-btn:hover {
  opacity: 1;
  background: rgba(18, 18, 22, 0.68);
  border-color: rgba(255, 255, 255, 0.16);
}

.hero-bottom-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 48px;
  margin-top: auto;
  padding-bottom: 12px;
}

.hero-left {
  flex: 1;
  min-width: 0;
  max-width: 820px;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.hero-brand-area {
  display: flex;
  align-items: flex-end;
}

.hero-logo {
  display: block;
  max-height: clamp(96px, 11vh, 136px);
  max-width: clamp(280px, 32vw, 460px);
  width: auto;
  height: auto;
  object-fit: contain;
  object-position: left bottom;
  filter: drop-shadow(0 6px 20px rgba(0, 0, 0, 0.65));
}

.hero-serif-title {
  margin: 0;
  font-family: var(--font-serif);
  font-size: clamp(36px, 3.4vw, 52px);
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: 0.03em;
  color: var(--text-primary);
  text-shadow: 0 4px 28px rgba(0, 0, 0, 0.65);
}

.hero-subtitle-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 14px;
  margin-top: 10px;
}

.hero-subtitle-row.with-logo {
  margin-top: 14px;
}

.hero-main-caption {
  font-size: clamp(22px, 1.8vw, 28px);
  font-weight: 600;
  letter-spacing: 0.02em;
  line-height: 1.25;
  color: var(--text-primary);
  text-shadow: 0 2px 18px rgba(0, 0, 0, 0.65);
}

.hero-alt-caption {
  font-size: clamp(16px, 1.15vw, 18px);
  color: var(--text-secondary);
  text-shadow: 0 2px 12px rgba(0, 0, 0, 0.58);
}

.hero-subtitle-row.with-logo .hero-alt-caption {
  font-size: 14.5px;
}

/* Single Clean Metadata Line */
.hero-meta-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  font-size: 13.5px;
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
}

.meta-status {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--text-primary);
  font-weight: 500;
}

.meta-item::before {
  content: '·';
  margin-right: 10px;
  color: rgba(255, 255, 255, 0.28);
}

/* Hero Action Controls */
.hero-action-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-top: 20px;
}

.launch-btn {
  padding: 13px 28px;
  font-size: 14.5px;
  border-radius: 999px;
}

.running-state {
  opacity: 1 !important;
  cursor: default !important;
}

.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--emerald);
  animation: dot-breathe 2.2s var(--ease-out-expo) infinite;
}

.stop-btn {
  padding: 12px 18px;
  border-radius: 999px;
}

.status-select-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.hero-status-select {
  appearance: none;
  -webkit-appearance: none;
  padding: 12px 34px 12px 16px;
  border-radius: 999px;
  border: none;
  background: rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  color: var(--text-primary);
  font-size: 13.5px;
  font-weight: 500;
  outline: none;
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.hero-status-select:hover,
.hero-status-select:focus {
  background: rgba(255, 255, 255, 0.14);
}

.select-chevron {
  position: absolute;
  right: 13px;
  color: var(--text-secondary);
  pointer-events: none;
}

.hero-circle-btn {
  width: 44px;
  height: 44px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  color: var(--text-primary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    transform var(--duration-fast) var(--ease-out-expo);
}

.hero-circle-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.16);
  transform: translateY(-1px);
}

.hero-circle-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* Bottom-Right Physical Collector Cover Card */
.floating-cover-card {
  position: relative;
  width: 196px;
  height: 278px;
  border-radius: 8px 12px 12px 8px;
  overflow: hidden;
  border: none;
  background: #141418;
  padding: 0;
  flex-shrink: 0;
  box-shadow: var(--shadow-cover);
  transform: perspective(950px) rotateY(-8deg) rotateX(1.5deg);
  transition:
    transform 0.46s var(--ease-out-expo),
    box-shadow 0.46s var(--ease-out-expo);
}

.floating-cover-card:hover {
  transform: perspective(950px) rotateY(-1deg) translateY(-8px) scale(1.03);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.38),
    0 32px 68px rgba(0, 0, 0, 0.82);
}

.floating-cover-card img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.cover-hinge-line {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 10px;
  width: 3px;
  background: linear-gradient(
    90deg,
    rgba(0, 0, 0, 0.45),
    rgba(255, 255, 255, 0.24),
    rgba(0, 0, 0, 0.3)
  );
  z-index: 3;
}

.cover-gloss {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    130deg,
    rgba(255, 255, 255, 0.2) 0%,
    rgba(255, 255, 255, 0.04) 28%,
    transparent 52%,
    rgba(255, 255, 255, 0.06) 100%
  );
  pointer-events: none;
  z-index: 2;
}

.cover-sweep {
  position: absolute;
  inset: -40%;
  background: linear-gradient(
    115deg,
    transparent 38%,
    rgba(255, 255, 255, 0.22) 50%,
    transparent 62%
  );
  transform: translateX(-120%);
  transition: transform 0.72s var(--ease-out-expo);
  pointer-events: none;
  z-index: 3;
}

.floating-cover-card:hover .cover-sweep {
  transform: translateX(120%);
}

.cover-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 18px;
  font-family: var(--font-serif);
  font-size: 18px;
  text-align: center;
  color: var(--text-secondary);
  background: linear-gradient(155deg, #1b1b20, #0d0d10);
}

.cover-hover-tip {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 12px 10px 10px;
  background: linear-gradient(180deg, transparent, rgba(10, 10, 12, 0.88));
  font-size: 11.5px;
  font-weight: 500;
  letter-spacing: 0.04em;
  color: var(--text-primary);
  text-align: center;
  opacity: 0;
  transition: opacity var(--duration-base) var(--ease-out-expo);
  z-index: 4;
}

.floating-cover-card:hover .cover-hover-tip {
  opacity: 1;
}

/* Whisper-quiet downward chevron */
.scroll-chevron-btn {
  align-self: center;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 24px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--text-primary);
  opacity: 0.24;
  animation: chevron-float 2.8s ease-in-out infinite;
  transition: opacity var(--duration-fast) var(--ease-out-expo);
}

.scroll-chevron-btn:hover {
  opacity: 0.72;
}

/* Below the fold: 72% / 28% seamlessly continuing #0a0a0c */
.below-fold {
  position: relative;
  z-index: 2;
  background: linear-gradient(to bottom, rgba(10, 10, 12, 0) 0%, #0a0a0c 56px);
  padding: 36px 64px 96px 76px;
  display: grid;
  grid-template-columns: minmax(0, 72fr) minmax(268px, 28fr);
  gap: 32px;
  align-items: start;
}

.col-left,
.section-stack {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

/* Ultra-restrained surface blocks (no harsh borders) */
.content-block {
  padding: 26px 28px;
  border-radius: var(--radius-lg);
  background: var(--bg-surface-subtle);
  box-shadow: inset 0 1px 0 var(--divider-subtle);
}

.block-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 18px;
}

.block-header h3,
.info-card h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--text-primary);
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.header-count {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-muted);
}

.subtle-meta {
  font-size: 12px;
  color: var(--text-muted);
}

/* Gallery Grid */
.gallery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 12px;
}

.gallery-tile {
  position: relative;
  aspect-ratio: 16 / 9;
  border-radius: 10px;
  overflow: hidden;
  border: none;
  background: var(--bg-surface);
  padding: 0;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.32);
}

.gallery-tile img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.42s var(--ease-out-expo);
}

.gallery-tile:hover img {
  transform: scale(1.045);
}

/* Editorial Synopsis */
.synopsis-body {
  margin: 0;
  max-width: 72ch;
  font-size: 14.5px;
  line-height: 1.85;
  color: var(--text-secondary);
  white-space: pre-line;
}

.synopsis-body.clamped {
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.text-toggle-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 12.5px;
  padding: 0;
  transition: color var(--duration-fast) var(--ease-out-expo);
}

.text-toggle-btn:hover {
  color: var(--text-primary);
}

/* Metrics & Local Tools */
.play-metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-bottom: 20px;
}

.metric-tile {
  padding: 16px 18px;
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.025);
}

.metric-label {
  font-size: 11.5px;
  color: var(--text-muted);
}

.metric-value {
  margin-top: 6px;
  font-size: 21px;
  font-weight: 600;
  color: var(--text-primary);
}

.metric-sub {
  margin-top: 3px;
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-muted);
}

.metric-link {
  margin-top: 6px;
  background: none;
  border: none;
  padding: 0;
  font-size: 12px;
  color: var(--text-secondary);
  transition: color var(--duration-fast) var(--ease-out-expo);
}

.metric-link:hover {
  color: var(--text-primary);
}

.ops-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.backup-btn {
  background: rgba(255, 255, 255, 0.12);
  color: var(--text-primary);
}

.backup-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.18);
}

/* Sub Drawers */
.sub-drawer {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--divider-subtle);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sub-drawer-title {
  font-size: 11.5px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.sub-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.025);
  font-size: 12.5px;
  color: var(--text-secondary);
}

.mono-name {
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--text-primary);
}

.mono-dim {
  font-family: var(--font-mono);
  color: var(--text-muted);
}

.bk-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.bk-actions {
  display: flex;
  gap: 6px;
}

/* Right Column Archive Card */
.info-card {
  position: sticky;
  top: 28px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.meta-list {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 14px;
  font-size: 13px;
}

.meta-row dt {
  color: var(--text-muted);
  flex-shrink: 0;
}

.meta-row dd {
  margin: 0;
  text-align: right;
  color: var(--text-primary);
  word-break: break-word;
}

.mini-badge {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.07);
  color: var(--text-primary);
}

.divider {
  height: 1px;
  background: var(--divider-subtle);
}

.sub-label {
  font-size: 11.5px;
  color: var(--text-muted);
  margin-bottom: 10px;
  display: block;
}

.edition-toggle {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  padding: 3px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
}

.edition-toggle button {
  padding: 7px 6px;
  border-radius: 8px;
  border: none;
  background: transparent;
  font-size: 12px;
  color: var(--text-secondary);
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.edition-toggle button:hover {
  color: var(--text-primary);
}

.edition-toggle button.active {
  background: rgba(255, 255, 255, 0.13);
  color: #ffffff;
  font-weight: 500;
}

.locked-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.locked-pills span {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 6px;
  background: var(--amber-bg);
  color: var(--amber-text);
}

.tag-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.cloud-tag {
  padding: 5px 10px;
  border-radius: 7px;
  border: none;
  background: rgba(255, 255, 255, 0.05);
  font-size: 12px;
  color: var(--text-secondary);
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.cloud-tag:hover {
  background: rgba(255, 255, 255, 0.12);
  color: var(--text-primary);
}

.spinning {
  animation: slow-spin 0.9s linear infinite;
}

.detail-phono-dock {
  position: fixed;
  right: 28px;
  bottom: 24px;
  z-index: 40;
}

/* Bangumi 单向推送克制按钮 */
.hero-bgm-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 44px;
  padding: 0 14px;
  border: none;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  color: rgba(244, 244, 245, 0.88);
  font-size: 12.5px;
  font-weight: 500;
  white-space: nowrap;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo),
    transform var(--duration-fast) var(--ease-out-expo);
}

.hero-bgm-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.16);
  color: #ffffff;
}

.hero-bgm-btn:disabled {
  opacity: 0.48;
  cursor: wait;
}

/* PV 后台下载进度条卡片 */
.pv-task-card {
  padding: 12px 16px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.035);
  border: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.pv-task-card.error {
  border-color: rgba(248, 113, 113, 0.24);
  background: rgba(248, 113, 113, 0.06);
}

.pv-task-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.pv-task-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text-secondary);
}

.pv-task-card.error .pv-task-label {
  color: var(--danger-text);
}

.pv-task-actions {
  display: inline-flex;
  gap: 6px;
  flex-shrink: 0;
}

.pv-progress-track {
  position: relative;
  height: 3px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}

.pv-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: #f5f5f7;
  transition: width 260ms var(--ease-out-expo);
}

.pv-progress-fill.indeterminate {
  width: 34%;
  animation: pv-indet 1.2s ease-in-out infinite;
}

@keyframes pv-indet {
  0% {
    transform: translateX(-110%);
  }
  100% {
    transform: translateX(320%);
  }
}

/* 标签行边缘微羽化，防止横向溢出硬截断 */
.hero-top-tags {
  max-width: 72vw;
  overflow-x: auto;
  scrollbar-width: none;
  -webkit-mask-image: linear-gradient(90deg, #000 92%, transparent 100%);
  mask-image: linear-gradient(90deg, #000 92%, transparent 100%);
}

.hero-top-tags::-webkit-scrollbar {
  display: none;
}

@keyframes slow-spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes dot-breathe {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.45;
    transform: scale(0.82);
  }
}

@keyframes chevron-float {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(4px);
  }
}

@media (max-width: 980px) {
  .hero-fold {
    padding: 24px 24px 20px;
  }
  .below-fold {
    grid-template-columns: 1fr;
    padding: 28px 24px 72px;
  }
  .floating-cover-card {
    display: none;
  }
  .play-metrics-grid {
    grid-template-columns: 1fr;
  }
}
</style>
