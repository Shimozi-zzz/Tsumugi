<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { assetUrl, fallbackToOriginalImage, mediaThumbUrl } from '@/api/client'
import { useLibraryStore } from '@/stores/library'
import type { CollectionType } from '@/types'

const store = useLibraryStore()

const isEditMode = computed(
  () => store.collectionModalMode === 'edit' && store.collectionModalTargetId !== null,
)
const targetCollection = computed(() =>
  isEditMode.value
    ? store.collections.find((c) => c.id === store.collectionModalTargetId) || null
    : null,
)

const name = ref(targetCollection.value?.name || '')
const description = ref(targetCollection.value?.description || '')
const collectionType = ref<CollectionType>(
  targetCollection.value?.collection_type === 'custom' ? 'custom' : 'series',
)
const selectedOrder = ref<number[]>([...(targetCollection.value?.game_ids || [])])
const existingLabelMap = computed<Record<number, string>>(() => {
  const map: Record<number, string> = {}
  for (const it of targetCollection.value?.items || []) {
    if (it.relation_label) map[it.game_id] = it.relation_label
  }
  return map
})
const selectedSet = computed(() => new Set(selectedOrder.value))
const searchQuery = ref('')
const saving = ref(false)
const confirmDelete = ref(false)

const filteredCandidates = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return store.games
  return store.games.filter(
    (g) =>
      g.title.toLowerCase().includes(q) ||
      (g.sub_title || '').toLowerCase().includes(q) ||
      g.developer.toLowerCase().includes(q) ||
      g.pinyin_initials.toLowerCase().includes(q),
  )
})

function toggleGame(gameId: number) {
  if (selectedSet.value.has(gameId)) {
    selectedOrder.value = selectedOrder.value.filter((id) => id !== gameId)
  } else {
    selectedOrder.value = [...selectedOrder.value, gameId]
  }
}

function close() {
  store.showCollectionModal = false
}

async function submit() {
  const trimmed = name.value.trim()
  if (!trimmed || saving.value) return
  saving.value = true
  try {
    const items = selectedOrder.value.map((gid) => ({
      game_id: gid,
      relation_label: existingLabelMap.value[gid] || '',
    }))
    if (isEditMode.value && targetCollection.value) {
      await store.updateCollectionMeta(targetCollection.value.id, {
        name: trimmed,
        description: description.value.trim(),
        collection_type: collectionType.value,
      })
      await store.setCollectionItems(targetCollection.value.id, items)
      store.notify(`已更新合集「${trimmed}」（共 ${items.length} 部作品）`, 'success')
    } else {
      await store.createCollection(
        {
          name: trimmed,
          description: description.value.trim(),
          collection_type: collectionType.value,
          items,
        },
        [],
        false,
      )
    }
    close()
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '保存合集失败', 'error')
  } finally {
    saving.value = false
  }
}

async function removeCollection() {
  if (!targetCollection.value) return
  if (!confirmDelete.value) {
    confirmDelete.value = true
    return
  }
  await store.deleteCollection(targetCollection.value.id)
  close()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') close()
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="modal-backdrop" @click.self="close">
    <div class="modal-card col-modal">
      <div class="modal-head">
        <div>
          <h2>{{ isEditMode ? '编辑合集' : '新建合集' }}</h2>
        </div>
        <button type="button" class="close-icon-btn" aria-label="关闭" @click="close">
          <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" />
          </svg>
        </button>
      </div>

      <div class="modal-body">
        <div class="field-row">
          <div class="field field-grow">
            <label>合集名称</label>
            <input
              v-model="name"
              class="input"
              maxlength="64"
              placeholder="例如：白色相簿系列、Key 社巡礼、命运石之门"
              autofocus
              @keydown.enter="submit"
            />
          </div>

          <div class="field field-type">
            <label>类型</label>
            <div class="type-seg" role="radiogroup" aria-label="合集类型">
              <button
                type="button"
                class="type-opt"
                :class="{ active: collectionType === 'series' }"
                @click="collectionType = 'series'"
              >
                系列
              </button>
              <button
                type="button"
                class="type-opt"
                :class="{ active: collectionType === 'custom' }"
                @click="collectionType = 'custom'"
              >
                自定义
              </button>
            </div>
          </div>
        </div>

        <div class="field">
          <label>简短说明（可选）</label>
          <input
            v-model="description"
            class="input"
            maxlength="240"
            placeholder="例如：建议按本篇 → FD → 外传顺序游玩"
          />
        </div>

        <div class="field">
          <div class="members-head">
            <label>收录作品（按勾选顺序排位，可在合集详情内随时拖拽调整）</label>
            <span class="selected-count tabular-nums">已选 {{ selectedOrder.length }} / {{ store.games.length }}</span>
          </div>

          <input
            v-model="searchQuery"
            class="input member-search"
            placeholder="筛选游戏名称或拼音…"
          />

          <div class="member-list">
            <button
              v-for="g in filteredCandidates"
              :key="g.id"
              type="button"
              class="member-row"
              :class="{ checked: selectedSet.has(g.id) }"
              @click="toggleGame(g.id)"
            >
              <span class="check-box" :class="{ on: selectedSet.has(g.id) }">
                <svg v-if="selectedSet.has(g.id)" viewBox="0 0 14 14" width="10" height="10" fill="none" stroke="currentColor" stroke-width="2.2">
                  <path d="M2.5 7.2L5.5 10.2L11.5 3.8" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </span>

              <div class="member-thumb">
                <img
                  v-if="g.media?.cover_path || g.media?.cover_thumb_path"
                  :src="mediaThumbUrl(g.media?.cover_path || g.media?.cover_thumb_path, 'sm', store.assetVersion)"
                  :class="{ 'privacy-blur-img': store.shouldBlurGame(g) }"
                  alt=""
                  loading="lazy"
                  decoding="async"
                  @error="fallbackToOriginalImage($event, assetUrl(g.media?.cover_path || g.media?.cover_thumb_path, store.assetVersion))"
                />
                <span v-else>{{ g.title.slice(0, 1) }}</span>
              </div>

              <div class="member-info">
                <div class="member-title">{{ g.title }}</div>
                <div class="member-dev">{{ g.developer || g.source_platform }}</div>
              </div>

              <span v-if="selectedSet.has(g.id)" class="member-order-num tabular-nums">
                {{ String(selectedOrder.indexOf(g.id) + 1).padStart(2, '0') }}
              </span>
            </button>

            <div v-if="filteredCandidates.length === 0" class="member-empty">
              无匹配作品
            </div>
          </div>
        </div>
      </div>

      <div class="modal-foot">
        <button
          v-if="isEditMode"
          type="button"
          class="btn btn-danger btn-sm"
          @click="removeCollection"
        >
          {{ confirmDelete ? '确认删除（保留游戏本体）' : '删除合集' }}
        </button>
        <div class="foot-right">
          <button type="button" class="btn btn-ghost" @click="close">取消</button>
          <button
            type="button"
            class="btn btn-primary"
            :disabled="!name.trim() || saving"
            @click="submit"
          >
            {{ saving ? '保存中…' : isEditMode ? '保存更改' : '创建合集' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.col-modal {
  max-width: 520px;
}

.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 20px 24px 15px;
  border-bottom: 1px solid var(--divider-subtle);
}

.modal-head h2 {
  margin: 0;
  font-size: 16.5px;
  font-weight: 600;
}

.modal-desc {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}

.close-icon-btn {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.close-icon-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.modal-body {
  padding: 18px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.field-row {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.field-grow {
  flex: 1;
  min-width: 0;
}

.field-type {
  flex-shrink: 0;
}

.type-seg {
  display: inline-flex;
  padding: 3px;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border-subtle);
  gap: 2px;
}

.type-opt {
  padding: 6px 12px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background-color 140ms ease, color 140ms ease;
}

.type-opt.active {
  background: #f5f5f7;
  color: #0a0a0c;
  font-weight: 600;
}

.member-order-num {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.field label {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-secondary);
}

.members-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.selected-count {
  font-size: 11.5px;
  color: var(--text-muted);
}

.member-search {
  padding: 7px 11px;
  font-size: 12.5px;
}

.member-list {
  max-height: 260px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px;
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.025);
}

.member-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 7px 9px;
  border: none;
  border-radius: 8px;
  background: transparent;
  text-align: left;
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.member-row:hover {
  background: var(--surface-hover);
}

.member-row.checked {
  background: var(--surface-active);
}

.check-box {
  width: 16px;
  height: 16px;
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.08);
  color: #0a0a0c;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.check-box.on {
  background: #f5f5f7;
}

.member-thumb {
  width: 24px;
  height: 32px;
  border-radius: 4px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-family: var(--font-serif);
  font-size: 11px;
  color: var(--text-muted);
}

.member-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.member-info {
  flex: 1;
  min-width: 0;
}

.member-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.member-dev {
  font-size: 11px;
  color: var(--text-muted);
}

.member-empty {
  padding: 24px 0;
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
}

.modal-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 14px 24px;
  border-top: 1px solid var(--divider-subtle);
}

.foot-right {
  margin-left: auto;
  display: flex;
  gap: 10px;
}
</style>
