<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { assetProxyUrl, gamesApi, scraperApi } from '@/api/client'
import { useLibraryStore } from '@/stores/library'
import type { BangumiSyncResponse, Game, ScrapedGameItem } from '@/types'

const props = defineProps<{
  game: Game
}>()

const emit = defineEmits<{
  close: []
  synced: [res: BangumiSyncResponse]
}>()

const store = useLibraryStore()

const query = ref((props.game.sub_title || props.game.title || '').trim())
const loading = ref(false)
const searchedOnce = ref(false)
const items = ref<ScrapedGameItem[]>([])
const bindingId = ref('')

const quickKeywords = computed(() => {
  const title = (props.game.title || '').trim()
  const sub = (props.game.sub_title || '').trim()
  if (!title || !sub || title === sub) return []
  return [
    { label: '原名', value: sub },
    { label: '中文名', value: title },
  ]
})

async function runSearch() {
  const q = query.value.trim()
  if (!q) return
  loading.value = true
  searchedOnce.value = true
  try {
    const res = await scraperApi.search(q, 'bgm', 8)
    items.value = res.items || []
  } catch (err) {
    items.value = []
    store.notify(err instanceof Error ? err.message : 'Bangumi 检索失败', 'warning')
  } finally {
    loading.value = false
  }
}

async function bindAndSync(item: ScrapedGameItem) {
  if (!item.external_id || bindingId.value) return
  bindingId.value = item.external_id
  try {
    const res = await gamesApi.syncBangumi(props.game.id, item.external_id)
    await store.refreshGame(props.game.id)
    store.notify(`已同步至 Bangumi · ${res.bangumi_type_label}`, 'success')
    emit('synced', res)
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '关联并同步失败', 'error')
  } finally {
    bindingId.value = ''
  }
}

function handleKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Escape' && !bindingId.value) {
    ev.preventDefault()
    ev.stopPropagation()
    emit('close')
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown, true)
  if (query.value) {
    void runSearch()
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown, true)
})
</script>

<template>
  <div class="modal-backdrop bind-backdrop" @click.self="!bindingId && emit('close')">
    <div class="modal-card bind-card">
      <div class="bind-head">
        <h2>关联 Bangumi 条目</h2>
        <button
          type="button"
          class="close-icon-btn"
          aria-label="关闭"
          :disabled="Boolean(bindingId)"
          @click="emit('close')"
        >
          <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" />
          </svg>
        </button>
      </div>

      <div class="bind-search">
        <form class="search-row" @submit.prevent="runSearch">
          <input
            v-model="query"
            class="input"
            placeholder="输入游戏原名或中文名检索 Bangumi…"
          />
          <button type="submit" class="btn btn-primary btn-sm" :disabled="loading || !query.trim()">
            {{ loading ? '搜索中…' : '搜索' }}
          </button>
        </form>

        <div v-if="quickKeywords.length > 0" class="quick-row">
          <button
            v-for="kw in quickKeywords"
            :key="kw.label"
            type="button"
            class="quick-chip"
            :class="{ active: query.trim() === kw.value }"
            @click="query = kw.value; runSearch()"
          >
            <span class="quick-tag">{{ kw.label }}</span>
            <span class="quick-val">{{ kw.value }}</span>
          </button>
        </div>
      </div>

      <div class="bind-body">
        <div v-if="loading" class="bind-empty">正在检索 Bangumi 条目…</div>

        <div v-else-if="items.length > 0" class="bind-list">
          <button
            v-for="item in items"
            :key="item.external_id"
            type="button"
            class="bind-row"
            :disabled="Boolean(bindingId)"
            @click="bindAndSync(item)"
          >
            <div class="bind-cover">
              <img
                v-if="item.cover_url"
                v-img-fade
                :src="assetProxyUrl(item.cover_url)"
                alt=""
                loading="lazy"
                decoding="async"
              />
              <span v-else>BGM</span>
            </div>
            <div class="bind-info">
              <div class="bind-title">{{ item.title }}</div>
              <div v-if="item.sub_title" class="bind-sub">{{ item.sub_title }}</div>
              <div class="bind-meta tabular-nums">
                <span v-if="item.release_date">{{ item.release_date }}</span>
                <span>ID {{ item.external_id }}</span>
              </div>
            </div>
            <span class="bind-action">
              {{ bindingId === item.external_id ? '同步中…' : '关联并同步' }}
            </span>
          </button>
        </div>

        <div v-else-if="searchedOnce" class="bind-empty">
          未找到匹配条目，可尝试更换日文原名重新搜索
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bind-backdrop {
  z-index: 100;
}

.bind-card {
  max-width: 560px;
  max-height: 76vh;
}

.bind-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px 12px;
}

.bind-head h2 {
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
}

.close-icon-btn:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.bind-search {
  padding: 0 22px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-bottom: 1px solid var(--divider-subtle);
}

.search-row {
  display: flex;
  gap: 8px;
}

.quick-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.quick-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 260px;
  padding: 4px 10px;
  border: none;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.045);
  color: var(--text-secondary);
  font-size: 12px;
}

.quick-chip:hover,
.quick-chip.active {
  background: rgba(255, 255, 255, 0.12);
  color: var(--text-primary);
}

.quick-tag {
  font-size: 10.5px;
  color: var(--text-muted);
}

.quick-val {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bind-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px 22px 20px;
}

.bind-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.bind-row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 9px 11px;
  border: none;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  text-align: left;
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.bind-row:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.075);
}

.bind-cover {
  width: 42px;
  height: 58px;
  border-radius: 6px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.06);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  color: var(--text-muted);
}

.bind-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.bind-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.bind-title {
  font-size: 13.5px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bind-sub {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bind-meta {
  display: flex;
  gap: 10px;
  font-size: 11px;
  color: var(--text-muted);
}

.bind-action {
  padding: 5px 11px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
}

.bind-row:hover:not(:disabled) .bind-action {
  background: #f5f5f7;
  color: #0a0a0c;
}

.bind-empty {
  padding: 40px 12px;
  text-align: center;
  font-size: 13px;
  color: var(--text-muted);
}
</style>
