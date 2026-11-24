<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { assetUrl, fallbackToOriginalImage, mediaThumbUrl } from '@/api/client'
import { useLibraryStore } from '@/stores/library'
import { normalizePlatformBadge } from '@/utils/platform'

const store = useLibraryStore()
const query = ref('')
const selectedIdx = ref(0)
const inputRef = ref<HTMLInputElement | null>(null)

const results = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return store.games.slice(0, 20)
  return store.games
    .filter((g) => {
      return (
        g.title.toLowerCase().includes(q) ||
        g.sub_title.toLowerCase().includes(q) ||
        g.developer.toLowerCase().includes(q) ||
        g.publisher.toLowerCase().includes(q) ||
        g.pinyin_initials.toLowerCase().includes(q) ||
        (g.tags || []).some((t) => t.toLowerCase().includes(q))
      )
    })
    .slice(0, 24)
})

watch(results, () => {
  selectedIdx.value = 0
})

function close() {
  store.showQuickSearch = false
}

function choose(gameId: number) {
  void store.selectGame(gameId, { switchToDetail: true })
  close()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (results.value.length > 0) {
      selectedIdx.value = (selectedIdx.value + 1) % results.value.length
    }
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (results.value.length > 0) {
      selectedIdx.value = (selectedIdx.value - 1 + results.value.length) % results.value.length
    }
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const picked = results.value[selectedIdx.value]
    if (picked) choose(picked.id)
  } else if (e.key === 'Escape') {
    close()
  }
}

onMounted(async () => {
  await nextTick()
  inputRef.value?.focus()
})
</script>

<template>
  <div class="modal-backdrop qs-backdrop" @click.self="close">
    <div class="qs-card" @keydown="onKeydown">
      <div class="qs-input-row">
        <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.9" class="qs-icon">
          <circle cx="11" cy="11" r="7.5" />
          <path d="m20 20-4.2-4.2" />
        </svg>
        <input
          ref="inputRef"
          v-model="query"
          type="text"
          class="qs-input"
          placeholder="搜索作品名、开发商、标签或拼音首字母…"
        />
        <span class="qs-esc">ESC</span>
      </div>

      <div class="qs-list">
        <button
          v-for="(g, idx) in results"
          :key="g.id"
          class="qs-item"
          :class="{ selected: idx === selectedIdx }"
          @mouseenter="selectedIdx = idx"
          @click="choose(g.id)"
        >
          <div class="qs-cover">
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
          <div class="qs-info">
            <div class="qs-title">{{ g.title }}</div>
            <div class="qs-sub">
              <span>{{ g.sub_title || g.developer || normalizePlatformBadge(g.source_platform, g.external_ids) || '本地作品' }}</span>
              <span v-if="g.pinyin_initials" class="qs-py">{{ g.pinyin_initials }}</span>
            </div>
          </div>
          <div class="qs-right">
            <span v-if="normalizePlatformBadge(g.source_platform, g.external_ids)" class="qs-badge">
              {{ normalizePlatformBadge(g.source_platform, g.external_ids) }}
            </span>
          </div>
        </button>

        <div v-if="results.length === 0" class="qs-empty">
          <span>未找到匹配的游戏条目</span>
          <button
            class="btn btn-primary btn-sm"
            style="margin-top: 12px"
            @click="close(); store.openImport('aggregated')"
          >
            导入新游戏
          </button>
        </div>
      </div>

      <div class="qs-footer">
        <div class="qs-hints">
          <span>↑↓ 选择</span>
          <span>↵ 打开详情</span>
        </div>
        <span class="tabular-nums">{{ results.length }} 项匹配</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.qs-backdrop {
  align-items: flex-start;
  padding-top: 13vh;
}

.qs-card {
  width: 100%;
  max-width: 620px;
  border-radius: 16px;
  overflow: hidden;
  background: var(--bg-acrylic-strong);
  backdrop-filter: blur(36px) saturate(140%);
  -webkit-backdrop-filter: blur(36px) saturate(140%);
  border: 1px solid rgba(255, 255, 255, 0.09);
  box-shadow: var(--shadow-modal);
}

.qs-input-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--divider-subtle);
}

.qs-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

.qs-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  font-size: 15px;
  color: var(--text-primary);
}

.qs-input::placeholder {
  color: var(--text-muted);
}

.qs-esc {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
  letter-spacing: 0.04em;
}

.qs-list {
  max-height: 396px;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.qs-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 9px 12px 9px 14px;
  border-radius: 10px;
  border: none;
  background: transparent;
  text-align: left;
  transition: background-color 140ms var(--ease-out-expo);
}

.qs-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 10px;
  bottom: 10px;
  width: 2px;
  border-radius: 2px;
  background: var(--active-bar);
  opacity: 0;
  transition: opacity 140ms var(--ease-out-expo);
}

.qs-item.selected {
  background: var(--surface-active);
}

.qs-item.selected::before {
  opacity: 1;
}

.qs-cover {
  width: 32px;
  height: 44px;
  border-radius: 5px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-family: var(--font-serif);
  color: var(--text-muted);
}

.qs-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.qs-info {
  flex: 1;
  min-width: 0;
}

.qs-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.qs-sub {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-secondary);
}

.qs-py {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
}

.qs-badge {
  font-family: var(--font-mono);
  font-size: 10.5px;
  padding: 2px 7px;
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-muted);
}

.qs-empty {
  padding: 40px 20px;
  text-align: center;
  font-size: 13px;
  color: var(--text-muted);
  display: flex;
  flex-direction: column;
  align-items: center;
}

.qs-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 18px;
  border-top: 1px solid var(--divider-subtle);
  font-size: 11.5px;
  color: var(--text-muted);
}

.qs-hints {
  display: flex;
  align-items: center;
  gap: 14px;
}
</style>
