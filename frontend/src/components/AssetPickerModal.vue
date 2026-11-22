<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { assetProxyUrl, scraperApi } from '@/api/client'
import { useLibraryStore } from '@/stores/library'
import { useTaskStore } from '@/stores/tasks'
import type { AssetCandidate, Game, PickerAssetType } from '@/types'

const props = defineProps<{
  game: Game
  assetType: PickerAssetType
}>()

const emit = defineEmits<{
  close: []
  applied: [updated: Game]
}>()

const store = useLibraryStore()
const taskStore = useTaskStore()

const SLOT_TITLES: Record<PickerAssetType, string> = {
  cover: '替换封面原图',
  logo: '替换透明艺术字 Logo',
  hero: '替换宽幅 Hero 背景',
  spine: '替换自定义侧封',
  pv: '查找官方宣传片 PV',
}

const SLOT_SHORT_NAMES: Record<PickerAssetType, string> = {
  cover: '封面原图',
  logo: '透明艺术字 Logo',
  hero: '宽幅 Hero 背景',
  spine: '自定义侧封',
  pv: '宣传片 PV',
}

interface SourceOption {
  key: string
  label: string
}

const IMAGE_SOURCES: SourceOption[] = [
  { key: 'all', label: '全部' },
  { key: 'steamgriddb', label: 'SteamGridDB' },
  { key: 'vndb', label: 'VNDB' },
  { key: 'bangumi', label: 'Bangumi' },
  { key: 'steam', label: 'Steam' },
  { key: 'touchgal', label: 'TouchGal' },
]

const PV_SOURCES: SourceOption[] = [
  { key: 'auto', label: '优先 Steam' },
  { key: 'steam', label: '仅 Steam' },
  { key: 'bilibili', label: 'Bilibili' },
  { key: 'youtube', label: 'YouTube' },
]

const modalTitle = computed(() => SLOT_TITLES[props.assetType])
const isPvMode = computed(() => props.assetType === 'pv')
const sourceOptions = computed<SourceOption[]>(() =>
  isPvMode.value ? PV_SOURCES : IMAGE_SOURCES,
)

const quickKeywords = computed(() => {
  const title = (props.game.title || '').trim()
  const sub = (props.game.sub_title || '').trim()
  if (!title || !sub || title === sub) return []
  return [
    { label: '原名', value: sub },
    { label: '中文名', value: title },
  ]
})

const query = ref((props.game.sub_title || props.game.title || '').trim())
const selectedSource = ref<string>(
  props.assetType === 'logo' ? 'steamgriddb' : props.assetType === 'pv' ? 'auto' : 'all',
)
const loading = ref(false)
const searchedOnce = ref(false)
const steamEmpty = ref(false)
const items = ref<AssetCandidate[]>([])
const warnings = ref<string[]>([])
const sgdbConfigured = ref(Boolean(store.settings.api_keys?.steamgriddb))
const applyingId = ref('')
const brokenIds = ref<Set<string>>(new Set())

let searchSeq = 0

function markBroken(id: string) {
  const next = new Set(brokenIds.value)
  next.add(id)
  brokenIds.value = next
}

async function runSearch() {
  const q = query.value.trim()
  const steamAppId = (props.game.external_ids?.steam || '').trim()
  if (!q && !(isPvMode.value && steamAppId)) return
  const altTitle =
    q !== (props.game.title || '').trim()
      ? (props.game.title || '').trim()
      : (props.game.sub_title || '').trim()

  const seq = ++searchSeq
  loading.value = true
  searchedOnce.value = true
  brokenIds.value = new Set()
  try {
    const res = await scraperApi.searchAssets(props.assetType, q, selectedSource.value, {
      steam_appid: isPvMode.value ? steamAppId : '',
      alt_title: isPvMode.value ? altTitle : '',
    })
    if (seq !== searchSeq) return
    items.value = res.items || []
    steamEmpty.value = Boolean(res.steam_empty)
    warnings.value = res.warnings || []
    sgdbConfigured.value = Boolean(res.sgdb_configured)
  } catch (err) {
    if (seq !== searchSeq) return
    items.value = []
    steamEmpty.value = false
    warnings.value = []
    store.notify(err instanceof Error ? err.message : '在线检索失败', 'warning')
  } finally {
    if (seq === searchSeq) {
      loading.value = false
    }
  }
}

function selectSource(sourceKey: string) {
  if (selectedSource.value === sourceKey) return
  selectedSource.value = sourceKey
  void runSearch()
}

function useQuickKeyword(val: string) {
  query.value = val
  void runSearch()
}

async function applyCandidate(item: AssetCandidate) {
  if (applyingId.value) return
  applyingId.value = item.id
  try {
    const updated = await scraperApi.applyAsset(props.game.id, {
      asset_type: props.assetType,
      url: item.url,
      source: item.source,
      mime_hint: item.mime_hint,
      async_mode: props.assetType === 'pv',
    })
    store.syncGameFromServer(updated)
    if (props.assetType === 'pv' && updated.download_task) {
      taskStore.trackTask(updated.download_task, {
        url: item.url,
        source: item.source,
        mime_hint: item.mime_hint,
      })
      store.notify('宣传片已加入后台下载，完成后自动更新', 'info')
    } else {
      store.notify(`已更新${SLOT_SHORT_NAMES[props.assetType]}`, 'success')
    }
    emit('applied', updated)
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '应用资产失败', 'error')
  } finally {
    applyingId.value = ''
  }
}

function formatDuration(sec: number | null): string {
  if (!sec || sec <= 0) return ''
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function formatDims(item: AssetCandidate): string {
  if (item.width && item.height) {
    return `${item.width}×${item.height}`
  }
  return ''
}

function pvHintLabel(item: AssetCandidate): string {
  if (item.mime_hint === 'hls') return 'HLS 直链'
  if (item.mime_hint === 'mp4') return 'MP4 直链'
  return '下载本地 MP4'
}

const showSgdbKeyEmpty = computed(
  () =>
    !loading.value &&
    items.value.length === 0 &&
    selectedSource.value === 'steamgriddb' &&
    !sgdbConfigured.value,
)

const gridModeClass = computed(() => {
  if (isPvMode.value) return 'grid-pv'
  if (props.assetType === 'cover' || props.assetType === 'spine') return 'grid-portrait'
  if (props.assetType === 'logo') return 'grid-logo'
  return 'grid-wide'
})

const skeletonCount = computed(() => (props.assetType === 'cover' || props.assetType === 'spine' ? 8 : 6))

function handleKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Escape') {
    ev.preventDefault()
    ev.stopPropagation()
    if (!applyingId.value) {
      emit('close')
    }
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
  <div class="picker-backdrop" @click.self="!applyingId && emit('close')">
    <div class="modal-card picker-card">
      <!-- 顶部标题栏 -->
      <div class="picker-head">
        <h2>{{ modalTitle }}</h2>
        <button
          type="button"
          class="close-icon-btn"
          aria-label="关闭"
          :disabled="Boolean(applyingId)"
          @click="emit('close')"
        >
          <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" />
          </svg>
        </button>
      </div>

      <!-- 搜索栏 + 快捷关键词 + 数据源切换 -->
      <div class="picker-controls">
        <form class="search-row" @submit.prevent="runSearch">
          <input
            v-model="query"
            class="input search-input"
            placeholder="输入游戏名或原名关键词…"
          />
          <button
            type="submit"
            class="btn btn-primary btn-sm search-btn"
            :disabled="loading || !query.trim()"
          >
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
            @click="useQuickKeyword(kw.value)"
          >
            <span class="quick-tag">{{ kw.label }}</span>
            <span class="quick-val">{{ kw.value }}</span>
          </button>
        </div>

        <div class="source-bar" role="tablist">
          <button
            v-for="src in sourceOptions"
            :key="src.key"
            type="button"
            class="source-pill"
            :class="{ active: selectedSource === src.key }"
            @click="selectSource(src.key)"
          >
            {{ src.label }}
          </button>
        </div>
      </div>

      <!-- 候选展示区域 -->
      <div class="picker-body">
        <div v-if="warnings.length > 0 && items.length > 0" class="inline-warning">
          {{ warnings[0] }}
        </div>
        <div
          v-if="isPvMode && steamEmpty && !loading && (selectedSource === 'auto' || selectedSource === 'steam')"
          class="inline-warning steam-empty-tip"
        >
          <span>未在 Steam 找到官方宣传片，可切换</span>
          <button type="button" class="inline-switch-btn" @click="selectSource('bilibili')">Bilibili</button>
          <span>或</span>
          <button type="button" class="inline-switch-btn" @click="selectSource('youtube')">YouTube</button>
          <span>查找</span>
        </div>

        <!-- 骨架加载态 -->
        <div v-if="loading" class="candidate-grid" :class="gridModeClass">
          <div
            v-for="n in skeletonCount"
            :key="n"
            class="skeleton-card"
            :class="{
              portrait: assetType === 'cover' || assetType === 'spine',
              wide: assetType === 'hero' || assetType === 'logo',
              pv: isPvMode,
            }"
          />
        </div>

        <!-- PV 视频候选网格 -->
        <div v-else-if="isPvMode && items.length > 0" class="candidate-grid grid-pv">
          <div
            v-for="item in items"
            :key="item.id"
            class="pv-card"
            :class="{ applying: applyingId === item.id }"
          >
            <div class="pv-thumb">
              <img
                v-if="item.thumb_url && !brokenIds.has(item.id)"
                :src="assetProxyUrl(item.thumb_url)"
                alt=""
                loading="lazy"
                @error="markBroken(item.id)"
              />
              <div v-else class="thumb-fallback">
                <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.5">
                  <polygon points="8 5 19 12 8 19 8 5" />
                </svg>
              </div>
              <span
                class="badge-source"
                :class="{ 'badge-official': item.is_official || item.source === 'Steam' }"
              >
                {{ item.is_official || item.source === 'Steam' ? 'Steam 官方' : item.platform || item.source }}
              </span>
              <span v-if="formatDuration(item.duration)" class="badge-meta tabular-nums">
                {{ formatDuration(item.duration) }}
              </span>
            </div>
            <div class="pv-footer">
              <div class="pv-info">
                <div class="pv-title" :title="item.title">{{ item.title }}</div>
                <div class="pv-sub">{{ pvHintLabel(item) }}</div>
              </div>
              <button
                type="button"
                class="btn btn-sm"
                :class="{ 'btn-primary': applyingId === item.id }"
                :disabled="Boolean(applyingId)"
                @click="applyCandidate(item)"
              >
                <template v-if="applyingId === item.id">
                  {{ item.mime_hint === 'video_page' ? '下载中…' : '保存中…' }}
                </template>
                <template v-else>应用</template>
              </button>
            </div>
          </div>
        </div>

        <!-- 图片候选网格 -->
        <div v-else-if="!isPvMode && items.length > 0" class="candidate-grid" :class="gridModeClass">
          <button
            v-for="item in items"
            :key="item.id"
            type="button"
            class="img-card"
            :class="{
              portrait: assetType === 'cover' || assetType === 'spine',
              wide: assetType === 'hero',
              logo: assetType === 'logo',
              applying: applyingId === item.id,
            }"
            :disabled="Boolean(applyingId)"
            :title="item.title"
            @click="applyCandidate(item)"
          >
            <img
              v-if="!brokenIds.has(item.id)"
              :src="assetProxyUrl(item.thumb_url || item.url)"
              :alt="item.title"
              loading="lazy"
              @error="markBroken(item.id)"
            />
            <div v-else class="thumb-fallback">预览加载失败</div>

            <span class="badge-source">{{ item.source }}</span>
            <span v-if="formatDims(item)" class="badge-meta tabular-nums">
              {{ formatDims(item) }}
            </span>

            <div class="hover-overlay" :class="{ visible: applyingId === item.id }">
              <span class="apply-pill">
                {{ applyingId === item.id ? '正在应用…' : '应用此图' }}
              </span>
            </div>
          </button>
        </div>

        <!-- 空态 -->
        <div v-else class="picker-empty">
          <template v-if="showSgdbKeyEmpty">
            <p class="empty-primary">尚未配置 SteamGridDB API Key</p>
            <p class="empty-sub">可在全局设置 → 数据源管理中填写</p>
          </template>
          <template v-else-if="warnings.length > 0">
            <p class="empty-primary">{{ warnings[0] }}</p>
          </template>
          <template v-else-if="searchedOnce">
            <p class="empty-primary">未找到匹配结果</p>
            <p class="empty-sub">可尝试更换关键词或切换数据源</p>
          </template>
          <template v-else>
            <p class="empty-primary">输入关键词开始搜索</p>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.picker-backdrop {
  position: fixed;
  inset: 0;
  z-index: 95;
  background: rgba(4, 4, 6, 0.76);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.picker-card {
  max-width: 880px;
  height: min(82vh, 720px);
}

.picker-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 24px 12px;
}

.picker-head h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
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

.close-icon-btn:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.close-icon-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.picker-controls {
  padding: 0 24px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  border-bottom: 1px solid var(--divider-subtle);
}

.search-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.search-input {
  flex: 1;
  font-size: 13.5px;
  font-weight: 400;
}

.search-btn {
  min-width: 74px;
  height: 37px;
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
  max-width: 360px;
  padding: 4px 10px;
  border: none;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.045);
  color: var(--text-secondary);
  font-size: 12px;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.quick-chip:hover {
  background: rgba(255, 255, 255, 0.09);
  color: var(--text-primary);
}

.quick-chip.active {
  background: rgba(255, 255, 255, 0.13);
  color: var(--text-primary);
}

.quick-tag {
  font-size: 10.5px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.quick-val {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.source-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 2px;
}

.source-pill {
  padding: 5px 12px;
  border: none;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.045);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.source-pill:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-primary);
}

.source-pill.active {
  background: #f5f5f7;
  color: #0a0a0c;
  font-weight: 600;
}

.picker-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 24px 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.inline-warning {
  padding: 8px 12px;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.045);
  color: var(--text-secondary);
  font-size: 12px;
}

.candidate-grid {
  display: grid;
  gap: 12px;
}

.grid-portrait {
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
}

.grid-wide,
.grid-logo {
  grid-template-columns: repeat(auto-fill, minmax(238px, 1fr));
}

.grid-pv {
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
}

/* 图片候选卡片 */
.img-card {
  position: relative;
  padding: 0;
  border: none;
  border-radius: 11px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.035);
  display: flex;
  align-items: center;
  justify-content: center;
  transition:
    transform var(--duration-fast) var(--ease-out-expo),
    background-color var(--duration-fast) var(--ease-out-expo),
    box-shadow var(--duration-fast) var(--ease-out-expo);
}

.img-card.portrait {
  aspect-ratio: 2 / 3;
}

.img-card.wide {
  aspect-ratio: 16 / 9;
}

.img-card.logo {
  aspect-ratio: 16 / 9;
  padding: 16px;
  background: repeating-conic-gradient(rgba(255, 255, 255, 0.055) 0% 25%, rgba(255, 255, 255, 0.015) 0% 50%)
    50% / 16px 16px;
}

.img-card img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition:
    transform 260ms var(--ease-out-expo),
    filter var(--duration-fast) var(--ease-out-expo);
}

.img-card.logo img {
  object-fit: contain;
}

.img-card:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.48);
}

.img-card:hover:not(:disabled) img {
  filter: brightness(1.08);
}

.img-card:disabled {
  cursor: wait;
}

.img-card:disabled:not(.applying) {
  opacity: 0.55;
}

.badge-source,
.badge-meta {
  position: absolute;
  bottom: 8px;
  z-index: 2;
  padding: 2px 7px;
  border-radius: 5px;
  background: rgba(10, 10, 12, 0.72);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  font-size: 10.5px;
  font-weight: 500;
  color: rgba(245, 245, 247, 0.88);
  pointer-events: none;
}

.badge-source {
  left: 8px;
}

.badge-meta {
  right: 8px;
  font-family: var(--font-mono);
  color: rgba(245, 245, 247, 0.72);
}

.hover-overlay {
  position: absolute;
  inset: 0;
  z-index: 3;
  background: rgba(8, 8, 10, 0.42);
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity var(--duration-fast) var(--ease-out-expo);
}

.img-card:hover:not(:disabled) .hover-overlay,
.hover-overlay.visible {
  opacity: 1;
}

.apply-pill {
  padding: 6px 14px;
  border-radius: 999px;
  background: #f5f5f7;
  color: #0a0a0c;
  font-size: 12px;
  font-weight: 600;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.45);
}

/* PV 视频候选卡片 */
.pv-card {
  display: flex;
  flex-direction: column;
  border-radius: 12px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.032);
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.pv-card:hover {
  background: rgba(255, 255, 255, 0.055);
}

.pv-thumb {
  position: relative;
  aspect-ratio: 16 / 9;
  background: rgba(255, 255, 255, 0.04);
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.pv-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.pv-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
}

.pv-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.pv-title {
  font-size: 12.5px;
  font-weight: 400;
  color: var(--text-primary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.4;
}

.pv-sub {
  font-size: 11px;
  color: var(--text-muted);
}

.thumb-fallback {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11.5px;
  color: var(--text-muted);
}

/* 骨架屏 */
.skeleton-card {
  border-radius: 11px;
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.03) 25%,
    rgba(255, 255, 255, 0.065) 50%,
    rgba(255, 255, 255, 0.03) 75%
  );
  background-size: 200% 100%;
  animation: picker-shimmer 1.35s ease-in-out infinite;
}

.skeleton-card.portrait {
  aspect-ratio: 2 / 3;
}

.skeleton-card.wide {
  aspect-ratio: 16 / 9;
}

.skeleton-card.pv {
  aspect-ratio: 16 / 12;
}

@keyframes picker-shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

/* 空态 */
.picker-empty {
  flex: 1;
  min-height: 220px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 6px;
}

.empty-primary {
  margin: 0;
  font-size: 13.5px;
  color: var(--text-secondary);
}

.empty-sub {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.steam-empty-tip {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
}

.inline-switch-btn {
  border: none;
  background: transparent;
  padding: 0;
  color: #f5f5f7;
  font-size: inherit;
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}

.inline-switch-btn:hover {
  opacity: 0.85;
}

.badge-official {
  background: rgba(244, 244, 245, 0.92);
  color: #0a0a0c;
  font-weight: 600;
}
</style>
