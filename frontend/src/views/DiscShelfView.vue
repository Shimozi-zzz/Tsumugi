<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { assetUrl, fallbackToOriginalImage, mediaApi, mediaThumbUrl, thumbUrl } from '@/api/client'
import BindExeModal from '@/components/BindExeModal.vue'
import PhonographPill from '@/components/PhonographPill.vue'
import SeriesCollectionsPanel from '@/components/SeriesCollectionsPanel.vue'
import { useAudioStore } from '@/stores/audio'
import { useLibraryStore } from '@/stores/library'
import type { ActiveStatusFilter, Game, LibrarySortBy } from '@/types'
import { getSpinePlatformBadge } from '@/utils/platform'
import { getSortOption, SORT_OPTIONS } from '@/utils/sortGames'

const store = useLibraryStore()
const audio = useAudioStore()

const gamesList = computed(() => store.filteredGames)
const galleryTab = ref<'works' | 'collections'>('works')
const activeIndex = ref(0)
const showBindExeModal = ref(false)
const colDropdownOpen = ref(false)
const sortDropdownOpen = ref(false)

function browseCollectionInShelf(collectionId: number) {
  store.setActiveCollection(collectionId)
  galleryTab.value = 'works'
}

const activeSortOption = computed(() => getSortOption(store.sortBy))

function pickSortMode(key: LibrarySortBy) {
  store.setSort(key)
  sortDropdownOpen.value = false
}

function flipSortOrder() {
  store.toggleSortOrder()
  sortDropdownOpen.value = false
}

// 二段式物理出盘状态机
const pulledGameId = ref<number | null>(null)
const ejectedGameId = ref<number | null>(null)

// 鼠标 3D 视差重力偏转与高光扫射（严格仅作用于当前已选中且转正的盒子）
const tiltX = ref(0)
const tiltY = ref(0)
const glareX = ref(50)
const glareY = ref(35)

// 联动氛围墙截图兜底缓存
const linkedScreenshotMap = ref<Record<number, string>>({})

// 浮游光尘粒子 Canvas
const particleCanvasRef = ref<HTMLCanvasElement | null>(null)
let particleRaf: number | null = null

let retractTimer: number | null = null
let ejectTimer: number | null = null
let wheelLock = false

function clearChoreographyTimers() {
  if (retractTimer !== null) {
    clearTimeout(retractTimer)
    retractTimer = null
  }
  if (ejectTimer !== null) {
    clearTimeout(ejectTimer)
    ejectTimer = null
  }
}

const currentGame = computed<Game | null>(() => gamesList.value[activeIndex.value] || null)

const isCurrentRunning = computed(
  () => Boolean(currentGame.value && store.running.running && store.running.game_id === currentGame.value.id),
)

const activeCollectionLabel = computed(() => store.activeCollection?.name || '全部')

const currentGameSeriesTag = computed<string>(() => {
  const g = currentGame.value
  if (!g || store.collections.length === 0) return ''
  let targetCol = store.activeCollection
  if (!targetCol) {
    const orderedCols = [...store.collections].sort((a, b) => {
      const aSeries = a.collection_type !== 'custom' ? 0 : 1
      const bSeries = b.collection_type !== 'custom' ? 0 : 1
      if (aSeries !== bSeries) return aSeries - bSeries
      if ((a.sort_order ?? 0) !== (b.sort_order ?? 0)) {
        return (a.sort_order ?? 0) - (b.sort_order ?? 0)
      }
      return a.id - b.id
    })
    targetCol =
      orderedCols.find(
        (c) => (c.items || []).some((it) => it.game_id === g.id) || (c.game_ids || []).includes(g.id),
      ) || null
  }
  if (!targetCol) return ''

  const orderedItems =
    targetCol.items && targetCol.items.length > 0
      ? [...targetCol.items].sort((x, y) => (x.position ?? 0) - (y.position ?? 0))
      : []
  let idx = orderedItems.findIndex((it) => it.game_id === g.id)
  let total = orderedItems.length
  let relLabel = idx >= 0 ? (orderedItems[idx].relation_label || '').trim() : ''

  if (idx < 0) {
    const ids = targetCol.game_ids || []
    idx = ids.indexOf(g.id)
    total = ids.length
  }
  if (idx < 0 || total <= 0) return ''
  return relLabel
    ? `${targetCol.name} · ${relLabel} · ${idx + 1}/${total}`
    : `${targetCol.name} · ${idx + 1}/${total}`
})

const watermarkText = computed(() => {
  const g = currentGame.value
  if (!g) return ''
  return (g.sub_title || g.title || '').trim()
})

const releaseYear = computed(() => {
  const raw = (currentGame.value?.release_date || '').trim()
  const match = raw.match(/\d{4}/)
  return match ? match[0] : ''
})

const currentPlaySeconds = computed(() => {
  const g = currentGame.value
  if (!g) return 0
  if (isCurrentRunning.value) return store.running.total_seconds
  return g.play_record?.total_seconds || 0
})

function formatPlayDuration(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  if (s === 0) return '尚未启程'
  if (s < 60) return `${s} 秒`
  const mins = Math.floor(s / 60)
  if (mins < 60) return `${mins} 分钟`
  return `${(s / 3600).toFixed(1)} 小时`
}

const poeticExcerpt = computed(() => {
  const raw = (currentGame.value?.synopsis || '').replace(/\s+/g, ' ').trim()
  if (!raw) return ''
  // 截取前 1~2 句诗意引言
  const sentences = raw.match(/[^。！？.!?]+[。！？.!?]?/g)
  if (!sentences || sentences.length === 0) return raw.slice(0, 96)
  const joined = sentences.slice(0, 2).join('').trim()
  return joined.length > 110 ? `${joined.slice(0, 108)}…` : joined
})

const statusFilterTabs: { key: ActiveStatusFilter; label: string; dotClass?: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'playing', label: '攻略中', dotClass: 'status-dot-playing' },
  { key: 'unplayed', label: '未开始', dotClass: 'status-dot-todo' },
  { key: 'completed', label: '已通关', dotClass: 'status-dot-done' },
]

function resetGalleryFilters() {
  store.setActiveStatus('all')
  store.setFilterTag('')
  if (store.activeCollectionId !== null && store.filteredGames.length === 0) {
    store.setActiveCollection(null)
  }
}

function statusDotClass(status: string): string {
  if (status === 'playing') return 'status-dot-playing'
  if (status === 'done' || status === 'completed') return 'status-dot-done'
  return 'status-dot-todo'
}

// 滑动窗口虚拟渲染：仅挂载 Math.abs(index - activeIndex) <= 7（最多 15 个 3D 盒体）
const visibleCases = computed(() => {
  const list = gamesList.value
  const total = list.length
  if (total === 0) return []
  const start = Math.max(0, activeIndex.value - 7)
  const end = Math.min(total - 1, activeIndex.value + 7)
  const windowItems: { game: Game; index: number; offset: number }[] = []
  for (let i = start; i <= end; i++) {
    windowItems.push({
      game: list[i],
      index: i,
      offset: i - activeIndex.value,
    })
  }
  return windowItems
})

function syncInitialIndex() {
  const list = gamesList.value
  if (list.length === 0) {
    activeIndex.value = 0
    pulledGameId.value = null
    ejectedGameId.value = null
    return
  }
  const idx = list.findIndex((g) => g.id === store.activeGameId)
  const nextIdx = idx >= 0 ? idx : 0
  const targetId = list[nextIdx].id
  activeIndex.value = nextIdx
  // 若排序切换后仍是同一张选中盘，仅平滑调整槽位索引，避免重复收盘/出盘
  if (pulledGameId.value === targetId) {
    return
  }
  triggerSelectChoreography(targetId, true)
}

function triggerSelectChoreography(targetId: number, immediate = false) {
  clearChoreographyTimers()
  const hadEjectedOther = ejectedGameId.value !== null && ejectedGameId.value !== targetId

  if (hadEjectedOther && !immediate) {
    ejectedGameId.value = null
    retractTimer = window.setTimeout(() => {
      pulledGameId.value = targetId
      ejectTimer = window.setTimeout(() => {
        if (pulledGameId.value === targetId) {
          ejectedGameId.value = targetId
        }
      }, 340)
    }, 220)
  } else {
    pulledGameId.value = targetId
    ejectTimer = window.setTimeout(() => {
      if (pulledGameId.value === targetId) {
        ejectedGameId.value = targetId
      }
    }, immediate ? 260 : 340)
  }
}

function selectByIndex(idx: number) {
  const list = gamesList.value
  if (idx < 0 || idx >= list.length) return
  if (idx === activeIndex.value && pulledGameId.value === list[idx].id) return
  activeIndex.value = idx
  const picked = list[idx]
  void store.selectGame(picked.id, { switchToDetail: false, recordActive: true })
  triggerSelectChoreography(picked.id)
}

function handleCaseClick(game: Game, idx: number) {
  if (idx !== activeIndex.value) {
    selectByIndex(idx)
  } else if (ejectedGameId.value !== game.id) {
    triggerSelectChoreography(game.id)
  }
}

function enterDetail(gameId?: number) {
  const id = gameId ?? currentGame.value?.id
  if (id != null) {
    void store.selectGame(id, { switchToDetail: true, recordActive: true })
  }
}

function handleLaunchCurrent() {
  if (!currentGame.value) return
  const exePath = (currentGame.value.media?.exe_path || '').trim()
  const hasCliArgs =
    currentGame.value.media?.launch_mode === 'cli' &&
    Boolean((currentGame.value.media?.launch_args || '').trim())
  if (!exePath && !hasCliArgs) {
    showBindExeModal.value = true
    return
  }
  void store.launchGame(currentGame.value.id)
}

function selectCollectionFromDropdown(collectionId: number | null) {
  store.setActiveCollection(collectionId)
  colDropdownOpen.value = false
}

function openAllWorksTab() {
  galleryTab.value = 'works'
  if (store.activeCollectionId !== null) {
    store.setActiveCollection(null)
  }
  colDropdownOpen.value = false
}

function openNewCollection() {
  colDropdownOpen.value = false
  store.openCreateCollectionModal()
}

function onStageMouseMove(e: MouseEvent) {
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  const nx = (e.clientX - rect.left) / Math.max(rect.width, 1) - 0.5
  const ny = (e.clientY - rect.top) / Math.max(rect.height, 1) - 0.5
  tiltY.value = Number((nx * 16).toFixed(2))
  tiltX.value = Number((-ny * 12).toFixed(2))
  glareX.value = Math.round((nx + 0.5) * 100)
  glareY.value = Math.round((ny + 0.5) * 100)
}

function resetStageTilt() {
  tiltX.value = 0
  tiltY.value = 0
  glareX.value = 50
  glareY.value = 35
}

function isAnyModalOpen(): boolean {
  return (
    showBindExeModal.value ||
    store.showImportModal ||
    store.showEditModal ||
    store.showQuickSearch ||
    store.showSettingsModal ||
    store.showTimeLedger ||
    store.showCollectionModal
  )
}

function isEditableFocused(): boolean {
  const el = document.activeElement as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

function onWheel(e: WheelEvent) {
  if (
    galleryTab.value !== 'works' ||
    colDropdownOpen.value ||
    sortDropdownOpen.value ||
    isAnyModalOpen() ||
    gamesList.value.length <= 1
  ) {
    return
  }
  const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY
  e.preventDefault()
  if (wheelLock || Math.abs(delta) <= 12) return
  wheelLock = true
  if (delta > 0) selectByIndex(Math.min(gamesList.value.length - 1, activeIndex.value + 1))
  else selectByIndex(Math.max(0, activeIndex.value - 1))
  window.setTimeout(() => {
    wheelLock = false
  }, 160)
}

function onKeyDown(e: KeyboardEvent) {
  if (isAnyModalOpen() || isEditableFocused()) return

  if (e.key === 'Escape') {
    e.preventDefault()
    if (colDropdownOpen.value || sortDropdownOpen.value) {
      colDropdownOpen.value = false
      sortDropdownOpen.value = false
    } else if (galleryTab.value === 'collections') {
      galleryTab.value = 'works'
    } else {
      enterDetail()
    }
    return
  }

  if (galleryTab.value !== 'works') return

  if (e.key === 'ArrowRight') {
    e.preventDefault()
    selectByIndex(Math.min(gamesList.value.length - 1, activeIndex.value + 1))
  } else if (e.key === 'ArrowLeft') {
    e.preventDefault()
    selectByIndex(Math.max(0, activeIndex.value - 1))
  } else if (e.key === 'Enter' && currentGame.value) {
    e.preventDefault()
    enterDetail(currentGame.value.id)
  } else if (e.code === 'Space' || e.key === ' ') {
    if (currentGame.value?.media?.bgm_path || currentGame.value?.media?.bgm_remote_url) {
      e.preventDefault()
      void audio.togglePlayForGame(currentGame.value, store.assetVersion)
    }
  }
}

const COLLECTOR_CASE_DEPTH = 46

/**
 * 外层槽位容器 (.disc-slot)：
 * 选中出盘态时，右侧相邻盒体额外增加 64px 平滑让位偏移
 */
function slotPositionStyle(game: Game, offset: number) {
  const isPulled = pulledGameId.value === game.id
  if (isPulled) {
    return {
      '--tx': '-32px',
      '--ty': '-10px',
      '--tz': '165px',
      zIndex: 40,
    }
  }

  const baseGap = 144
  const rightDiscClearance = pulledGameId.value !== null && offset > 0 ? 64 : 0
  const sideGap = baseGap + rightDiscClearance
  const stepX = 72
  const sign = offset < 0 ? -1 : 1
  const absOff = Math.abs(offset)
  const tx = sign * (sideGap + (absOff - 1) * stepX)
  const tz = -absOff * 28

  return {
    '--tx': `${tx}px`,
    '--ty': '8px',
    '--tz': `${tz}px`,
    zIndex: 20 - absOff,
  }
}

/**
 * 内层 3D 六面体 (.disc-box)：
 * 统一按 46px 典藏厚盒渲染；鼠标 3D 视差偏转仅在当前已选中且转正的盒子上生效
 */
function boxRotationStyle(game: Game, offset: number) {
  const isPulled = pulledGameId.value === game.id
  const depth = COLLECTOR_CASE_DEPTH

  if (isPulled) {
    const rx = tiltX.value * 0.75
    const ry = -10 + tiltY.value * 0.85
    return {
      '--d': `${depth}px`,
      '--glare-x': `${glareX.value}%`,
      '--glare-y': `${glareY.value}%`,
      transform: `rotateX(${rx}deg) rotateY(${ry}deg)`,
    }
  }

  const rotY = offset < 0 ? 74 : 68
  return {
    '--d': `${depth}px`,
    '--glare-x': '35%',
    '--glare-y': '30%',
    transform: `rotateY(${rotY}deg)`,
  }
}

function spineBadgeFor(game: Game) {
  return getSpinePlatformBadge(game.source_platform, game.external_ids)
}

function devAbbrev(dev: string): string {
  const clean = (dev || 'LOCAL').trim()
  if (!clean) return 'TSM'
  if (/^[a-zA-Z0-9\s._-]+$/.test(clean)) {
    return clean.replace(/[^a-zA-Z0-9]/g, '').slice(0, 4).toUpperCase() || 'TSM'
  }
  return clean.slice(0, 2)
}

function coverThumb(game: Game): string {
  const m = game.media
  if (!m) return ''
  const raw = m.cover_path || m.cover_thumb_path
  return raw ? mediaThumbUrl(raw, 'sm', store.assetVersion) : ''
}

function coverOriginalUrl(game: Game): string {
  const m = game.media
  if (!m) return ''
  return assetUrl(m.cover_path || m.cover_thumb_path, store.assetVersion)
}

function spineTextureUrl(game: Game): string {
  const m = game.media
  if (!m) return ''
  const raw = m.custom_spine_path || m.cover_path || m.cover_thumb_path
  return raw ? mediaThumbUrl(raw, 'sm', store.assetVersion) : ''
}

// ─────────────── 联动氛围墙背景解析逻辑 ───────────────

async function ensureLinkedFallbackScreenshot(game: Game) {
  if (game.media?.hero_bg_path) return
  if (game.id in linkedScreenshotMap.value) return
  try {
    const res = await mediaApi.screenshots(game.id)
    if (res.items.length > 0) {
      const pick = res.items[Math.floor(Math.random() * res.items.length)]
      linkedScreenshotMap.value = {
        ...linkedScreenshotMap.value,
        [game.id]: thumbUrl(pick.path, 900),
      }
    } else {
      linkedScreenshotMap.value = { ...linkedScreenshotMap.value, [game.id]: '' }
    }
  } catch {
    linkedScreenshotMap.value = { ...linkedScreenshotMap.value, [game.id]: '' }
  }
}

const activeBackdropUrl = computed(() => {
  // 固定联动氛围墙：hero_bg_path → 游戏截图目录随机 1 张 → cover_path
  const g = currentGame.value
  if (!g?.media) return ''
  if (g.media.hero_bg_path) {
    return mediaThumbUrl(g.media.hero_bg_path, 'md', store.assetVersion)
  }
  const ss = linkedScreenshotMap.value[g.id]
  if (ss) return ss
  const fallbackCover = g.media.cover_path || g.media.cover_thumb_path
  return fallbackCover ? mediaThumbUrl(fallbackCover, 'md', store.assetVersion) : ''
})

const floorReflectionImg = computed(() => {
  const g = currentGame.value
  if (!g) return ''
  return coverThumb(g) || activeBackdropUrl.value
})

// ─────────────── 轻量浮游光尘 Canvas 粒子 ───────────────

interface DustMote {
  x: number
  y: number
  r: number
  vx: number
  vy: number
  phase: number
  speed: number
  baseAlpha: number
  warmth: number
}

let motes: DustMote[] = []

function initMotes(w: number, h: number) {
  const count = 22
  motes = Array.from({ length: count }, () => ({
    x: Math.random() * w,
    y: Math.random() * h,
    r: 1.1 + Math.random() * 2.5,
    vx: (Math.random() - 0.5) * 0.16,
    vy: -(0.08 + Math.random() * 0.22),
    phase: Math.random() * Math.PI * 2,
    speed: 0.006 + Math.random() * 0.012,
    baseAlpha: 0.12 + Math.random() * 0.24,
    warmth: Math.random(),
  }))
}

function stopParticles() {
  if (particleRaf !== null) {
    cancelAnimationFrame(particleRaf)
    particleRaf = null
  }
  const canvas = particleCanvasRef.value
  if (canvas) {
    const ctx = canvas.getContext('2d')
    ctx?.clearRect(0, 0, canvas.width, canvas.height)
  }
}

function startParticles() {
  stopParticles()
  if (!store.galleryParticles) return
  const canvas = particleCanvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  const resize = () => {
    const w = window.innerWidth
    const h = window.innerHeight
    canvas.width = Math.floor(w * dpr)
    canvas.height = Math.floor(h * dpr)
    canvas.style.width = `${w}px`
    canvas.style.height = `${h}px`
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    if (motes.length === 0) initMotes(w, h)
  }
  resize()

  const tick = () => {
    if (!store.galleryParticles) {
      stopParticles()
      return
    }
    const w = window.innerWidth
    const h = window.innerHeight
    ctx.clearRect(0, 0, w, h)

    for (const m of motes) {
      m.x += m.vx + Math.sin(m.phase * 0.6) * 0.06
      m.y += m.vy
      m.phase += m.speed

      if (m.y < -16) {
        m.y = h + 16
        m.x = Math.random() * w
      }
      if (m.x < -16) m.x = w + 16
      if (m.x > w + 16) m.x = -16

      const alpha = m.baseAlpha * (0.52 + 0.48 * Math.sin(m.phase))
      const g = Math.round(244 - m.warmth * 12)
      const b = Math.round(234 - m.warmth * 30)

      const grad = ctx.createRadialGradient(m.x, m.y, 0, m.x, m.y, m.r * 3.2)
      grad.addColorStop(0, `rgba(255, ${g}, ${b}, ${alpha.toFixed(3)})`)
      grad.addColorStop(0.45, `rgba(255, ${g}, ${b}, ${(alpha * 0.35).toFixed(3)})`)
      grad.addColorStop(1, `rgba(255, ${g}, ${b}, 0)`)

      ctx.fillStyle = grad
      ctx.beginPath()
      ctx.arc(m.x, m.y, m.r * 3.2, 0, Math.PI * 2)
      ctx.fill()
    }

    particleRaf = requestAnimationFrame(tick)
  }

  particleRaf = requestAnimationFrame(tick)
}

function handleResize() {
  if (store.galleryParticles) {
    motes = []
    startParticles()
  }
}

watch(
  () => [
    gamesList.value.length,
    store.filterStatus,
    store.filterTag,
    store.activeCollectionId,
    store.sortBy,
    store.sortOrder,
  ],
  () => syncInitialIndex(),
)

watch(
  () => currentGame.value?.id,
  () => {
    if (currentGame.value) {
      void ensureLinkedFallbackScreenshot(currentGame.value)
    }
  },
  { immediate: true },
)

watch(
  () => store.galleryParticles,
  (enabled) => {
    if (enabled) startParticles()
    else stopParticles()
  },
)

watch(
  () => [
    ejectedGameId.value,
    currentGame.value?.media?.bgm_path,
    currentGame.value?.media?.bgm_remote_url,
  ],
  () => {
    const g = currentGame.value
    if (!g || ejectedGameId.value !== g.id) return
    void audio.syncGameBgm(g, {
      autoPlay: store.bgmAutoplay && !store.running.running && !audio.autoplaySuppressed,
      cacheBust: store.assetVersion,
    })
  },
)

function closeDropdownOnOutsideClick(e: MouseEvent) {
  const target = e.target as HTMLElement | null
  if (!target?.closest('.gallery-col-dropdown')) {
    colDropdownOpen.value = false
  }
  if (!target?.closest('.gallery-sort-dropdown')) {
    sortDropdownOpen.value = false
  }
}

onMounted(() => {
  syncInitialIndex()
  if (store.galleryParticles) {
    startParticles()
  }
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('click', closeDropdownOnOutsideClick)
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  clearChoreographyTimers()
  stopParticles()
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('click', closeDropdownOnOutsideClick)
  window.removeEventListener('resize', handleResize)
})
</script>

<template>
  <main class="shelf-root" @wheel="onWheel">
    <!-- 联动氛围墙背景层 -->
    <div class="shelf-bg">
      <Transition name="gallery-bg-fade">
        <div
          v-if="activeBackdropUrl"
          :key="activeBackdropUrl"
          class="shelf-bg-img"
          :class="{ 'privacy-blur-img': store.shouldBlurGame(currentGame) }"
          :style="{ backgroundImage: `url('${activeBackdropUrl}')` }"
        />
      </Transition>
      <div class="gallery-diagonal-beam" />
      <div class="gallery-spotlight" />
      <div class="shelf-bg-vignette" />
      <svg class="film-grain" aria-hidden="true">
        <filter id="gallery-grain">
          <feTurbulence type="fractalNoise" baseFrequency="0.78" numOctaves="3" stitchTiles="stitch" />
        </filter>
        <rect width="100%" height="100%" filter="url(#gallery-grain)" />
      </svg>
    </div>

    <!-- 超大号日文原名衬线背景水印（Editorial Typography） -->
    <div v-if="galleryTab === 'works'" class="watermark-stage" aria-hidden="true">
      <Transition name="watermark-shift" mode="out-in">
        <div v-if="watermarkText" :key="`${currentGame?.id}-${watermarkText}`" class="editorial-watermark">
          {{ watermarkText }}
        </div>
      </Transition>
    </div>

    <!-- 二次元空气感浮游光尘 Canvas 粒子层 -->
    <canvas v-show="store.galleryParticles" ref="particleCanvasRef" class="dust-canvas" aria-hidden="true" />

    <!-- 顶部极简双语 HUD + 全部作品/系列合集分段切换 -->
    <header class="shelf-topbar">
      <div class="shelf-top-left">
        <button class="topbar-ghost-btn" @click="enterDetail()">
          <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.75">
            <path d="M12.5 15L7.5 10l5-5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span>详情</span>
        </button>

        <!-- 精致分段切换：全部作品 | 系列合集 -->
        <div class="gallery-view-seg" role="tablist" aria-label="回廊视图切换">
          <button
            type="button"
            role="tab"
            class="gallery-seg-btn"
            :class="{ active: galleryTab === 'works' && store.activeCollectionId === null }"
            :aria-selected="galleryTab === 'works' && store.activeCollectionId === null"
            @click="openAllWorksTab"
          >
            全部作品
          </button>
          <button
            type="button"
            role="tab"
            class="gallery-seg-btn"
            :class="{ active: galleryTab === 'collections' }"
            :aria-selected="galleryTab === 'collections'"
            @click="galleryTab = 'collections'"
          >
            <span>系列合集</span>
            <span v-if="store.collections.length > 0" class="gallery-seg-count tabular-nums">
              {{ store.collections.length }}
            </span>
          </button>
        </div>

        <template v-if="galleryTab === 'works'">
          <div class="gallery-col-dropdown">
            <button
              type="button"
              class="gallery-title-trigger"
              :class="{ 'is-filtered': store.activeCollectionId !== null }"
              @click.stop="colDropdownOpen = !colDropdownOpen"
            >
              <span class="gallery-title-cn">回廊</span>
              <span class="gallery-title-en">GALLERY</span>
              <span class="gallery-sep">·</span>
              <span class="gallery-col-label">{{ activeCollectionLabel }}</span>
              <svg
                class="dropdown-caret"
                :class="{ open: colDropdownOpen }"
                viewBox="0 0 16 16"
                width="13"
                height="13"
                fill="none"
                stroke="currentColor"
                stroke-width="1.7"
              >
                <path d="M4.5 6.25L8 9.75l3.5-3.5" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>

            <Transition name="fade">
              <div v-if="colDropdownOpen" class="col-menu">
                <button
                  type="button"
                  class="col-menu-item"
                  :class="{ active: store.activeCollectionId === null }"
                  @click="selectCollectionFromDropdown(null)"
                >
                  <span>全部藏品</span>
                  <span class="menu-count tabular-nums">{{ store.games.length }}</span>
                </button>

                <button
                  v-for="col in store.collections"
                  :key="col.id"
                  type="button"
                  class="col-menu-item"
                  :class="{ active: store.activeCollectionId === col.id }"
                  @click="selectCollectionFromDropdown(col.id)"
                >
                  <span class="menu-col-name">{{ col.name }}</span>
                  <span class="menu-count tabular-nums">{{ col.total_count ?? col.game_ids.length }}</span>
                </button>

                <div class="col-menu-divider" />

                <button type="button" class="col-menu-item col-menu-create" @click="openNewCollection">
                  <span>+ 新建合集</span>
                </button>
              </div>
            </Transition>
          </div>

          <!-- 顶部快捷状态筛选条（与左侧边栏和当前分组双向同步） -->
          <nav class="status-filter-bar" aria-label="按攻略进度筛选">
            <button
              v-for="tab in statusFilterTabs"
              :key="tab.key"
              type="button"
              class="status-tab-btn"
              :class="{ active: store.activeStatus === tab.key }"
              @click="store.setActiveStatus(tab.key)"
            >
              <span v-if="tab.dotClass" class="status-dot" :class="tab.dotClass" />
              <span>{{ tab.label }}</span>
              <span class="status-tab-count tabular-nums">{{ store.collectionStatusCounts[tab.key] }}</span>
            </button>
          </nav>

          <div v-if="store.filterTag" class="filter-summary">
            <span class="filter-pill">
              {{ store.filterTag }}
              <button class="pill-close" aria-label="清除标签" @click="store.setFilterTag('')">×</button>
            </span>
          </div>
        </template>
      </div>

      <!-- 右上角极简无边框排序下拉控件（仅全部作品视图显示） -->
      <div v-if="galleryTab === 'works'" class="gallery-sort-dropdown">
        <button
          type="button"
          class="sort-trigger-btn"
          :class="{ open: sortDropdownOpen }"
          :title="`排序：${activeSortOption.label}（${store.sortOrder === 'asc' ? '升序' : '降序'}）`"
          @click.stop="sortDropdownOpen = !sortDropdownOpen"
        >
          <svg viewBox="0 0 18 18" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M3 5h12M5 9h8M7 13h4" stroke-linecap="round" />
          </svg>
          <span>{{ activeSortOption.shortLabel }}</span>
          <svg
            class="sort-dir-icon"
            :class="{ desc: store.sortOrder === 'desc' }"
            viewBox="0 0 14 14"
            width="11"
            height="11"
            fill="none"
            stroke="currentColor"
            stroke-width="1.7"
          >
            <path d="M7 11V3M4 6l3-3 3 3" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>

        <Transition name="fade">
          <div v-if="sortDropdownOpen" class="sort-menu">
            <button
              v-for="opt in SORT_OPTIONS"
              :key="opt.key"
              type="button"
              class="sort-menu-item"
              :class="{ active: store.sortBy === opt.key }"
              @click="pickSortMode(opt.key)"
            >
              <span>{{ opt.label }}</span>
              <span v-if="store.sortBy === opt.key" class="sort-active-mark">
                {{ store.sortOrder === 'asc' ? '↑' : '↓' }}
              </span>
            </button>

            <div class="col-menu-divider" />

            <button type="button" class="sort-menu-item sort-flip-row" @click="flipSortOrder">
              <span>切换为{{ store.sortOrder === 'asc' ? '降序' : '升序' }}</span>
              <span class="sort-active-mark">{{ store.sortOrder === 'asc' ? '↓' : '↑' }}</span>
            </button>
          </div>
        </Transition>
      </div>

      <button
        v-else-if="galleryTab === 'collections' && store.collections.length > 0"
        type="button"
        class="topbar-create-col-btn"
        title="新建系列合集"
        @click="openNewCollection"
      >
        <span>+ 新建合集</span>
      </button>
    </header>

    <!-- 系列合集总览与关联排序面板 -->
    <SeriesCollectionsPanel
      v-if="galleryTab === 'collections'"
      @open-game="enterDetail"
      @browse-in-shelf="browseCollectionInShelf"
    />

    <!-- 空状态 -->
    <div v-else-if="gamesList.length === 0" class="shelf-empty">
      <div class="shelf-empty-box">
        <h2>
          {{
            store.activeCollection
              ? `「${store.activeCollection.name}」暂无匹配作品`
              : '暂无匹配作品'
          }}
        </h2>
        <p>
          {{
            store.activeStatus !== 'all' || store.filterTag
              ? '当前筛选条件下没有对应的收藏。'
              : store.activeCollection
                ? '可向此分组添加作品，或切换查看全部藏品。'
                : '导入新作品后将在此处陈列。'
          }}
        </p>
        <div class="shelf-empty-btns">
          <button
            v-if="store.activeStatus !== 'all' || store.filterTag || store.activeCollection"
            class="btn btn-primary"
            @click="resetGalleryFilters"
          >
            查看全部
          </button>
          <button
            v-if="store.activeCollection && store.activeStatus === 'all' && !store.filterTag"
            class="btn"
            @click="store.openEditCollectionModal(store.activeCollection.id)"
          >
            管理分组成员
          </button>
          <button
            v-if="!store.activeCollection && store.activeStatus === 'all' && !store.filterTag"
            class="btn btn-primary"
            @click="store.openImport('aggregated')"
          >
            + 导入游戏
          </button>
        </div>
      </div>
    </div>

    <!-- 真 3D 立体回廊舞台 -->
    <section
      v-else
      class="stage-viewport"
      @mousemove="onStageMouseMove"
      @mouseleave="resetStageTilt"
    >
      <div class="stage-camera">
        <!-- 深色磨砂玻璃展台搁板 + 1px 顶缘渐变高光 + 镜面微倒影 -->
        <div class="shelf-plank">
          <div class="plank-specular-edge" />
          <div
            v-if="floorReflectionImg"
            class="active-mirror-reflection"
            :class="{ 'privacy-blur-img': store.shouldBlurGame(currentGame) }"
            :style="{ backgroundImage: `url('${floorReflectionImg}')` }"
          />
        </div>
        <div class="shelf-floor-glow">
          <div
            v-if="floorReflectionImg"
            class="floor-color-echo"
            :style="{ backgroundImage: `url('${floorReflectionImg}')` }"
          />
        </div>

        <!-- 外层槽位容器 (.disc-slot) -->
        <div
          v-for="entry in visibleCases"
          :key="entry.game.id"
          class="disc-slot"
          :class="{ 'is-active': pulledGameId === entry.game.id }"
          :style="slotPositionStyle(entry.game, entry.offset)"
          @click="handleCaseClick(entry.game, entry.index)"
          @dblclick="enterDetail(entry.game.id)"
        >
          <!-- 内层真 3D 六面体 (.disc-box，统一 46px 典藏厚盒) -->
          <div
            class="disc-box collector"
            :class="{
              pulled: pulledGameId === entry.game.id,
              ejected: ejectedGameId === entry.game.id,
            }"
            :style="boxRotationStyle(entry.game, entry.offset)"
          >
            <div class="case-contact-shadow" />

            <!-- 夹层 Z=0 镭射光盘 -->
            <div class="disc-slot-layer">
              <div class="optical-disc">
                <div
                  class="disc-art"
                  :class="{ 'privacy-blur-img': store.shouldBlurGame(entry.game) }"
                  :style="coverThumb(entry.game) ? { backgroundImage: `url('${coverThumb(entry.game)}')` } : undefined"
                />
                <div class="disc-sheen" />
                <div class="disc-inner-ring" />
                <div class="disc-spindle-hole" />
              </div>
            </div>

            <!-- 面 1：正面封面 -->
            <div class="face face-front">
              <img
                v-if="coverThumb(entry.game)"
                v-img-fade
                :src="coverThumb(entry.game)"
                :alt="entry.game.title"
                :class="{ 'privacy-blur-img': store.shouldBlurGame(entry.game) }"
                loading="lazy"
                decoding="async"
                draggable="false"
                @error="fallbackToOriginalImage($event, coverOriginalUrl(entry.game))"
              />
              <div v-else class="front-fallback">
                <span>{{ entry.game.title }}</span>
              </div>
              <div class="plastic-hinge" />
              <div class="plastic-lip top" />
              <div class="plastic-lip bottom" />
              <div class="plastic-glare" />
            </div>

            <!-- 面 2：背面封底 -->
            <div class="face face-back">
              <div
                class="back-bg"
                :class="{ 'privacy-blur-img': store.shouldBlurGame(entry.game) }"
                :style="coverThumb(entry.game) ? { backgroundImage: `url('${coverThumb(entry.game)}')` } : undefined"
              />
              <div class="back-overlay">
                <div class="back-title">{{ entry.game.title }}</div>
                <p class="back-desc">{{ (entry.game.synopsis || 'TSUMUGI ARCHIVE EDITION').slice(0, 90) }}</p>
                <div class="back-barcode">
                  <span>{{ entry.game.developer || 'LOCAL' }}</span>
                  <div class="barcode-bars" />
                </div>
              </div>
            </div>

            <!-- 面 3：四段式拟物侧封 -->
            <div
              class="face face-spine"
              :class="{ 'custom-spine': Boolean(entry.game.media?.custom_spine_path) }"
            >
              <div
                class="spine-tex"
                :class="{ 'privacy-blur-img': store.shouldBlurGame(entry.game) }"
                :style="spineTextureUrl(entry.game) ? { backgroundImage: `url('${spineTextureUrl(entry.game)}')` } : undefined"
              />
              <div class="spine-refraction" />
              <div class="spine-hover-sheen" />

              <div class="spine-content">
                <div
                  v-if="spineBadgeFor(entry.game)"
                  class="spine-badge"
                  :style="{
                    backgroundColor: spineBadgeFor(entry.game)!.bg,
                    color: spineBadgeFor(entry.game)!.color,
                  }"
                >
                  {{ spineBadgeFor(entry.game)!.label }}
                </div>
                <div v-else class="spine-badge-spacer" />

                <div class="spine-title-zone">
                  <img
                    v-if="entry.game.media?.logo_path"
                    v-img-fade
                    :src="mediaThumbUrl(entry.game.media.logo_path, 'sm', store.assetVersion)"
                    :alt="entry.game.title"
                    class="spine-mini-logo"
                    loading="lazy"
                    decoding="async"
                    @error="fallbackToOriginalImage($event, assetUrl(entry.game.media.logo_path, store.assetVersion))"
                  />
                  <span v-else class="spine-vertical-text">{{ entry.game.title }}</span>
                </div>

                <div class="spine-led-wrap">
                  <span class="spine-led" :class="`led-${entry.game.status}`" />
                </div>

                <div class="spine-footer">
                  <span class="spine-dev">{{ devAbbrev(entry.game.developer) }}</span>
                  <span class="spine-num tabular-nums">#{{ String(entry.index + 1).padStart(3, '0') }}</span>
                </div>
              </div>
            </div>

            <!-- 面 4：右侧中空出盘槽 -->
            <div class="face face-right">
              <div class="slot-groove" />
            </div>

            <!-- 面 5 & 6：上下透明盒盖 -->
            <div class="face face-top" />
            <div class="face face-bottom" />
          </div>
        </div>
      </div>

      <!-- 左右极简磨砂拨盘箭头 -->
      <button
        v-if="activeIndex > 0"
        class="shelf-arrow left"
        title="上一款 (←)"
        aria-label="上一款"
        @click="selectByIndex(activeIndex - 1)"
      >
        <svg viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6">
          <path d="M12.5 15L7.5 10l5-5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
      <button
        v-if="activeIndex < gamesList.length - 1"
        class="shelf-arrow right"
        title="下一款 (→)"
        aria-label="下一款"
        @click="selectByIndex(activeIndex + 1)"
      >
        <svg viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6">
          <path d="M7.5 5l5 5-5 5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
    </section>

    <!-- 底部作品铭牌 + 左下等宽序号指示器 + 右下留声机浮条 -->
    <footer v-if="galleryTab === 'works' && currentGame" class="exhibition-footer">
      <div class="gallery-index-indicator tabular-nums">
        {{ String(activeIndex + 1).padStart(2, '0') }} / {{ String(gamesList.length).padStart(2, '0') }}
      </div>

      <Transition name="placard-fade" mode="out-in">
        <div :key="currentGame.id" class="curator-placard">
          <!-- 第一行：衬线中文主标题 + 低透明度日文原名 + 状态小圆点 -->
          <div class="placard-title-row">
            <span class="status-dot" :class="statusDotClass(currentGame.status)" />
            <h2 class="placard-title">{{ currentGame.title }}</h2>
            <span v-if="currentGame.sub_title" class="placard-sub">{{ currentGame.sub_title }}</span>
          </div>

          <!-- 第二行：单行精炼元信息 -->
          <div class="placard-meta">
            <span v-if="currentGame.developer">{{ currentGame.developer }}</span>
            <span v-if="releaseYear" class="meta-dot tabular-nums">{{ releaseYear }}</span>
            <span class="meta-dot tabular-nums">{{ formatPlayDuration(currentPlaySeconds) }}</span>
            <span v-if="currentGameSeriesTag" class="meta-dot meta-series-tag tabular-nums">
              {{ currentGameSeriesTag }}
            </span>
          </div>

          <!-- 第三行：诗意引言（1~2 句，斜体柔白） -->
          <p v-if="poeticExcerpt" class="placard-quote">
            {{ poeticExcerpt }}
          </p>

          <!-- 第四行：极克制无边框幽灵操作组 -->
          <div class="placard-actions">
            <button type="button" class="placard-ghost-btn" @click="enterDetail(currentGame.id)">
              <span>进入作品详情</span>
              <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6">
                <path d="M6 3.5L10.5 8 6 12.5" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>

            <span class="action-divider" />

            <button v-if="isCurrentRunning" type="button" class="placard-launch running" disabled>
              <span class="hud-live-dot" />
              <span>运行中</span>
            </button>
            <button
              v-else
              type="button"
              class="placard-launch"
              :disabled="store.running.running"
              @click="handleLaunchCurrent"
            >
              <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor">
                <path d="M7.5 5.25v13.5l11-6.75-11-6.75z" />
              </svg>
              <span>立即启动</span>
            </button>
          </div>
        </div>
      </Transition>

      <!-- 右下留声机微控胶囊（与铭牌视觉平衡） -->
      <Transition name="fade">
        <div
          v-if="currentGame.media?.bgm_path || currentGame.media?.bgm_remote_url"
          class="gallery-phono-dock"
        >
          <PhonographPill :game="currentGame" />
        </div>
      </Transition>
    </footer>

    <!-- 未绑定启动程序引导弹窗 -->
    <BindExeModal
      v-if="showBindExeModal && currentGame"
      :game="currentGame"
      @close="showBindExeModal = false"
    />
  </main>
</template>

<style scoped>
.shelf-root {
  position: relative;
  width: 100%;
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  user-select: none;
  background: var(--bg-canvas);
}

/* 通透情绪绘卷背景 + 斜切展馆顶光 + 柔和暗角 + 胶片噪点 */
.shelf-bg {
  position: fixed;
  inset: 0;
  z-index: 0;
  background: var(--bg-canvas);
  overflow: hidden;
}

.shelf-bg-img {
  position: absolute;
  inset: -32px;
  background-size: cover;
  background-position: center 24%;
  filter: blur(14px) saturate(1.22);
  transform: scale(1.06);
  opacity: 0.38;
  will-change: opacity;
}

.gallery-bg-fade-enter-active,
.gallery-bg-fade-leave-active {
  transition: opacity 0.8s var(--ease-out-expo);
}

.gallery-bg-fade-enter-from,
.gallery-bg-fade-leave-to {
  opacity: 0;
}

/* 展馆斜切顶光束 */
.gallery-diagonal-beam {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    126deg,
    transparent 18%,
    rgba(255, 250, 240, 0.055) 42%,
    rgba(255, 255, 255, 0.025) 54%,
    transparent 74%
  );
  pointer-events: none;
}

.gallery-spotlight {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(
      ellipse 58% 46% at 50% 6%,
      rgba(255, 252, 246, 0.09) 0%,
      rgba(255, 255, 255, 0.024) 44%,
      transparent 72%
    ),
    radial-gradient(
      ellipse 46% 20% at 50% 72%,
      rgba(255, 255, 255, 0.036) 0%,
      transparent 72%
    );
  pointer-events: none;
}

/* 柔和四周暗角 + 底部渐变过渡，保持绘卷色彩透出与前景高对比 */
.shelf-bg-vignette {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(
      to top,
      #0a0a0c 0%,
      rgba(10, 10, 12, 0.86) 24%,
      rgba(10, 10, 12, 0.28) 56%,
      rgba(10, 10, 12, 0.42) 100%
    ),
    radial-gradient(
      circle at 50% 42%,
      transparent 22%,
      rgba(10, 10, 12, 0.72) 86%
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

/* 超大号日文原名衬线背景水印 */
.watermark-stage {
  position: fixed;
  inset: 0;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 5vw 14vh;
  pointer-events: none;
  overflow: hidden;
}

.editorial-watermark {
  font-family: var(--font-serif);
  font-size: clamp(56px, 9vw, 132px);
  font-weight: 600;
  letter-spacing: 0.08em;
  line-height: 1.1;
  color: #f4f4f5;
  opacity: 0.055;
  white-space: nowrap;
  max-width: 96vw;
  overflow: hidden;
  text-overflow: ellipsis;
  user-select: none;
}

.watermark-shift-enter-active,
.watermark-shift-leave-active {
  transition:
    opacity 0.65s var(--ease-out-expo),
    transform 0.65s var(--ease-out-expo);
}

.watermark-shift-enter-from {
  opacity: 0;
  transform: translateX(28px);
}

.watermark-shift-leave-to {
  opacity: 0;
  transform: translateX(-28px);
}

/* 浮游光尘粒子层 */
.dust-canvas {
  position: fixed;
  inset: 0;
  z-index: 4;
  pointer-events: none;
}

/* Top Floating HUD */
.shelf-topbar {
  position: relative;
  z-index: 26;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: calc(22px + var(--titlebar-safe-top, 0px)) 44px 4px 54px;
}

.shelf-top-left {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

/* 回廊「全部作品 | 系列合集」精致分段切换 */
.gallery-view-seg {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.055);
  border: 1px solid rgba(255, 255, 255, 0.07);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
}

.gallery-seg-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.gallery-seg-btn:hover:not(.active) {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.06);
}

.gallery-seg-btn.active {
  background: #f5f5f7;
  color: #0a0a0c;
  font-weight: 600;
}

.gallery-seg-count {
  font-size: 11px;
  opacity: 0.72;
}

.topbar-create-col-btn {
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.045);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    border-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.topbar-create-col-btn:hover {
  background: rgba(255, 255, 255, 0.12);
  border-color: rgba(255, 255, 255, 0.16);
  color: #ffffff;
}

/* 顶部快捷状态筛选条 */
.status-filter-bar {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.04);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}

.status-tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.status-tab-btn:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.06);
}

.status-tab-btn.active {
  background: rgba(255, 255, 255, 0.14);
  color: #f5f5f7;
}

.status-tab-count {
  font-size: 11px;
  color: var(--text-muted);
  opacity: 0.85;
}

.status-tab-btn.active .status-tab-count {
  color: rgba(245, 245, 247, 0.78);
}

/* 回廊极简排序下拉控件 */
.gallery-sort-dropdown {
  position: relative;
  flex-shrink: 0;
}

.sort-trigger-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: none;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.045);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.sort-trigger-btn:hover,
.sort-trigger-btn.open {
  background: rgba(255, 255, 255, 0.11);
  color: var(--text-primary);
}

.sort-dir-icon {
  opacity: 0.72;
  transition: transform var(--duration-fast) var(--ease-out-expo);
}

.sort-dir-icon.desc {
  transform: rotate(180deg);
}

.sort-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 176px;
  padding: 6px;
  border-radius: 12px;
  background: var(--bg-acrylic-strong);
  backdrop-filter: blur(28px) saturate(140%);
  -webkit-backdrop-filter: blur(28px) saturate(140%);
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 18px 46px rgba(0, 0, 0, 0.64);
  display: flex;
  flex-direction: column;
  gap: 2px;
  z-index: 40;
}

.sort-menu-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  padding: 7px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12.5px;
  text-align: left;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.sort-menu-item:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
}

.sort-menu-item.active {
  background: rgba(255, 255, 255, 0.12);
  color: #f5f5f7;
  font-weight: 500;
}

.sort-flip-row {
  color: var(--text-muted);
  font-size: 12px;
}

.sort-active-mark {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-primary);
}

.topbar-ghost-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border: none;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 500;
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.topbar-ghost-btn:hover {
  background: rgba(255, 255, 255, 0.13);
}

/* 回廊双语标题 + 分组下拉菜单 */
.gallery-col-dropdown {
  position: relative;
}

.gallery-title-trigger {
  display: inline-flex;
  align-items: baseline;
  gap: 7px;
  padding: 6px 12px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--text-primary);
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    border-color var(--duration-fast) var(--ease-out-expo);
}

.gallery-title-trigger:hover {
  background: rgba(255, 255, 255, 0.07);
}

.gallery-title-trigger.is-filtered {
  background: rgba(255, 255, 255, 0.11);
  border-color: rgba(255, 255, 255, 0.22);
  color: #ffffff;
}

.gallery-title-trigger.is-filtered .gallery-col-label {
  color: #ffffff;
  font-weight: 600;
}

.gallery-title-cn {
  font-family: var(--font-serif);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--text-primary);
}

.gallery-title-en {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.18em;
  color: var(--text-muted);
  opacity: 0.65;
}

.gallery-sep {
  color: rgba(255, 255, 255, 0.25);
  margin: 0 1px;
}

.gallery-col-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.dropdown-caret {
  align-self: center;
  color: var(--text-muted);
  transition: transform var(--duration-fast) var(--ease-out-expo);
}

.dropdown-caret.open {
  transform: rotate(180deg);
  color: var(--text-primary);
}

.col-menu {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  min-width: 210px;
  padding: 6px;
  border-radius: 13px;
  background: var(--bg-acrylic-strong);
  backdrop-filter: blur(32px) saturate(140%);
  -webkit-backdrop-filter: blur(32px) saturate(140%);
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.72);
  display: flex;
  flex-direction: column;
  gap: 2px;
  z-index: 40;
}

.col-menu-item {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  padding: 8px 10px 8px 12px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  text-align: left;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.col-menu-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 7px;
  bottom: 7px;
  width: 2px;
  border-radius: 2px;
  background: var(--active-bar);
  opacity: 0;
}

.col-menu-item:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.col-menu-item.active {
  background: var(--surface-active);
  color: var(--text-primary);
  font-weight: 500;
}

.col-menu-item.active::before {
  opacity: 1;
}

.menu-col-name {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.menu-count {
  font-size: 11.5px;
  color: var(--text-muted);
}

.col-menu-divider {
  height: 1px;
  background: var(--divider-subtle);
  margin: 4px 6px;
}

.col-menu-create {
  color: var(--text-primary);
}

.filter-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-muted);
}

.filter-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  font-size: 11.5px;
  color: var(--text-primary);
}

.pill-close {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1;
}

.pill-close:hover {
  color: #ffffff;
}

.shelf-top-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.top-counter {
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 0.08em;
  color: rgba(244, 244, 245, 0.45);
}

.bg-refresh-btn {
  width: 34px;
  height: 34px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-secondary);
  opacity: 0.65;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition:
    opacity var(--duration-fast) var(--ease-out-expo),
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.bg-refresh-btn:hover {
  opacity: 1;
  background: rgba(255, 255, 255, 0.12);
  color: var(--text-primary);
}

.spinning {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* Empty State */
.shelf-empty {
  flex: 1;
  position: relative;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.shelf-empty-box {
  padding: 40px 44px;
  border-radius: var(--radius-lg);
  background: var(--bg-acrylic);
  backdrop-filter: var(--backdrop-acrylic);
  -webkit-backdrop-filter: var(--backdrop-acrylic);
  box-shadow: inset 0 1px 0 var(--highlight-top), 0 24px 64px rgba(0, 0, 0, 0.55);
  text-align: center;
  max-width: 440px;
}

.shelf-empty-box h2 {
  margin: 0 0 10px;
  font-family: var(--font-serif);
  font-size: 20px;
  font-weight: 600;
}

.shelf-empty-box p {
  margin: 0 0 22px;
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.shelf-empty-btns {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 10px;
}

/* 3D Stage */
.stage-viewport {
  flex: 1;
  position: relative;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
  perspective: 1450px;
  perspective-origin: 50% 46%;
  overflow: hidden;
}

.stage-camera {
  position: relative;
  width: 220px;
  height: 310px;
  transform-style: preserve-3d;
  transform: translateY(-18px) rotateX(-5deg);
}

/* Dark Frosted Glass Gallery Plinth + Specular Edge + Inverted Soft Mirror Reflection */
.shelf-plank {
  position: absolute;
  left: -680px;
  top: 320px;
  width: 1580px;
  height: 230px;
  transform-origin: top center;
  transform: rotateX(87deg) translateZ(16px);
  background: linear-gradient(
    180deg,
    rgba(255, 255, 255, 0.09) 0%,
    rgba(22, 22, 26, 0.78) 6%,
    rgba(12, 12, 15, 0.92) 45%,
    rgba(10, 10, 12, 0.98) 100%
  );
  box-shadow: 0 28px 96px rgba(0, 0, 0, 0.9);
  pointer-events: none;
  overflow: hidden;
}

.plank-specular-edge {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent 5%,
    rgba(255, 255, 255, 0.18) 28%,
    rgba(255, 255, 255, 0.38) 50%,
    rgba(255, 255, 255, 0.18) 72%,
    transparent 95%
  );
}

/* 磨砂玻璃表面的当前选中光盘盒微弱镜面倒影 */
.active-mirror-reflection {
  position: absolute;
  left: calc(50% - 148px);
  top: 6px;
  width: 236px;
  height: 165px;
  background-size: cover;
  background-position: center bottom;
  transform: scaleY(-1);
  filter: blur(11px) saturate(1.25);
  opacity: 0.24;
  mask-image: linear-gradient(to bottom, rgba(0, 0, 0, 0.82) 0%, rgba(0, 0, 0, 0.22) 48%, transparent 88%);
  -webkit-mask-image: linear-gradient(to bottom, rgba(0, 0, 0, 0.82) 0%, rgba(0, 0, 0, 0.22) 48%, transparent 88%);
  transition: background-image 0.6s var(--ease-out-expo);
}

.shelf-floor-glow {
  position: absolute;
  left: -210px;
  top: 323px;
  width: 640px;
  height: 118px;
  transform-origin: top center;
  transform: rotateX(87deg) translateZ(18px);
  background: radial-gradient(
    ellipse at center,
    rgba(255, 255, 255, 0.1) 0%,
    rgba(255, 255, 255, 0.025) 45%,
    transparent 74%
  );
  border-radius: 50%;
  overflow: hidden;
  pointer-events: none;
}

.floor-color-echo {
  position: absolute;
  inset: 0;
  background-size: cover;
  background-position: center;
  filter: blur(28px) saturate(1.45);
  opacity: 0.3;
  mask-image: radial-gradient(ellipse at center, #000 0%, transparent 72%);
  -webkit-mask-image: radial-gradient(ellipse at center, #000 0%, transparent 72%);
  transition: background-image 0.6s var(--ease-out-expo);
}

/* Two-Layer 3D Architecture */
.disc-slot {
  --w: 220px;
  --h: 310px;
  position: absolute;
  inset: 0;
  width: var(--w);
  height: var(--h);
  transform-style: preserve-3d;
  transform: translate3d(var(--tx, 0px), var(--ty, 0px), var(--tz, 0px));
  transition: transform 0.42s var(--ease-out-expo);
  will-change: transform;
  cursor: pointer;
}

.disc-slot:not(.is-active):hover {
  transform: translate3d(
    var(--tx, 0px),
    calc(var(--ty, 0px) - 6px),
    calc(var(--tz, 0px) + 36px)
  );
}

.disc-box {
  --d: 46px;
  position: relative;
  width: var(--w);
  height: var(--h);
  transform-style: preserve-3d;
  transition: transform 0.46s var(--ease-out-expo);
  will-change: transform;
}

.case-contact-shadow {
  position: absolute;
  left: 10px;
  top: 0;
  width: calc(var(--w) - 20px);
  height: calc(var(--d) + 32px);
  transform-origin: center center;
  transform: translateY(298px) rotateX(90deg);
  background: radial-gradient(
    ellipse at center,
    rgba(0, 0, 0, 0.72) 0%,
    rgba(0, 0, 0, 0.34) 48%,
    transparent 76%
  );
  pointer-events: none;
  opacity: 0.75;
  transition:
    opacity 0.36s var(--ease-out-expo),
    transform 0.36s var(--ease-out-expo);
}

.disc-slot:not(.is-active):hover .case-contact-shadow {
  opacity: 1;
  transform: translateY(304px) rotateX(90deg) scale(1.18, 1.35);
}

.face {
  position: absolute;
  backface-visibility: hidden;
  -webkit-backface-visibility: hidden;
}

/* 1. Front Cover */
.face-front {
  width: var(--w);
  height: var(--h);
  left: 0;
  top: 0;
  transform: translateZ(calc(var(--d) / 2));
  border-radius: 3px 8px 8px 3px;
  overflow: hidden;
  background: #141418;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.26),
    inset 0 0 0 1px rgba(255, 255, 255, 0.14),
    0 24px 52px rgba(0, 0, 0, 0.72);
}

.face-front img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.front-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  text-align: center;
  font-family: var(--font-serif);
  font-size: 20px;
  color: var(--text-secondary);
  background: linear-gradient(155deg, #1d1d22, #0d0d10);
}

.plastic-hinge {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 12px;
  width: 5px;
  background: linear-gradient(
    90deg,
    rgba(0, 0, 0, 0.48) 0%,
    rgba(255, 255, 255, 0.32) 45%,
    rgba(0, 0, 0, 0.34) 100%
  );
  pointer-events: none;
}

.plastic-lip {
  position: absolute;
  left: 0;
  right: 0;
  height: 8px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.22), rgba(255, 255, 255, 0.03));
  pointer-events: none;
}

.plastic-lip.top {
  top: 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.16);
}

.plastic-lip.bottom {
  bottom: 0;
  border-top: 1px solid rgba(255, 255, 255, 0.12);
}

.plastic-glare {
  position: absolute;
  inset: 0;
  background: radial-gradient(
    circle at var(--glare-x, 50%) var(--glare-y, 35%),
    rgba(255, 255, 255, 0.28) 0%,
    rgba(255, 255, 255, 0.07) 28%,
    transparent 62%
  );
  mix-blend-mode: screen;
  pointer-events: none;
  opacity: 0.42;
  transition: opacity 0.28s var(--ease-out-expo);
}

.disc-box.pulled .plastic-glare {
  opacity: 0.85;
}

/* 2. Back Cover */
.face-back {
  width: var(--w);
  height: var(--h);
  left: 0;
  top: 0;
  transform: rotateY(180deg) translateZ(calc(var(--d) / 2));
  border-radius: 8px 3px 3px 8px;
  overflow: hidden;
  background: #101014;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14);
}

.back-bg {
  position: absolute;
  inset: -12px;
  background-size: cover;
  background-position: center;
  filter: blur(16px) brightness(0.28);
}

.back-overlay {
  position: relative;
  height: 100%;
  padding: 20px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.back-title {
  font-size: 14px;
  font-weight: 600;
}

.back-desc {
  font-size: 11px;
  line-height: 1.65;
  color: var(--text-secondary);
}

.back-barcode {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
}

.barcode-bars {
  width: 58px;
  height: 20px;
  background: repeating-linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.72) 0 2px,
    transparent 2px 4px,
    rgba(255, 255, 255, 0.72) 4px 5px,
    transparent 5px 8px
  );
  border-radius: 2px;
}

/* 3. Four-Segment Skeuomorphic Left Spine */
.face-spine {
  width: var(--d);
  height: var(--h);
  left: calc(var(--d) / -2);
  top: 0;
  transform: rotateY(-90deg);
  overflow: hidden;
  background: #141418;
  border-left: 1px solid rgba(255, 255, 255, 0.2);
  border-right: 1px solid rgba(255, 255, 255, 0.22);
  box-shadow: inset 0 0 14px rgba(0, 0, 0, 0.65);
  transition:
    border-color 0.32s var(--ease-out-expo),
    box-shadow 0.32s var(--ease-out-expo);
}

.disc-slot:not(.is-active):hover .face-spine {
  border-left-color: rgba(255, 255, 255, 0.38);
  border-right-color: rgba(255, 255, 255, 0.38);
  box-shadow:
    inset 0 0 12px rgba(0, 0, 0, 0.45),
    0 18px 36px rgba(0, 0, 0, 0.75);
}

.spine-tex {
  position: absolute;
  inset: 0;
  background-size: cover;
  background-position: left center;
  filter: brightness(0.45) saturate(1.05);
}

.face-spine.custom-spine .spine-tex {
  background-position: center;
  filter: brightness(0.92);
}

.spine-refraction {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.24) 0%,
    rgba(255, 255, 255, 0.04) 24%,
    rgba(0, 0, 0, 0.3) 72%,
    rgba(255, 255, 255, 0.14) 100%
  );
  pointer-events: none;
}

.spine-hover-sheen {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    180deg,
    rgba(255, 255, 255, 0.24) 0%,
    rgba(255, 255, 255, 0.09) 42%,
    rgba(255, 255, 255, 0.02) 100%
  );
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.32s var(--ease-out-expo);
}

.disc-slot:not(.is-active):hover .spine-hover-sheen {
  opacity: 1;
}

.spine-content {
  position: relative;
  z-index: 2;
  height: 100%;
  padding: 8px 3px 9px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
}

.spine-badge {
  width: calc(100% - 6px);
  padding: 3px 2px;
  border-radius: 3px;
  font-family: var(--font-mono);
  font-size: 8px;
  font-weight: 700;
  text-align: center;
  color: #0a0a0c;
  letter-spacing: 0.02em;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.48);
}

.spine-badge-spacer {
  height: 16px;
}

.spine-title-zone {
  flex: 1;
  min-height: 0;
  width: 100%;
  margin: 10px 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.spine-mini-logo {
  max-width: 148px;
  max-height: calc(var(--d) - 8px);
  object-fit: contain;
  transform: rotate(90deg);
  filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.85));
}

.spine-vertical-text {
  writing-mode: vertical-rl;
  text-orientation: mixed;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: #f4f4f5;
  text-shadow: 0 2px 6px rgba(0, 0, 0, 0.92);
  max-height: 164px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.disc-box.collector .spine-vertical-text {
  font-size: 13px;
}

.spine-led-wrap {
  padding: 4px 0;
}

.spine-led {
  display: block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.led-todo {
  background: var(--status-todo);
}

.led-playing {
  background: var(--status-playing);
  box-shadow: 0 0 8px rgba(245, 158, 11, 0.72);
  animation: led-pulse 2s ease-in-out infinite;
}

.led-done {
  background: var(--status-done);
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.72);
}

.spine-footer {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  font-family: var(--font-mono);
}

.spine-dev {
  font-size: 7.5px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.88);
}

.spine-num {
  font-size: 7px;
  color: rgba(255, 255, 255, 0.56);
}

/* 4. Right Hollow Disc Slot */
.face-right {
  width: var(--d);
  height: var(--h);
  left: calc(var(--w) - var(--d) / 2);
  top: 0;
  transform: rotateY(90deg);
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.14) 0%,
    #060608 22%,
    #060608 78%,
    rgba(255, 255, 255, 0.14) 100%
  );
  border-top: 1px solid rgba(255, 255, 255, 0.16);
  border-bottom: 1px solid rgba(255, 255, 255, 0.16);
  display: flex;
  align-items: center;
  justify-content: center;
}

.slot-groove {
  width: 42%;
  height: 82%;
  border-radius: 999px;
  background: #020204;
  box-shadow:
    inset 0 0 8px rgba(0, 0, 0, 0.96),
    0 0 2px rgba(255, 255, 255, 0.14);
}

/* 5 & 6. Top & Bottom Translucent Acrylic Caps */
.face-top {
  width: var(--w);
  height: var(--d);
  left: 0;
  top: calc(var(--d) / -2);
  transform: rotateX(90deg);
  background: linear-gradient(180deg, rgba(244, 244, 245, 0.2), rgba(32, 32, 38, 0.56));
  border: 1px solid rgba(255, 255, 255, 0.18);
}

.face-bottom {
  width: var(--w);
  height: var(--d);
  left: 0;
  top: calc(var(--h) - var(--d) / 2);
  transform: rotateX(-90deg);
  background: linear-gradient(180deg, rgba(18, 18, 22, 0.78), rgba(244, 244, 245, 0.12));
  border: 1px solid rgba(255, 255, 255, 0.12);
}

/* Optical Laser Disc at Z = 0 */
.disc-slot-layer {
  position: absolute;
  width: 204px;
  height: 204px;
  left: 8px;
  top: 53px;
  transform: translateZ(0px);
  pointer-events: none;
  transform-style: preserve-3d;
}

.optical-disc {
  position: relative;
  width: 204px;
  height: 204px;
  border-radius: 50%;
  overflow: hidden;
  background: #16161a;
  border: 2px solid rgba(255, 255, 255, 0.34);
  box-shadow:
    0 14px 36px rgba(0, 0, 0, 0.72),
    inset 0 0 18px rgba(255, 255, 255, 0.22);
  transform: translateX(0px) rotate(0deg);
  opacity: 0;
  transition:
    transform 0.6s var(--ease-out-expo),
    opacity 0.24s var(--ease-out-expo);
}

.disc-box.pulled .optical-disc {
  opacity: 1;
}

.disc-box.ejected .optical-disc {
  opacity: 1;
  transform: translateX(126px) rotate(135deg);
}

.disc-art {
  position: absolute;
  inset: 0;
  background-size: cover;
  background-position: center;
  opacity: 0.78;
}

.disc-sheen {
  position: absolute;
  inset: 0;
  background: conic-gradient(
    from 28deg,
    rgba(255, 255, 255, 0.34),
    rgba(186, 230, 253, 0.24),
    rgba(254, 243, 199, 0.22),
    rgba(255, 255, 255, 0.08),
    rgba(226, 232, 240, 0.28),
    rgba(167, 243, 208, 0.2),
    rgba(255, 255, 255, 0.34)
  );
  mix-blend-mode: screen;
}

.disc-inner-ring {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 64px;
  height: 64px;
  transform: translate(-50%, -50%);
  border-radius: 50%;
  background: rgba(228, 228, 231, 0.26);
  border: 2px solid rgba(255, 255, 255, 0.42);
  backdrop-filter: blur(4px);
}

.disc-spindle-hole {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 24px;
  height: 24px;
  transform: translate(-50%, -50%);
  border-radius: 50%;
  background: var(--bg-canvas);
  border: 2px solid rgba(255, 255, 255, 0.5);
}

/* Minimal Navigation Arrows */
.shelf-arrow {
  position: absolute;
  top: 48%;
  transform: translateY(-50%);
  z-index: 30;
  width: 44px;
  height: 68px;
  border-radius: 12px;
  border: none;
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.shelf-arrow:hover {
  background: rgba(255, 255, 255, 0.14);
  color: #ffffff;
}

.shelf-arrow.left {
  left: 32px;
}

.shelf-arrow.right {
  right: 32px;
}

/* =========================================================================
   底部日系策展典藏作品铭牌 + 右下留声机浮条
   ========================================================================= */
.exhibition-footer {
  position: relative;
  z-index: 24;
  padding: 0 44px 30px 54px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  min-height: 162px;
}

.curator-placard {
  max-width: 640px;
  width: 100%;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.placard-title-row {
  display: inline-flex;
  align-items: baseline;
  justify-content: center;
  flex-wrap: wrap;
  gap: 10px;
}

.placard-title-row .status-dot {
  align-self: center;
}

.placard-title {
  margin: 0;
  font-family: var(--font-serif);
  font-size: clamp(20px, 2.2vw, 26px);
  font-weight: 600;
  letter-spacing: 0.05em;
  color: var(--text-primary);
  text-shadow: 0 4px 20px rgba(0, 0, 0, 0.65);
}

.placard-sub {
  font-size: 13px;
  font-weight: 400;
  color: rgba(244, 244, 245, 0.44);
  letter-spacing: 0.03em;
}

.placard-meta {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text-secondary);
}

.meta-series-tag {
  color: rgba(244, 244, 245, 0.72);
}

.meta-dot::before {
  content: '·';
  margin-right: 8px;
  color: rgba(255, 255, 255, 0.26);
}

.placard-quote {
  margin: 2px 0 4px;
  max-width: 56ch;
  font-size: 12.5px;
  font-style: italic;
  line-height: 1.7;
  color: rgba(244, 244, 245, 0.56);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.placard-actions {
  display: inline-flex;
  align-items: center;
  gap: 14px;
  margin-top: 2px;
}

.placard-ghost-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 14px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.02em;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.placard-ghost-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
}

.action-divider {
  width: 1px;
  height: 14px;
  background: rgba(255, 255, 255, 0.14);
}

.placard-launch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 18px;
  border: none;
  border-radius: 999px;
  background: #f5f5f7;
  color: #0a0a0c;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    transform var(--duration-fast) var(--ease-out-expo),
    opacity var(--duration-fast) var(--ease-out-expo);
}

.placard-launch:hover:not(:disabled) {
  background: #ffffff;
  transform: translateY(-1px);
}

.placard-launch:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.placard-launch.running {
  background: var(--emerald-bg);
  color: var(--emerald-text);
  opacity: 1;
}

.placard-fade-enter-active,
.placard-fade-leave-active {
  transition:
    opacity 0.34s var(--ease-out-expo),
    transform 0.34s var(--ease-out-expo);
}

.placard-fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.placard-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

.gallery-index-indicator {
  position: absolute;
  left: 54px;
  bottom: 36px;
  font-family: var(--font-mono);
  font-size: 12.5px;
  letter-spacing: 0.1em;
  color: var(--text-primary);
  opacity: 0.45;
  pointer-events: none;
}

.gallery-phono-dock {
  position: absolute;
  right: 44px;
  bottom: 30px;
  z-index: 26;
}

.hud-live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--emerald);
  animation: led-pulse 2s ease-in-out infinite;
}

@keyframes led-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.45;
    transform: scale(0.84);
  }
}

@media (max-width: 1120px) {
  .gallery-index-indicator {
    position: static;
    margin-bottom: 6px;
  }
  .gallery-phono-dock {
    position: static;
    margin-top: 12px;
  }
  .exhibition-footer {
    flex-direction: column;
    align-items: center;
  }
}
</style>
