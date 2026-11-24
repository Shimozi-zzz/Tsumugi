<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { assetUrl, fallbackToOriginalImage, mediaThumbUrl } from '@/api/client'
import { useLibraryStore } from '@/stores/library'
import type { ActiveStatusFilter, CollectionItem, LibrarySortBy } from '@/types'
import { normalizePlatformBadge } from '@/utils/platform'
import { getSortOption, SORT_OPTIONS } from '@/utils/sortGames'

interface StatusFilterOption {
  key: ActiveStatusFilter
  label: string
  dotClass: string
}

const STATUS_FILTER_OPTIONS: StatusFilterOption[] = [
  { key: 'all', label: '全部作品', dotClass: 'dot-all' },
  { key: 'playing', label: '攻略中', dotClass: 'status-dot-playing' },
  { key: 'completed', label: '已通关', dotClass: 'status-dot-done' },
  { key: 'unplayed', label: '未开始', dotClass: 'status-dot-todo' },
]

const store = useLibraryStore()

const isOpen = ref(false)
const isPinned = ref(false)
const tagsSectionOpen = ref(true)
const tagsExpanded = ref(false)
const statusMenuOpen = ref(false)
const sortMenuOpen = ref(false)
const colMenuOpen = ref(false)
let hideTimer: number | null = null

const activeSortOption = computed(() => getSortOption(store.sortBy))
const activeStatusOption = computed(
  () => STATUS_FILTER_OPTIONS.find((opt) => opt.key === store.activeStatus) ?? STATUS_FILTER_OPTIONS[0],
)

function statusFilterCount(key: ActiveStatusFilter): number {
  return store.statusCounts[key] ?? 0
}

function toggleStatusMenu() {
  const next = !statusMenuOpen.value
  statusMenuOpen.value = next
  if (next) {
    sortMenuOpen.value = false
    colMenuOpen.value = false
  }
}

function toggleSortMenu() {
  const next = !sortMenuOpen.value
  sortMenuOpen.value = next
  if (next) {
    statusMenuOpen.value = false
    colMenuOpen.value = false
  }
}

function toggleColMenu() {
  const next = !colMenuOpen.value
  colMenuOpen.value = next
  if (next) {
    statusMenuOpen.value = false
    sortMenuOpen.value = false
  }
}

function pickSortMode(key: LibrarySortBy) {
  store.setSort(key)
  sortMenuOpen.value = false
}

function flipSortOrder() {
  store.toggleSortOrder()
  sortMenuOpen.value = false
}

function closeMenusOnOutsideClick(e: MouseEvent) {
  const target = e.target as HTMLElement | null
  if (!target?.closest('.sb-sort-wrap')) {
    sortMenuOpen.value = false
  }
  if (!target?.closest('.sb-progress-wrap')) {
    statusMenuOpen.value = false
  }
  if (!target?.closest('.sb-col-filter-wrap')) {
    colMenuOpen.value = false
  }
}

function handleDropdownKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (statusMenuOpen.value || sortMenuOpen.value || colMenuOpen.value) {
    statusMenuOpen.value = false
    sortMenuOpen.value = false
    colMenuOpen.value = false
    e.preventDefault()
    e.stopImmediatePropagation()
  }
}

onMounted(() => {
  window.addEventListener('click', closeMenusOnOutsideClick)
  window.addEventListener('keydown', handleDropdownKeydown, true)
})

onBeforeUnmount(() => {
  if (hideTimer !== null) {
    clearTimeout(hideTimer)
    hideTimer = null
  }
  window.removeEventListener('click', closeMenusOnOutsideClick)
  window.removeEventListener('keydown', handleDropdownKeydown, true)
})

const sidebarVisible = computed(() => isOpen.value || isPinned.value)

watch(sidebarVisible, (visible) => {
  if (!visible) {
    statusMenuOpen.value = false
    sortMenuOpen.value = false
    colMenuOpen.value = false
  }
})

const displayedTags = computed(() => {
  const limit = tagsExpanded.value ? 24 : 6
  return store.allTags.slice(0, limit)
})

const hasMoreTags = computed(() => store.allTags.length > 6)

function openSidebar() {
  if (hideTimer !== null) {
    clearTimeout(hideTimer)
    hideTimer = null
  }
  isOpen.value = true
}

function closeSidebarImmediately() {
  if (isPinned.value) return
  if (hideTimer !== null) {
    clearTimeout(hideTimer)
    hideTimer = null
  }
  isOpen.value = false
}

function scheduleClose() {
  if (isPinned.value) return
  if (hideTimer !== null) clearTimeout(hideTimer)
  hideTimer = window.setTimeout(() => {
    isOpen.value = false
    hideTimer = null
  }, 220)
}

function switchView(mode: 'detail' | 'shelf') {
  store.setViewMode(mode)
}

function openLedger() {
  store.showTimeLedger = true
}

function pickStatus(st: ActiveStatusFilter) {
  store.setActiveStatus(st)
  statusMenuOpen.value = false
}

function pickTag(tag: string) {
  store.setFilterTag(tag)
  if (store.filteredGames.length > 0 && !store.filteredGames.some((g) => g.id === store.activeGameId)) {
    void store.selectGame(store.filteredGames[0].id, { recordActive: false })
  }
}

function pickCollection(collectionId: number | null) {
  store.setActiveCollection(collectionId)
  colMenuOpen.value = false
}

function openCreateCollectionFromMenu() {
  colMenuOpen.value = false
  store.openCreateCollectionModal()
}

function openEditCollectionFromMenu(col: CollectionItem) {
  colMenuOpen.value = false
  store.openEditCollectionModal(col.id)
}

function statusDotClass(status: string) {
  if (status === 'playing') return 'status-dot-playing'
  if (status === 'done' || status === 'completed') return 'status-dot-done'
  return 'status-dot-todo'
}
</script>

<template>
  <!-- 左侧边缘极窄感应热区与极简银白指示条 -->
  <div
    class="sidebar-hotzone"
    :class="{ hidden: sidebarVisible }"
    @mouseenter="openSidebar"
  >
    <div class="edge-indicator" title="移入展开导航栏" />
  </div>

  <!-- 空间分层隔离：主内容区全屏暗化遮罩 -->
  <Transition name="scrim-fade">
    <div
      v-if="sidebarVisible"
      class="sidebar-scrim"
      :class="{ 'is-pinned': isPinned }"
      @click="closeSidebarImmediately"
      @mouseenter="scheduleClose"
    />
  </Transition>

  <!-- 亚克力毛玻璃滑出导航栏 -->
  <aside
    class="hover-sidebar"
    :class="{ open: sidebarVisible }"
    @mouseenter="openSidebar"
    @mouseleave="scheduleClose"
  >
    <!-- 顶部单色极简品牌区 -->
    <div class="sb-header">
      <div class="sb-brand">
        <svg class="sb-emblem" viewBox="0 0 28 28" width="26" height="26" fill="none" aria-hidden="true">
          <circle cx="14" cy="14" r="11.5" stroke="#f4f4f5" stroke-width="1.5" stroke-opacity="0.9" />
          <circle cx="14" cy="14" r="6.8" stroke="#f4f4f5" stroke-width="1" stroke-opacity="0.28" />
          <circle cx="14" cy="14" r="2.6" fill="#f4f4f5" fill-opacity="0.92" />
        </svg>
        <div class="sb-brand-text">
          <div class="sb-title">TSUMUGI</div>
          <div class="sb-sub tabular-nums">{{ store.games.length }} 部收藏</div>
        </div>
      </div>

      <button
        class="pin-btn"
        :class="{ active: isPinned }"
        :title="isPinned ? '取消固定侧栏' : '固定侧栏'"
        @click="isPinned = !isPinned"
      >
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M12 17v5" />
          <path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16h14v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1h.5a.5.5 0 0 0 .5-.5v-1a.5.5 0 0 0-.5-.5h-9a.5.5 0 0 0-.5.5v1a.5.5 0 0 0 .5.5H8a1 1 0 0 1 1 1z" />
        </svg>
      </button>
    </div>

    <!-- 无边框微透明快捷搜索入口 -->
    <button class="sb-search-trigger" @click="store.showQuickSearch = true">
      <span class="sb-search-left">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="7.5" />
          <path d="m20 20-3.8-3.8" />
        </svg>
        <span>检索游戏或拼音…</span>
      </span>
      <span class="sb-kbd">Ctrl K</span>
    </button>

    <!-- 视图空间：沉浸详情 / 回廊 / 时间账本 -->
    <nav class="sb-section" aria-label="视图切换">
      <div class="sb-section-label">视图</div>
      <div class="nav-list">
        <button
          class="nav-item"
          :class="{ active: store.viewMode === 'detail' && !store.showTimeLedger }"
          @click="switchView('detail')"
        >
          <span class="nav-item-left">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.75">
              <rect x="3" y="4.5" width="18" height="15" rx="2.5" />
              <path d="M8 14h8M8 10h4.5" />
            </svg>
            <span>沉浸详情</span>
          </span>
        </button>

        <button
          class="nav-item"
          :class="{ active: store.viewMode === 'shelf' && !store.showTimeLedger }"
          @click="switchView('shelf')"
        >
          <span class="nav-item-left">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.75">
              <path d="M4 19h16M6 5h3v14H6zM11 6h3v13h-3zM16 4l3 .8-2.5 14.2-3-.8z" />
            </svg>
            <span>回廊</span>
          </span>
          <span class="nav-en-tag">GALLERY</span>
        </button>

        <button
          class="nav-item"
          :class="{ active: store.showTimeLedger }"
          @click="openLedger"
        >
          <span class="nav-item-left">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.75">
              <rect x="3.5" y="4.5" width="17" height="15.5" rx="2.5" />
              <path d="M7.5 2.8v3.2M16.5 2.8v3.2M3.5 9.5h17M8 13.5h2M12 13.5h2M16 13.5h1M8 16.8h4" stroke-linecap="round" />
            </svg>
            <span>时间账本</span>
          </span>
        </button>
      </div>
    </nav>

    <!-- 攻略进度（单行紧凑毛玻璃下拉选择器） -->
    <div class="sb-section sb-progress-section">
      <div class="sb-section-label">进度</div>
      <div class="sb-progress-wrap">
        <button
          type="button"
          class="sb-progress-trigger"
          :class="{ open: statusMenuOpen }"
          :aria-expanded="statusMenuOpen"
          aria-haspopup="listbox"
          aria-label="筛选攻略进度"
          @click.stop="toggleStatusMenu"
        >
          <span class="sb-progress-left">
            <span class="status-dot" :class="activeStatusOption.dotClass" />
            <span class="sb-progress-label">{{ activeStatusOption.label }}</span>
          </span>
          <span class="sb-progress-right">
            <span class="sb-progress-badge tabular-nums">{{ statusFilterCount(activeStatusOption.key) }}</span>
            <svg
              class="sb-progress-chevron"
              :class="{ rotated: statusMenuOpen }"
              viewBox="0 0 16 16"
              width="12"
              height="12"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              aria-hidden="true"
            >
              <path d="M4.2 6.2 8 10l3.8-3.8" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </span>
        </button>

        <Transition name="dropdown-pop">
          <div
            v-if="statusMenuOpen"
            class="sb-progress-menu"
            role="listbox"
            aria-label="攻略进度选项"
            @click.stop
          >
            <button
              v-for="opt in STATUS_FILTER_OPTIONS"
              :key="opt.key"
              type="button"
              role="option"
              class="sb-progress-option"
              :class="{ active: store.activeStatus === opt.key }"
              :aria-selected="store.activeStatus === opt.key"
              @click="pickStatus(opt.key)"
            >
              <span class="sb-progress-left">
                <span class="status-dot" :class="opt.dotClass" />
                <span>{{ opt.label }}</span>
              </span>
              <span class="sb-progress-option-right">
                <span class="sb-progress-option-count tabular-nums">{{ statusFilterCount(opt.key) }}</span>
                <span class="sb-progress-check" aria-hidden="true">
                  <svg
                    v-if="store.activeStatus === opt.key"
                    viewBox="0 0 16 16"
                    width="12"
                    height="12"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                  >
                    <path d="M3.5 8.4 6.6 11.4 12.6 4.8" stroke-linecap="round" stroke-linejoin="round" />
                  </svg>
                </span>
              </span>
            </button>
          </div>
        </Transition>
      </div>
    </div>

    <!-- 精简可折叠标签筛选 -->
    <div v-if="store.allTags.length > 0" class="sb-section">
      <div class="sb-section-head">
        <button class="sb-collapse-head" @click="tagsSectionOpen = !tagsSectionOpen">
          <span class="sb-section-label">标签</span>
          <svg
            class="collapse-chevron"
            :class="{ rotated: tagsSectionOpen }"
            viewBox="0 0 16 16"
            width="12"
            height="12"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
          >
            <path d="M6 4l4 4-4 4" />
          </svg>
        </button>

        <button v-if="store.filterTag" class="clear-tag-btn" @click="store.setFilterTag('')">
          清除
        </button>
      </div>

      <div v-if="tagsSectionOpen" class="tag-flow">
        <button
          v-for="item in displayedTags"
          :key="item.tag"
          class="tag-pill"
          :class="{ active: store.filterTag === item.tag }"
          @click="pickTag(item.tag)"
        >
          {{ item.tag }}
        </button>
        <button
          v-if="hasMoreTags"
          class="tag-more-btn tabular-nums"
          @click="tagsExpanded = !tagsExpanded"
        >
          {{ tagsExpanded ? '收起' : `更多 +${Math.min(store.allTags.length, 24) - 6}` }}
        </button>
      </div>
    </div>

    <!-- 游戏库：精简标题栏（按合集筛选浮层 + 排序）+ 作品列表 -->
    <div class="sb-games-wrap">
      <div class="sb-section-head">
        <span class="sb-section-label">游戏库</span>
        <div class="sb-head-right">
          <span class="sb-list-count tabular-nums">{{ store.filteredGames.length }}</span>

          <!-- 按合集筛选小图标浮层（默认收起，不占垂直空间） -->
          <div class="sb-col-filter-wrap">
            <button
              type="button"
              class="sb-add-col-btn"
              :class="{ active: colMenuOpen || store.activeCollectionId !== null }"
              :title="store.activeCollection ? `已按合集筛选：${store.activeCollection.name}` : '按系列合集筛选'"
              aria-label="按合集筛选"
              @click.stop="toggleColMenu"
            >
              <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6">
                <path d="M2.5 5.2 8 2.5l5.5 2.7L8 8 2.5 5.2Z" stroke-linejoin="round" />
                <path d="M2.5 8.4 8 11.1l5.5-2.7" stroke-linecap="round" stroke-linejoin="round" />
                <path d="M2.5 11.4 8 14.1l5.5-2.7" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>

            <Transition name="fade">
              <div v-if="colMenuOpen" class="sb-sort-menu sb-col-menu" @click.stop>
                <button
                  type="button"
                  class="sb-sort-item"
                  :class="{ active: store.activeCollectionId === null }"
                  @click="pickCollection(null)"
                >
                  <span>全部作品</span>
                  <span class="sb-col-menu-count tabular-nums">{{ store.games.length }}</span>
                </button>

                <template v-if="store.collections.length > 0">
                  <div class="sb-sort-divider" />
                  <div class="sb-col-menu-list">
                    <div
                      v-for="col in store.collections"
                      :key="col.id"
                      class="sb-sort-item sb-col-menu-row"
                      :class="{ active: store.activeCollectionId === col.id }"
                      @click="pickCollection(col.id)"
                    >
                      <span class="sb-col-menu-name" :title="col.name">{{ col.name }}</span>
                      <span class="sb-col-menu-right">
                        <button
                          type="button"
                          class="sb-col-edit-mini"
                          title="编辑合集"
                          @click.stop="openEditCollectionFromMenu(col)"
                        >
                          <svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.6">
                            <path d="M11.2 2.8l2 2-7.4 7.4-2.6.6.6-2.6 7.4-7.4z" stroke-linejoin="round" />
                          </svg>
                        </button>
                        <span class="sb-col-menu-count tabular-nums">{{ col.total_count ?? col.game_ids.length }}</span>
                      </span>
                    </div>
                  </div>
                </template>

                <div class="sb-sort-divider" />
                <button type="button" class="sb-sort-item sb-sort-flip" @click="openCreateCollectionFromMenu">
                  <span>+ 新建合集</span>
                </button>
              </div>
            </Transition>
          </div>

          <div class="sb-sort-wrap">
            <button
              type="button"
              class="sb-add-col-btn"
              :class="{ active: sortMenuOpen }"
              :title="`排序：${activeSortOption.label}（${store.sortOrder === 'asc' ? '升序' : '降序'}）`"
              aria-label="切换排序方式"
              @click.stop="toggleSortMenu"
            >
              <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.65">
                <path d="M2.5 4.5h11M4.5 8h7M6.5 11.5h3" stroke-linecap="round" />
              </svg>
            </button>

            <Transition name="fade">
              <div v-if="sortMenuOpen" class="sb-sort-menu" @click.stop>
                <button
                  v-for="opt in SORT_OPTIONS"
                  :key="opt.key"
                  type="button"
                  class="sb-sort-item"
                  :class="{ active: store.sortBy === opt.key }"
                  @click="pickSortMode(opt.key)"
                >
                  <span>{{ opt.label }}</span>
                  <span v-if="store.sortBy === opt.key" class="sb-sort-mark">
                    {{ store.sortOrder === 'asc' ? '↑' : '↓' }}
                  </span>
                </button>
                <div class="sb-sort-divider" />
                <button type="button" class="sb-sort-item sb-sort-flip" @click="flipSortOrder">
                  <span>切换为{{ store.sortOrder === 'asc' ? '降序' : '升序' }}</span>
                  <span class="sb-sort-mark">{{ store.sortOrder === 'asc' ? '↓' : '↑' }}</span>
                </button>
              </div>
            </Transition>
          </div>
        </div>
      </div>

      <!-- 仅当选中某合集时，在作品列表顶部显示可一键清除的小筛选标签 -->
      <div v-if="store.activeCollection" class="sb-active-col-bar">
        <span class="sb-active-col-chip" :title="store.activeCollection.name">
          <span class="sb-active-col-tag">合集</span>
          <span class="sb-active-col-name">{{ store.activeCollection.name }}</span>
          <button
            type="button"
            class="sb-active-col-clear"
            aria-label="清除合集筛选"
            title="清除合集筛选"
            @click="pickCollection(null)"
          >
            ×
          </button>
        </span>
      </div>

      <div class="sb-game-list">
        <button
          v-for="g in store.filteredGames"
          :key="g.id"
          class="sb-game-item"
          :class="{ active: store.activeGame?.id === g.id }"
          @click="store.selectGame(g.id, { switchToDetail: store.viewMode === 'detail' })"
        >
          <div class="sb-game-thumb">
            <img
              v-if="g.media?.cover_path || g.media?.cover_thumb_path"
              v-img-fade
              :src="mediaThumbUrl(g.media?.cover_path || g.media?.cover_thumb_path, 'sm', store.assetVersion)"
              :class="{ 'privacy-blur-img': store.shouldBlurGame(g) }"
              alt=""
              loading="lazy"
              decoding="async"
              @error="fallbackToOriginalImage($event, assetUrl(g.media?.cover_path || g.media?.cover_thumb_path, store.assetVersion))"
            />
            <span v-else class="sb-thumb-fallback">{{ g.title.slice(0, 1) }}</span>
          </div>
          <div class="sb-game-meta">
            <div class="sb-game-title">{{ g.title }}</div>
            <div class="sb-game-dev">{{ g.developer || normalizePlatformBadge(g.source_platform, g.external_ids) || '本地作品' }}</div>
          </div>
          <span class="status-dot" :class="statusDotClass(g.status)" />
        </button>

        <div v-if="store.filteredGames.length === 0" class="sb-empty">
          暂无匹配作品
        </div>
      </div>
    </div>

    <!-- 底部克制工具栏 -->
    <div class="sb-footer">
      <button class="sb-import-btn" @click="store.openImport('aggregated')">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 5v14M5 12h14" />
        </svg>
        <span>导入游戏</span>
      </button>

      <div class="sb-footer-icons">
        <button
          class="sb-icon-action"
          :class="{ 'privacy-on': store.privacyBlurMode }"
          :title="store.privacyBlurMode ? '关闭隐私模式' : '开启隐私模式'"
          @click="store.togglePrivacyBlur()"
        >
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8">
            <path v-if="store.privacyBlurMode" d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24M1 1l22 22" />
            <template v-else>
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
              <circle cx="12" cy="12" r="3" />
            </template>
          </svg>
          <span>{{ store.privacyBlurMode ? '隐私开' : '隐私' }}</span>
        </button>

        <button class="sb-icon-action" title="全局设置" @click="store.showSettingsModal = true">
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.26.6.85 1 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
          <span>设置</span>
        </button>
      </div>
    </div>
  </aside>
</template>

<style scoped>
/* Left edge trigger */
.sidebar-hotzone {
  position: fixed;
  top: 0;
  left: 0;
  width: 18px;
  height: 100vh;
  z-index: 55;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  padding-left: 4px;
  transition: opacity var(--duration-base) var(--ease-out-expo);
}

.sidebar-hotzone.hidden {
  opacity: 0;
  pointer-events: none;
}

.edge-indicator {
  width: 3px;
  height: 56px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.24);
  transition:
    background-color var(--duration-base) var(--ease-out-expo),
    height var(--duration-base) var(--ease-out-expo),
    width var(--duration-base) var(--ease-out-expo);
}

.sidebar-hotzone:hover .edge-indicator {
  width: 4px;
  height: 82px;
  background: rgba(255, 255, 255, 0.65);
}

/* Spatial isolation dimming veil */
.sidebar-scrim {
  position: fixed;
  inset: 0;
  z-index: 58;
  background: rgba(0, 0, 0, 0.48);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
}

.sidebar-scrim.is-pinned {
  background: rgba(0, 0, 0, 0.26);
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  pointer-events: none;
}

.scrim-fade-enter-active,
.scrim-fade-leave-active {
  transition: opacity 0.32s var(--ease-out-expo);
}

.scrim-fade-enter-from,
.scrim-fade-leave-to {
  opacity: 0;
}

/* Acrylic Docked Sidebar */
.hover-sidebar {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  width: 276px;
  z-index: 60;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: calc(18px + var(--titlebar-safe-top, 0px)) 14px 16px;
  background: var(--bg-acrylic);
  backdrop-filter: var(--backdrop-acrylic);
  -webkit-backdrop-filter: var(--backdrop-acrylic);
  border-right: 1px solid var(--divider-subtle);
  box-shadow: 24px 0 64px rgba(0, 0, 0, 0.55);
  transform: translateX(-100%);
  opacity: 0;
  transition:
    transform 0.36s var(--ease-out-expo),
    opacity 0.24s var(--ease-out-expo);
}

.hover-sidebar.open {
  transform: translateX(0);
  opacity: 1;
}

/* Brand Header */
.sb-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px;
}

.sb-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sb-emblem {
  flex-shrink: 0;
  opacity: 0.94;
}

.sb-brand-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.sb-title {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.22em;
  color: var(--text-primary);
}

.sb-sub {
  font-size: 11px;
  color: var(--text-muted);
}

.pin-btn {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.pin-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.pin-btn.active {
  background: var(--surface-active);
  color: var(--text-primary);
}

/* Borderless Search Trigger */
.sb-search-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 9px 11px;
  border-radius: 9px;
  border: none;
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-secondary);
  font-size: 12.5px;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.sb-search-trigger:hover {
  background: rgba(255, 255, 255, 0.09);
  color: var(--text-primary);
}

.sb-search-left {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.sb-search-left svg {
  color: var(--text-muted);
}

.sb-kbd {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.03em;
  color: var(--text-muted);
  opacity: 0.8;
}

/* Sections */
.sb-section {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.sb-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 8px;
}

.sb-section-label {
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  padding: 0 8px;
}

.sb-section-head .sb-section-label {
  padding: 0;
}

.sb-head-right {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.sb-list-count {
  font-size: 11px;
  color: var(--text-muted);
}

.sb-add-col-btn {
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.sb-add-col-btn:hover,
.sb-add-col-btn.active {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.sb-sort-wrap {
  position: relative;
  display: inline-flex;
}

.sb-sort-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  width: 162px;
  padding: 5px;
  border-radius: 11px;
  background: var(--bg-acrylic-strong);
  backdrop-filter: blur(28px) saturate(140%);
  -webkit-backdrop-filter: blur(28px) saturate(140%);
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.65);
  display: flex;
  flex-direction: column;
  gap: 2px;
  z-index: 60;
}

.sb-sort-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 6px 9px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  text-align: left;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.sb-sort-item:hover:not(.active) {
  background: rgba(255, 255, 255, 0.055);
  color: var(--text-primary);
}

.sb-sort-item.active {
  background: rgba(255, 255, 255, 0.14);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1);
  color: #f5f5f7;
  font-weight: 500;
}

.sb-sort-item.active:hover {
  background: rgba(255, 255, 255, 0.17);
}

.sb-sort-flip {
  color: var(--text-muted);
  font-size: 11.5px;
}

.sb-sort-divider {
  height: 1px;
  margin: 3px 6px;
  background: rgba(255, 255, 255, 0.07);
}

.sb-sort-mark {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-primary);
}

.sb-collapse-head {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--text-muted);
}

.sb-collapse-head:hover .sb-section-label,
.sb-collapse-head:hover {
  color: var(--text-secondary);
}

.collapse-chevron {
  transition: transform var(--duration-fast) var(--ease-out-expo);
}

.collapse-chevron.rotated {
  transform: rotate(90deg);
}

.clear-tag-btn {
  border: none;
  background: transparent;
  font-size: 11px;
  color: var(--text-secondary);
  padding: 0;
}

.clear-tag-btn:hover {
  color: var(--text-primary);
}

/* Borderless Vertical Lists */
.nav-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 7px 10px 7px 12px;
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

.nav-item::before {
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

.nav-item:hover:not(.active) {
  background: rgba(255, 255, 255, 0.048);
  color: var(--text-primary);
}

.nav-item.active {
  background: rgba(255, 255, 255, 0.125);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08);
  color: #ffffff;
  font-weight: 500;
}

.nav-item.active:hover {
  background: rgba(255, 255, 255, 0.15);
}

.nav-item.active::before {
  opacity: 1;
  transform: scaleY(1);
}

/* Compact Glassmorphic Progress Dropdown */
.sb-progress-wrap {
  position: relative;
}

.sb-progress-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  height: 34px;
  padding: 0 10px 0 12px;
  border-radius: 9px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
  color: var(--text-primary);
  font-size: 12.5px;
  font-weight: 500;
  text-align: left;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    border-color var(--duration-fast) var(--ease-out-expo),
    box-shadow var(--duration-fast) var(--ease-out-expo);
}

.sb-progress-trigger:hover {
  background: rgba(255, 255, 255, 0.085);
  border-color: rgba(255, 255, 255, 0.14);
}

.sb-progress-trigger.open {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.2);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    0 6px 20px rgba(0, 0, 0, 0.28);
}

.sb-progress-left {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.sb-progress-label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sb-progress-right {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.sb-progress-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 18px;
  padding: 0 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1;
}

.sb-progress-chevron {
  color: var(--text-muted);
  transition:
    transform var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.sb-progress-trigger:hover .sb-progress-chevron,
.sb-progress-trigger.open .sb-progress-chevron {
  color: var(--text-primary);
}

.sb-progress-chevron.rotated {
  transform: rotate(180deg);
}

.sb-progress-menu {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  right: 0;
  z-index: 75;
  padding: 5px;
  border-radius: 11px;
  background: rgba(16, 16, 20, 0.94);
  backdrop-filter: blur(28px) saturate(140%);
  -webkit-backdrop-filter: blur(28px) saturate(140%);
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow:
    0 18px 44px rgba(0, 0, 0, 0.72),
    inset 0 1px 0 rgba(255, 255, 255, 0.06);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sb-progress-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 7px 9px 7px 11px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12.5px;
  font-weight: 450;
  text-align: left;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    border-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.sb-progress-option:hover:not(.active) {
  background: rgba(255, 255, 255, 0.055);
  color: var(--text-primary);
}

.sb-progress-option.active {
  background: rgba(255, 255, 255, 0.14);
  border-color: rgba(255, 255, 255, 0.12);
  color: #ffffff;
  font-weight: 500;
}

.sb-progress-option.active:hover {
  background: rgba(255, 255, 255, 0.17);
}

.sb-progress-option-right {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.sb-progress-option-count {
  font-size: 11px;
  color: var(--text-muted);
}

.sb-progress-option.active .sb-progress-option-count {
  color: var(--text-primary);
}

.sb-progress-check {
  width: 12px;
  height: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
}

.dropdown-pop-enter-active,
.dropdown-pop-leave-active {
  transition:
    opacity 150ms var(--ease-out-expo),
    transform 150ms var(--ease-out-expo);
  transform-origin: top center;
}

.dropdown-pop-enter-from,
.dropdown-pop-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.985);
}

.nav-item-left {
  display: inline-flex;
  align-items: center;
  gap: 9px;
}

.nav-item-left svg {
  opacity: 0.78;
}

.nav-item.active .nav-item-left svg {
  opacity: 1;
}

.nav-en-tag {
  font-family: var(--font-mono);
  font-size: 9.5px;
  letter-spacing: 0.12em;
  color: var(--text-muted);
  opacity: 0.6;
}

.dot-all {
  background: rgba(255, 255, 255, 0.45);
}

.nav-count {
  font-size: 11.5px;
  color: var(--text-muted);
}

.nav-item.active .nav-count {
  color: var(--text-secondary);
}

/* Clean Collapsible Tag Group */
.tag-flow {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  padding: 2px 6px 0;
  max-height: 92px;
  overflow-y: auto;
}

.tag-pill {
  padding: 4px 9px;
  border: none;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.045);
  font-size: 11.5px;
  color: var(--text-secondary);
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.tag-pill:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.tag-pill.active {
  background: rgba(255, 255, 255, 0.16);
  color: #ffffff;
}

.tag-more-btn {
  padding: 4px 8px;
  border: none;
  border-radius: 6px;
  background: transparent;
  font-size: 11px;
  color: var(--text-muted);
}

.tag-more-btn:hover {
  color: var(--text-primary);
}

/* Compact Collection Filter Popover & Active Chip */
.sb-col-filter-wrap {
  position: relative;
}

.sb-col-menu {
  min-width: 192px;
  max-width: 230px;
}

.sb-col-menu-list {
  max-height: 200px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sb-col-menu-row {
  cursor: pointer;
}

.sb-col-menu-name {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sb-col-menu-right {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.sb-col-menu-count {
  font-size: 11px;
  color: var(--text-muted);
}

.sb-col-edit-mini {
  display: none;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--text-muted);
  align-items: center;
  justify-content: center;
}

.sb-col-menu-row:hover .sb-col-edit-mini {
  display: inline-flex;
}

.sb-col-edit-mini:hover {
  background: rgba(255, 255, 255, 0.12);
  color: var(--text-primary);
}

.sb-active-col-bar {
  display: flex;
  align-items: center;
  padding: 0 4px 2px;
}

.sb-active-col-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 3px 6px 3px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.09);
  border: 1px solid rgba(255, 255, 255, 0.1);
  font-size: 11px;
  color: var(--text-primary);
}

.sb-active-col-tag {
  font-size: 10px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.sb-active-col-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.sb-active-col-clear {
  width: 16px;
  height: 16px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.sb-active-col-clear:hover {
  background: rgba(255, 255, 255, 0.22);
  color: #ffffff;
}

.col-micro-btn {
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.col-micro-btn:hover {
  background: rgba(255, 255, 255, 0.12);
  color: var(--text-primary);
}

.col-micro-btn.danger:hover {
  background: var(--danger-bg);
  color: var(--danger-text);
}

/* Game List */
.sb-games-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 10px;
  border-top: 1px solid var(--divider-subtle);
}

.sb-game-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-right: 2px;
}

.sb-game-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  text-align: left;
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.sb-game-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 9px;
  bottom: 9px;
  width: 2px;
  border-radius: 2px;
  background: var(--active-bar);
  opacity: 0;
  transform: scaleY(0.5);
  transition:
    opacity var(--duration-fast) var(--ease-out-expo),
    transform var(--duration-fast) var(--ease-out-expo);
}

.sb-game-item:hover:not(.active) {
  background: rgba(255, 255, 255, 0.048);
}

.sb-game-item.active {
  background: rgba(255, 255, 255, 0.12);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.075);
}

.sb-game-item.active:hover {
  background: rgba(255, 255, 255, 0.145);
}

.sb-game-item.active::before {
  opacity: 1;
  transform: scaleY(1);
}

.sb-game-thumb {
  width: 28px;
  height: 38px;
  border-radius: 5px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.05);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
}

.sb-game-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.sb-thumb-fallback {
  font-family: var(--font-serif);
  font-size: 12px;
  color: var(--text-muted);
}

.sb-game-meta {
  flex: 1;
  min-width: 0;
}

.sb-game-title {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sb-game-dev {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 1px;
}

.sb-empty {
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
  padding: 20px 0;
}

/* Footer Controls */
.sb-footer {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--divider-subtle);
}

.sb-import-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  padding: 9px 12px;
  border: none;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-primary);
  font-size: 12.5px;
  font-weight: 500;
  white-space: nowrap;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo),
    transform var(--duration-fast) var(--ease-out-expo);
}

.sb-import-btn:hover {
  background: rgba(255, 255, 255, 0.16);
}

.sb-import-btn:active {
  transform: scale(0.985);
}

.sb-footer-icons {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
}

.sb-icon-action {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 7px 8px;
  border: none;
  border-radius: 8px;
  background: transparent;
  font-size: 12px;
  color: var(--text-secondary);
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.sb-icon-action:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.sb-icon-action.privacy-on {
  background: rgba(245, 158, 11, 0.14);
  color: var(--amber-text);
}
</style>
