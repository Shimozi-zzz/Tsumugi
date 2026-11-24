<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { assetUrl, fallbackToOriginalImage, mediaThumbUrl } from '@/api/client'
import { useLibraryStore } from '@/stores/library'
import type { CollectionItem, CollectionWorkSummary } from '@/types'

const emit = defineEmits<{
  'open-game': [gameId: number]
  'browse-in-shelf': [collectionId: number]
}>()

const store = useLibraryStore()

const RELATION_PRESETS = ['本篇', '前篇', '后篇', 'FD', '外传', '续作']

const activeCollectionId = ref<number | null>(null)
const addDrawerOpen = ref(false)
const addSearchQuery = ref('')
const addDefaultLabel = ref('')
const savingOrder = ref(false)
const confirmDeleteId = ref<number | null>(null)

// 拖拽排序状态
const dragFromIndex = ref<number | null>(null)
const dragOverIndex = ref<number | null>(null)

// 行内关系标签编辑状态
const editingLabelGameId = ref<number | null>(null)
const editingLabelDraft = ref('')

const activeCollection = computed<CollectionItem | null>(() => {
  if (activeCollectionId.value === null) return null
  return store.collections.find((c) => c.id === activeCollectionId.value) || null
})

watch(
  () => store.collections,
  (list) => {
    if (activeCollectionId.value !== null && !list.some((c) => c.id === activeCollectionId.value)) {
      activeCollectionId.value = null
    }
  },
)

const orderedItems = computed<CollectionWorkSummary[]>(() => {
  const col = activeCollection.value
  if (!col) return []
  return [...(col.items || [])].sort((a, b) => a.position - b.position)
})

const addableGames = computed(() => {
  const col = activeCollection.value
  if (!col) return []
  const existing = new Set(col.game_ids)
  const q = addSearchQuery.value.trim().toLowerCase()
  return store.games.filter((g) => {
    if (existing.has(g.id)) return false
    if (!q) return true
    return (
      g.title.toLowerCase().includes(q) ||
      (g.sub_title || '').toLowerCase().includes(q) ||
      (g.developer || '').toLowerCase().includes(q) ||
      (g.pinyin_initials || '').toLowerCase().includes(q)
    )
  })
})

function openDetail(colId: number) {
  activeCollectionId.value = colId
  addDrawerOpen.value = false
  addSearchQuery.value = ''
  confirmDeleteId.value = null
  editingLabelGameId.value = null
}

function backToGrid() {
  activeCollectionId.value = null
  addDrawerOpen.value = false
  confirmDeleteId.value = null
  editingLabelGameId.value = null
}

function coverThumbSrc(item: CollectionWorkSummary): string {
  if (item.cover_path) {
    return mediaThumbUrl(item.cover_path, 'sm', store.assetVersion)
  }
  return item.cover_thumb_url || ''
}

function coverFallbackSrc(item: CollectionWorkSummary): string {
  return item.cover_path ? assetUrl(item.cover_path, store.assetVersion) : ''
}

function isItemBlurred(item: CollectionWorkSummary): boolean {
  return store.privacyBlurMode && Boolean(item.is_nsfw)
}

function completionPercent(col: CollectionItem): number {
  const total = col.total_count || col.items?.length || 0
  if (total <= 0) return 0
  return Math.min(100, Math.round(((col.completed_count || 0) / total) * 100))
}

function statusDotClass(status: string): string {
  const s = (status || '').toLowerCase()
  if (s === 'playing') return 'status-dot-playing'
  if (s === 'done' || s === 'completed') return 'status-dot-done'
  return 'status-dot-todo'
}

function statusText(status: string): string {
  const s = (status || '').toLowerCase()
  if (s === 'playing') return '攻略中'
  if (s === 'done' || s === 'completed') return '已通关'
  return '未开始'
}

async function persistItemsOrder(nextItems: CollectionWorkSummary[]) {
  const col = activeCollection.value
  if (!col || savingOrder.value) return
  savingOrder.value = true
  try {
    await store.setCollectionItems(
      col.id,
      nextItems.map((it) => ({
        game_id: it.game_id,
        relation_label: it.relation_label || '',
      })),
    )
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '保存排序失败', 'error')
  } finally {
    savingOrder.value = false
  }
}

async function moveItem(index: number, delta: -1 | 1) {
  const list = [...orderedItems.value]
  const target = index + delta
  if (target < 0 || target >= list.length) return
  const [moved] = list.splice(index, 1)
  list.splice(target, 0, moved)
  await persistItemsOrder(list)
}

function onDragStart(index: number, ev: DragEvent) {
  dragFromIndex.value = index
  if (ev.dataTransfer) {
    ev.dataTransfer.effectAllowed = 'move'
    ev.dataTransfer.setData('text/plain', String(index))
  }
}

function onDragOver(index: number, ev: DragEvent) {
  ev.preventDefault()
  if (ev.dataTransfer) {
    ev.dataTransfer.dropEffect = 'move'
  }
  dragOverIndex.value = index
}

function onDragEnd() {
  dragFromIndex.value = null
  dragOverIndex.value = null
}

async function onDrop(targetIndex: number, ev: DragEvent) {
  ev.preventDefault()
  const from = dragFromIndex.value
  dragFromIndex.value = null
  dragOverIndex.value = null
  if (from === null || from === targetIndex) return
  const list = [...orderedItems.value]
  if (from < 0 || from >= list.length || targetIndex < 0 || targetIndex >= list.length) return
  const [moved] = list.splice(from, 1)
  list.splice(targetIndex, 0, moved)
  await persistItemsOrder(list)
}

function startEditLabel(item: CollectionWorkSummary) {
  editingLabelGameId.value = item.game_id
  editingLabelDraft.value = item.relation_label || ''
}

async function saveRelationLabel(gameId: number, explicitLabel?: string) {
  const col = activeCollection.value
  if (!col) return
  const nextLabel = (explicitLabel !== undefined ? explicitLabel : editingLabelDraft.value).trim().slice(0, 32)
  editingLabelGameId.value = null
  const currentItem = orderedItems.value.find((it) => it.game_id === gameId)
  if (currentItem && (currentItem.relation_label || '') === nextLabel) return
  const nextList = orderedItems.value.map((it) =>
    it.game_id === gameId ? { ...it, relation_label: nextLabel } : it,
  )
  await persistItemsOrder(nextList)
}

async function handleAddGame(gameId: number) {
  const col = activeCollection.value
  if (!col) return
  try {
    await store.addCollectionItem(col.id, gameId, addDefaultLabel.value.trim())
    store.notify('已加入合集', 'success')
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '添加失败', 'error')
  }
}

async function handleRemoveGame(item: CollectionWorkSummary) {
  const col = activeCollection.value
  if (!col) return
  try {
    await store.removeCollectionItem(col.id, item.game_id)
    store.notify(`已将《${item.title}》移出合集`, 'info')
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '移出失败', 'error')
  }
}

async function handleDeleteCollection(col: CollectionItem) {
  if (confirmDeleteId.value !== col.id) {
    confirmDeleteId.value = col.id
    return
  }
  try {
    await store.deleteCollection(col.id)
    confirmDeleteId.value = null
    activeCollectionId.value = null
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '删除合集失败', 'error')
  }
}
</script>

<template>
  <section class="series-stage">
    <!-- 视图 B：单个合集详情与顺序编排面板 -->
    <div v-if="activeCollection" class="series-detail-wrap">
      <div class="detail-top-bar">
        <button type="button" class="ghost-back-btn" @click="backToGrid">
          <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.75">
            <path d="M12.5 15L7.5 10l5-5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span>返回系列合集</span>
        </button>

        <div class="detail-top-actions">
          <button
            v-if="orderedItems.length > 0"
            type="button"
            class="btn btn-sm"
            @click="emit('browse-in-shelf', activeCollection.id)"
          >
            在 3D 回廊中浏览
          </button>
          <button
            type="button"
            class="btn btn-sm"
            :class="{ 'btn-primary': addDrawerOpen }"
            @click="addDrawerOpen = !addDrawerOpen"
          >
            {{ addDrawerOpen ? '收起添加' : '+ 添加作品' }}
          </button>
          <button
            type="button"
            class="btn btn-sm btn-ghost"
            @click="store.openEditCollectionModal(activeCollection.id)"
          >
            编辑信息
          </button>
          <button
            type="button"
            class="btn btn-sm btn-danger"
            @click="handleDeleteCollection(activeCollection)"
          >
            {{ confirmDeleteId === activeCollection.id ? '确认删除（保留游戏）' : '删除合集' }}
          </button>
        </div>
      </div>

      <!-- 合集抬头与进度 -->
      <div class="detail-header-card">
        <div class="detail-header-main">
          <div class="detail-title-row">
            <h2>{{ activeCollection.name }}</h2>
            <span class="type-badge">
              {{ activeCollection.collection_type === 'custom' ? '自定义合集' : '系列合集' }}
            </span>
          </div>
          <p v-if="activeCollection.description" class="detail-desc">
            {{ activeCollection.description }}
          </p>
        </div>

        <div class="detail-progress-box">
          <div class="detail-progress-meta tabular-nums">
            <span>共 {{ activeCollection.total_count }} 部</span>
            <span class="dot-sep">·</span>
            <span>已通关 {{ activeCollection.completed_count }}/{{ activeCollection.total_count }}</span>
          </div>
          <div class="progress-track">
            <div
              class="progress-fill"
              :class="{ done: completionPercent(activeCollection) === 100 && activeCollection.total_count > 0 }"
              :style="{ width: `${completionPercent(activeCollection)}%` }"
            />
          </div>
        </div>
      </div>

      <!-- 快捷搜索添加作品抽屉 -->
      <Transition name="fade">
        <div v-if="addDrawerOpen" class="add-drawer">
          <div class="add-drawer-controls">
            <input
              v-model="addSearchQuery"
              class="input add-search-input"
              placeholder="搜索库内作品名称、原名或拼音以加入合集…"
            />
            <input
              v-model="addDefaultLabel"
              class="input add-label-input"
              maxlength="32"
              placeholder="可选默认标签（如 本篇 / FD）"
            />
          </div>
          <div class="add-candidates">
            <button
              v-for="g in addableGames.slice(0, 18)"
              :key="g.id"
              type="button"
              class="add-candidate-row"
              @click="handleAddGame(g.id)"
            >
              <div class="mini-cover">
                <img
                  v-if="g.media?.cover_path || g.media?.cover_thumb_path"
                  :src="mediaThumbUrl(g.media?.cover_path || g.media?.cover_thumb_path, 'sm', store.assetVersion)"
                  :class="{ 'privacy-blur-img': store.shouldBlurGame(g) }"
                  alt=""
                  loading="lazy"
                  @error="fallbackToOriginalImage($event, assetUrl(g.media?.cover_path || g.media?.cover_thumb_path, store.assetVersion))"
                />
                <span v-else>{{ g.title.slice(0, 1) }}</span>
              </div>
              <div class="add-cand-info">
                <div class="add-cand-title">{{ g.title }}</div>
                <div class="add-cand-sub">{{ g.developer || g.source_platform }}</div>
              </div>
              <span class="add-cand-plus">+ 加入</span>
            </button>
            <div v-if="addableGames.length === 0" class="add-empty">
              {{ addSearchQuery.trim() ? '无匹配的可添加作品' : '库内全部作品均已收录于此合集' }}
            </div>
          </div>
        </div>
      </Transition>

      <!-- 按游玩顺序排列的作品列表（支持拖拽排序与上下微调按钮） -->
      <div v-if="orderedItems.length > 0" class="ordered-list">
        <div class="ordered-list-hint">
          <span>按游玩顺序排列 · 支持拖拽行或点击上下按钮微调顺序，点击作品进入详情</span>
          <span v-if="savingOrder" class="saving-tip">正在保存顺序…</span>
        </div>

        <div
          v-for="(item, idx) in orderedItems"
          :key="item.game_id"
          class="order-row"
          :class="{
            dragging: dragFromIndex === idx,
            'drag-over': dragOverIndex === idx && dragFromIndex !== idx,
          }"
          draggable="true"
          @dragstart="onDragStart(idx, $event)"
          @dragover="onDragOver(idx, $event)"
          @drop="onDrop(idx, $event)"
          @dragend="onDragEnd"
        >
          <span class="drag-grip" title="拖拽调整顺序" aria-hidden="true">
            <svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor">
              <circle cx="5.5" cy="4" r="1.15" />
              <circle cx="10.5" cy="4" r="1.15" />
              <circle cx="5.5" cy="8" r="1.15" />
              <circle cx="10.5" cy="8" r="1.15" />
              <circle cx="5.5" cy="12" r="1.15" />
              <circle cx="10.5" cy="12" r="1.15" />
            </svg>
          </span>

          <span class="seq-num tabular-nums">{{ String(idx + 1).padStart(2, '0') }}</span>

          <button
            type="button"
            class="row-work-trigger"
            @click="emit('open-game', item.game_id)"
          >
            <div class="row-cover">
              <img
                v-if="coverThumbSrc(item)"
                :src="coverThumbSrc(item)"
                :alt="item.title"
                :class="{ 'privacy-blur-img': isItemBlurred(item) }"
                loading="lazy"
                @error="fallbackToOriginalImage($event, coverFallbackSrc(item))"
              />
              <span v-else>{{ item.title.slice(0, 1) }}</span>
            </div>

            <div class="row-work-info">
              <div class="row-work-title-line">
                <span class="row-work-title">{{ item.title }}</span>
                <span v-if="item.rating_overall != null" class="row-rating tabular-nums">
                  ★ {{ Number(item.rating_overall).toFixed(1) }}
                </span>
              </div>
              <div class="row-work-sub-line">
                <span class="status-dot" :class="statusDotClass(item.play_status)" />
                <span>{{ statusText(item.play_status) }}</span>
                <span v-if="item.sub_title" class="row-work-orig">· {{ item.sub_title }}</span>
              </div>
            </div>
          </button>

          <!-- 可编辑关系标签（如 本篇 / 前篇 / 后篇 / FD / 外传） -->
          <div class="relation-cell">
            <div v-if="editingLabelGameId === item.game_id" class="relation-editor">
              <input
                v-model="editingLabelDraft"
                class="input relation-input"
                maxlength="32"
                placeholder="如 本篇 / FD"
                autofocus
                @keydown.enter="saveRelationLabel(item.game_id)"
                @keydown.esc="editingLabelGameId = null"
                @blur="saveRelationLabel(item.game_id)"
              />
              <div class="relation-presets">
                <button
                  v-for="preset in RELATION_PRESETS"
                  :key="preset"
                  type="button"
                  class="preset-chip"
                  @mousedown.prevent="saveRelationLabel(item.game_id, preset)"
                >
                  {{ preset }}
                </button>
                <button
                  v-if="item.relation_label"
                  type="button"
                  class="preset-chip clear"
                  @mousedown.prevent="saveRelationLabel(item.game_id, '')"
                >
                  清空
                </button>
              </div>
            </div>
            <button
              v-else
              type="button"
              class="relation-badge-btn"
              :class="{ empty: !item.relation_label }"
              title="点击编辑关系标签（如 本篇 / 前篇 / FD）"
              @click="startEditLabel(item)"
            >
              {{ item.relation_label || '+ 关系标签' }}
            </button>
          </div>

          <!-- 上下微调 + 移出按钮 -->
          <div class="row-controls">
            <button
              type="button"
              class="micro-icon-btn"
              title="上移一位"
              :disabled="idx === 0 || savingOrder"
              @click="moveItem(idx, -1)"
            >
              ↑
            </button>
            <button
              type="button"
              class="micro-icon-btn"
              title="下移一位"
              :disabled="idx === orderedItems.length - 1 || savingOrder"
              @click="moveItem(idx, 1)"
            >
              ↓
            </button>
            <button
              type="button"
              class="micro-icon-btn danger"
              title="移出合集（不删除游戏）"
              @click="handleRemoveGame(item)"
            >
              ×
            </button>
          </div>
        </div>
      </div>

      <div v-else class="detail-empty-box">
        <p>此合集尚未收录作品</p>
        <button type="button" class="btn btn-primary btn-sm" @click="addDrawerOpen = true">
          + 添加作品
        </button>
      </div>
    </div>

    <!-- 视图 A：堆叠封面毛玻璃合集卡片总览 -->
    <div v-else class="series-grid-wrap">
      <div v-if="store.collections.length === 0" class="series-empty-state">
        <h2>尚未创建系列合集</h2>
        <p>将同一系列或关联作品归档在一起，按本篇、FD、外传顺序梳理游玩脉络。</p>
        <button type="button" class="btn btn-primary" @click="store.openCreateCollectionModal()">
          + 新建系列合集
        </button>
      </div>

      <div v-else class="series-card-grid">
        <button
          v-for="col in store.collections"
          :key="col.id"
          type="button"
          class="series-card"
          @click="openDetail(col.id)"
        >
          <!-- 堆叠封面缩略图叠层（最多展示前 3 部） -->
          <div class="cover-stack-stage">
            <template v-if="(col.items || []).length > 0">
              <div
                v-for="(item, idx) in col.items.slice(0, 3)"
                :key="item.game_id"
                class="stack-layer"
                :class="`layer-${idx}`"
              >
                <img
                  v-if="coverThumbSrc(item)"
                  :src="coverThumbSrc(item)"
                  :alt="item.title"
                  :class="{ 'privacy-blur-img': isItemBlurred(item) }"
                  loading="lazy"
                  decoding="async"
                  @error="fallbackToOriginalImage($event, coverFallbackSrc(item))"
                />
                <div v-else class="stack-fallback">{{ item.title.slice(0, 2) }}</div>
              </div>
            </template>
            <div v-else class="stack-empty-placeholder">
              <span>{{ col.name.slice(0, 1) }}</span>
            </div>
          </div>

          <!-- 卡片底部信息 -->
          <div class="series-card-body">
            <div class="series-card-head">
              <h3 class="series-card-title" :title="col.name">{{ col.name }}</h3>
              <span class="series-type-pill">
                {{ col.collection_type === 'custom' ? '自定义' : '系列' }}
              </span>
            </div>
            <p v-if="col.description" class="series-card-desc">{{ col.description }}</p>

            <div class="series-card-foot">
              <div class="series-stats tabular-nums">
                <span>{{ col.total_count }} 部作品</span>
                <span class="dot-sep">·</span>
                <span>已通关 {{ col.completed_count }}/{{ col.total_count }}</span>
              </div>
              <div class="progress-track">
                <div
                  class="progress-fill"
                  :class="{ done: completionPercent(col) === 100 && col.total_count > 0 }"
                  :style="{ width: `${completionPercent(col)}%` }"
                />
              </div>
            </div>
          </div>
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.series-stage {
  position: relative;
  z-index: 4;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 56px 56px;
  user-select: text;
}

/* Overview Grid */
.series-grid-wrap {
  max-width: 1220px;
  margin: 0 auto;
}

.series-empty-state {
  min-height: 52vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 10px;
}

.series-empty-state h2 {
  margin: 0;
  font-family: var(--font-serif);
  font-size: 20px;
  font-weight: 500;
  color: var(--text-primary);
}

.series-empty-state p {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--text-secondary);
  max-width: 420px;
}

.series-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(272px, 1fr));
  gap: 20px;
}

.series-card {
  display: flex;
  flex-direction: column;
  text-align: left;
  padding: 18px;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(16, 16, 20, 0.66);
  backdrop-filter: blur(22px) saturate(135%);
  -webkit-backdrop-filter: blur(22px) saturate(135%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.06),
    0 18px 40px rgba(0, 0, 0, 0.42);
  cursor: pointer;
  transition:
    transform var(--duration-base) var(--ease-out-expo),
    border-color var(--duration-fast) var(--ease-out-expo),
    background-color var(--duration-fast) var(--ease-out-expo),
    box-shadow var(--duration-base) var(--ease-out-expo);
}

.series-card:hover {
  transform: translateY(-4px);
  border-color: rgba(255, 255, 255, 0.16);
  background: rgba(22, 22, 27, 0.78);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.1),
    0 24px 54px rgba(0, 0, 0, 0.56);
}

/* Stacked 3-Cover Fan Stage */
.cover-stack-stage {
  position: relative;
  height: 158px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 14px;
}

.stack-layer {
  position: absolute;
  width: 98px;
  height: 140px;
  border-radius: 8px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.12);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.6);
  transition: transform var(--duration-base) var(--ease-out-expo);
}

.stack-layer img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.stack-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-serif);
  font-size: 16px;
  color: var(--text-muted);
}

.stack-layer.layer-0 {
  z-index: 3;
  transform: translateX(0) rotate(0deg);
}

.stack-layer.layer-1 {
  z-index: 2;
  transform: translateX(28px) translateY(5px) rotate(5deg) scale(0.94);
  opacity: 0.88;
}

.stack-layer.layer-2 {
  z-index: 1;
  transform: translateX(-28px) translateY(7px) rotate(-5.5deg) scale(0.9);
  opacity: 0.74;
}

.series-card:hover .stack-layer.layer-0 {
  transform: translateY(-4px) scale(1.02);
}

.series-card:hover .stack-layer.layer-1 {
  transform: translateX(36px) translateY(3px) rotate(7deg) scale(0.95);
}

.series-card:hover .stack-layer.layer-2 {
  transform: translateX(-36px) translateY(5px) rotate(-7.5deg) scale(0.91);
}

.stack-empty-placeholder {
  width: 98px;
  height: 140px;
  border-radius: 8px;
  border: 1px dashed rgba(255, 255, 255, 0.14);
  background: rgba(255, 255, 255, 0.03);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-serif);
  font-size: 28px;
  color: var(--text-muted);
}

.series-card-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
}

.series-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.series-card-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.series-type-pill,
.type-badge {
  flex-shrink: 0;
  padding: 2px 7px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.07);
  color: var(--text-secondary);
  font-size: 10.5px;
  font-weight: 500;
}

.series-card-desc {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.series-card-foot {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 4px;
}

.series-stats {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--text-secondary);
}

.dot-sep {
  opacity: 0.45;
}

.progress-track {
  width: 100%;
  height: 3px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 999px;
  background: rgba(244, 244, 245, 0.72);
  transition: width 320ms var(--ease-out-expo);
}

.progress-fill.done {
  background: var(--emerald);
}

/* Detail Panel */
.series-detail-wrap {
  max-width: 980px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.detail-top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.ghost-back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-primary);
  font-size: 12.5px;
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.ghost-back-btn:hover {
  background: rgba(255, 255, 255, 0.12);
}

.detail-top-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.detail-header-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 18px 22px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(16, 16, 20, 0.72);
  backdrop-filter: blur(22px);
  -webkit-backdrop-filter: blur(22px);
  flex-wrap: wrap;
}

.detail-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.detail-title-row h2 {
  margin: 0;
  font-family: var(--font-serif);
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}

.detail-desc {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.detail-progress-box {
  min-width: 190px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.detail-progress-meta {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

/* Add Game Drawer */
.add-drawer {
  padding: 14px 16px;
  border-radius: 13px;
  border: 1px solid rgba(255, 255, 255, 0.09);
  background: rgba(16, 16, 20, 0.8);
  backdrop-filter: blur(22px);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.add-drawer-controls {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.add-search-input {
  flex: 1;
  min-width: 220px;
  font-size: 12.5px;
}

.add-label-input {
  width: 200px;
  font-size: 12.5px;
}

.add-candidates {
  max-height: 210px;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 6px;
}

.add-candidate-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.03);
  text-align: left;
  cursor: pointer;
  transition: background-color 140ms ease, border-color 140ms ease;
}

.add-candidate-row:hover {
  background: rgba(255, 255, 255, 0.09);
  border-color: rgba(255, 255, 255, 0.14);
}

.mini-cover {
  width: 28px;
  height: 38px;
  border-radius: 4px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.06);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: var(--text-muted);
}

.mini-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.add-cand-info {
  flex: 1;
  min-width: 0;
}

.add-cand-title {
  font-size: 12.5px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.add-cand-sub {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.add-cand-plus {
  font-size: 11.5px;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.add-empty {
  grid-column: 1 / -1;
  padding: 18px 0;
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
}

/* Ordered List */
.ordered-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ordered-list-hint {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11.5px;
  color: var(--text-muted);
  padding: 0 4px;
}

.saving-tip {
  color: var(--text-secondary);
}

.order-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.07);
  background: rgba(16, 16, 20, 0.7);
  backdrop-filter: blur(18px);
  transition:
    border-color 140ms ease,
    background-color 140ms ease,
    opacity 140ms ease;
}

.order-row:hover {
  border-color: rgba(255, 255, 255, 0.14);
  background: rgba(24, 24, 30, 0.8);
}

.order-row.dragging {
  opacity: 0.45;
}

.order-row.drag-over {
  border-color: rgba(245, 245, 247, 0.55);
  box-shadow: inset 0 2px 0 rgba(245, 245, 247, 0.65);
}

.drag-grip {
  color: var(--text-muted);
  cursor: grab;
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  opacity: 0.6;
}

.order-row:hover .drag-grip {
  opacity: 1;
}

.seq-num {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-muted);
  min-width: 22px;
  flex-shrink: 0;
}

.row-work-trigger {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0;
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.row-cover {
  width: 38px;
  height: 52px;
  border-radius: 5px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.09);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-serif);
  font-size: 13px;
  color: var(--text-muted);
}

.row-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.row-work-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.row-work-title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.row-work-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.row-work-trigger:hover .row-work-title {
  color: #ffffff;
}

.row-rating {
  flex-shrink: 0;
  font-size: 11.5px;
  color: var(--amber-text);
  background: var(--amber-bg);
  padding: 1px 6px;
  border-radius: 999px;
}

.row-work-sub-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--text-muted);
  min-width: 0;
}

.row-work-orig {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Relation Label Editor */
.relation-cell {
  position: relative;
  flex-shrink: 0;
}

.relation-badge-btn {
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
  font-size: 11.5px;
  cursor: pointer;
  transition: background-color 140ms ease, border-color 140ms ease;
}

.relation-badge-btn.empty {
  border-style: dashed;
  border-color: rgba(255, 255, 255, 0.1);
  background: transparent;
  color: var(--text-muted);
}

.relation-badge-btn:hover {
  background: rgba(255, 255, 255, 0.14);
  color: #ffffff;
}

.relation-editor {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.relation-input {
  width: 120px;
  padding: 4px 8px;
  font-size: 12px;
}

.relation-presets {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  z-index: 20;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  width: 210px;
  padding: 6px;
  border-radius: 9px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(16, 16, 20, 0.96);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.72);
}

.preset-chip {
  padding: 3px 8px;
  border: none;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
  font-size: 11px;
  cursor: pointer;
}

.preset-chip:hover {
  background: #f5f5f7;
  color: #0a0a0c;
}

.preset-chip.clear {
  background: var(--danger-bg);
  color: var(--danger-text);
}

/* Reorder & Remove Controls */
.row-controls {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.micro-icon-btn {
  width: 26px;
  height: 26px;
  padding: 0;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-secondary);
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color 140ms ease, color 140ms ease;
}

.micro-icon-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.14);
  color: #ffffff;
}

.micro-icon-btn:disabled {
  opacity: 0.28;
  cursor: not-allowed;
}

.micro-icon-btn.danger:hover:not(:disabled) {
  background: var(--danger-bg);
  border-color: rgba(239, 68, 68, 0.35);
  color: var(--danger-text);
}

.detail-empty-box {
  padding: 48px 20px;
  border-radius: 14px;
  border: 1px dashed rgba(255, 255, 255, 0.1);
  background: rgba(16, 16, 20, 0.5);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--text-secondary);
  font-size: 13px;
}

.detail-empty-box p {
  margin: 0;
}
</style>
