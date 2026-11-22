<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { assetProxyUrl, scraperApi } from '@/api/client'
import { useLibraryStore } from '@/stores/library'
import type {
  MetadataApplyPatch,
  MetadataCandidateItem,
  MetadataDetailResponse,
  MetadataFieldKey,
  MetadataSourceKey,
} from '@/types'

interface CurrentFormSnapshot {
  title: string
  sub_title: string
  developer: string
  publisher: string
  release_date: string
  bangumi_id: string
  tags: string[]
  synopsis: string
  locked_fields: string[]
}

const props = defineProps<{
  currentForm: CurrentFormSnapshot
  focusField?: MetadataFieldKey | null
}>()

const emit = defineEmits<{
  close: []
  apply: [patch: MetadataApplyPatch]
}>()

const store = useLibraryStore()

const FIELD_LABELS: Record<MetadataFieldKey, string> = {
  title: '主标题',
  sub_title: '原名 / 副标题',
  developer: '开发商',
  publisher: '发行商',
  release_date: '发售日期',
  bangumi_id: 'Bangumi 条目 ID',
  tags: '标签',
  description: '剧情简介',
}

const LOCK_KEY_MAP: Record<MetadataFieldKey, string> = {
  title: 'title',
  sub_title: 'sub_title',
  developer: 'developer',
  publisher: 'publisher',
  release_date: 'release_date',
  bangumi_id: 'bangumi_id',
  tags: 'tags',
  description: 'synopsis',
}

const SOURCE_TABS: { key: MetadataSourceKey; label: string }[] = [
  { key: 'vndb', label: 'VNDB' },
  { key: 'bangumi', label: 'Bangumi' },
  { key: 'touchgal', label: 'TouchGal' },
  { key: 'steam', label: 'Steam' },
]

const modalTitle = computed(() =>
  props.focusField ? `查找并替换：${FIELD_LABELS[props.focusField]}` : '查找并替换资料',
)

const quickKeywords = computed(() => {
  const title = (props.currentForm.title || '').trim()
  const sub = (props.currentForm.sub_title || '').trim()
  if (!title || !sub || title === sub) return []
  return [
    { label: '主标题', value: title },
    { label: '原名', value: sub },
  ]
})

const query = ref((props.currentForm.title || props.currentForm.sub_title || '').trim())
const selectedSource = ref<MetadataSourceKey>('vndb')
const searching = ref(false)
const searchedOnce = ref(false)
const candidates = ref<MetadataCandidateItem[]>([])
const brokenCovers = ref<Set<string>>(new Set())

const selectedCandidateId = ref('')
const loadingDetail = ref(false)
const detail = ref<MetadataDetailResponse | null>(null)
const detailError = ref('')

const tagsMode = ref<'replace' | 'merge'>('replace')
const checkedFields = reactive<Record<MetadataFieldKey, boolean>>({
  title: false,
  sub_title: false,
  developer: false,
  publisher: false,
  release_date: false,
  bangumi_id: false,
  tags: false,
  description: false,
})

let searchSeq = 0
let detailSeq = 0

function isFieldLocked(field: MetadataFieldKey): boolean {
  const lockKey = LOCK_KEY_MAP[field]
  return (props.currentForm.locked_fields || []).includes(lockKey)
}

function hasNewValue(d: MetadataDetailResponse | null, field: MetadataFieldKey): boolean {
  if (!d) return false
  if (field === 'tags') return Array.isArray(d.tags) && d.tags.length > 0
  if (field === 'bangumi_id') return d.source === 'bangumi' && Boolean((d.bangumi_id || '').trim())
  return Boolean((d[field] || '').trim())
}

function currentValuePreview(field: MetadataFieldKey): string {
  if (field === 'tags') {
    const list = props.currentForm.tags || []
    return list.length > 0 ? list.slice(0, 5).join(' · ') + (list.length > 5 ? ` (+${list.length - 5})` : '') : '空'
  }
  if (field === 'description') {
    const txt = (props.currentForm.synopsis || '').replace(/\s+/g, ' ').trim()
    return txt ? (txt.length > 64 ? `${txt.slice(0, 62)}…` : txt) : '空'
  }
  const val = (props.currentForm[field] || '').trim()
  return val || '空'
}

function resetCheckedForDetail(d: MetadataDetailResponse | null) {
  const allKeys: MetadataFieldKey[] = [
    'title',
    'sub_title',
    'developer',
    'publisher',
    'release_date',
    'bangumi_id',
    'tags',
    'description',
  ]
  for (const k of allKeys) {
    if (!d || !hasNewValue(d, k)) {
      checkedFields[k] = false
      continue
    }
    if (props.focusField) {
      checkedFields[k] = k === props.focusField
    } else {
      checkedFields[k] = !isFieldLocked(k)
    }
  }
}

const visibleFields = computed<MetadataFieldKey[]>(() => {
  const base: MetadataFieldKey[] = [
    'title',
    'sub_title',
    'developer',
    'publisher',
    'release_date',
  ]
  if (detail.value?.source === 'bangumi' && (detail.value.bangumi_id || '').trim()) {
    base.push('bangumi_id')
  }
  base.push('tags', 'description')
  return base
})

const selectedCount = computed(
  () => visibleFields.value.filter((k) => checkedFields[k] && hasNewValue(detail.value, k)).length,
)

function extractYear(raw?: string): string {
  const m = (raw || '').match(/\d{4}/)
  return m ? m[0] : ''
}

function markCoverBroken(id: string) {
  const next = new Set(brokenCovers.value)
  next.add(id)
  brokenCovers.value = next
}

async function selectCandidate(item: MetadataCandidateItem) {
  selectedCandidateId.value = item.external_id
  const seq = ++detailSeq
  loadingDetail.value = true
  detailError.value = ''
  detail.value = null
  resetCheckedForDetail(null)

  try {
    const res = await scraperApi.detailMetadata(item.source, item.external_id)
    if (seq !== detailSeq) return
    detail.value = res
    resetCheckedForDetail(res)
  } catch (err) {
    if (seq !== detailSeq) return
    detailError.value = err instanceof Error ? err.message : '拉取条目详情失败'
  } finally {
    if (seq === detailSeq) {
      loadingDetail.value = false
    }
  }
}

async function runSearch() {
  const q = query.value.trim()
  if (!q) return
  const seq = ++searchSeq
  detailSeq++
  searching.value = true
  searchedOnce.value = true
  candidates.value = []
  selectedCandidateId.value = ''
  detail.value = null
  detailError.value = ''
  brokenCovers.value = new Set()
  resetCheckedForDetail(null)

  try {
    const res = await scraperApi.searchMetadata(q, selectedSource.value, 10)
    if (seq !== searchSeq) return
    candidates.value = res.items || []
    if (candidates.value.length > 0) {
      void selectCandidate(candidates.value[0])
    }
  } catch (err) {
    if (seq !== searchSeq) return
    store.notify(err instanceof Error ? err.message : '在线检索失败', 'warning')
  } finally {
    if (seq === searchSeq) {
      searching.value = false
    }
  }
}

function switchSource(src: MetadataSourceKey) {
  if (selectedSource.value === src) return
  selectedSource.value = src
  void runSearch()
}

function useQuickKeyword(val: string) {
  query.value = val
  void runSearch()
}

function toggleField(field: MetadataFieldKey) {
  if (!hasNewValue(detail.value, field)) return
  checkedFields[field] = !checkedFields[field]
}

function applySelection() {
  const d = detail.value
  if (!d || selectedCount.value === 0) return

  const patch: MetadataApplyPatch = {}
  if (checkedFields.title && d.title.trim()) patch.title = d.title.trim()
  if (checkedFields.sub_title && d.sub_title.trim()) patch.sub_title = d.sub_title.trim()
  if (checkedFields.developer && d.developer.trim()) patch.developer = d.developer.trim()
  if (checkedFields.publisher && d.publisher.trim()) patch.publisher = d.publisher.trim()
  if (checkedFields.release_date && d.release_date.trim()) patch.release_date = d.release_date.trim()
  if (checkedFields.bangumi_id && d.bangumi_id.trim()) patch.bangumi_id = d.bangumi_id.trim()
  if (checkedFields.tags && d.tags.length > 0) {
    patch.tags = [...d.tags]
    patch.tagsMode = tagsMode.value
  }
  if (checkedFields.description && d.description.trim()) patch.description = d.description.trim()

  emit('apply', patch)
}

function handleKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Escape') {
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
  <div class="meta-picker-backdrop" @click.self="emit('close')">
    <div class="modal-card meta-picker-card">
      <!-- 顶部标题栏 -->
      <div class="mp-head">
        <h2>{{ modalTitle }}</h2>
        <button type="button" class="close-icon-btn" aria-label="关闭" @click="emit('close')">
          <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" />
          </svg>
        </button>
      </div>

      <!-- 检索栏 + 快捷关键词 + 单数据源切换条 -->
      <div class="mp-controls">
        <form class="mp-search-row" @submit.prevent="runSearch">
          <input
            v-model="query"
            class="input mp-search-input"
            placeholder="输入中文主标题或日文原名…"
          />
          <button
            type="submit"
            class="btn btn-primary btn-sm mp-search-btn"
            :disabled="searching || !query.trim()"
          >
            {{ searching ? '搜索中…' : '搜索' }}
          </button>
        </form>

        <div class="mp-sub-controls">
          <div class="source-bar" role="tablist">
            <button
              v-for="src in SOURCE_TABS"
              :key="src.key"
              type="button"
              class="source-pill"
              :class="{ active: selectedSource === src.key }"
              @click="switchSource(src.key)"
            >
              {{ src.label }}
            </button>
          </div>

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
        </div>
      </div>

      <!-- 主体：左候选列表 + 右字段对比勾选 -->
      <div class="mp-split">
        <!-- 左侧候选列表 -->
        <aside class="mp-left">
          <div v-if="searching" class="mp-left-state">正在搜索…</div>

          <div v-else-if="candidates.length > 0" class="cand-list">
            <button
              v-for="item in candidates"
              :key="`${item.source}-${item.external_id}`"
              type="button"
              class="cand-row"
              :class="{ active: selectedCandidateId === item.external_id }"
              @click="selectCandidate(item)"
            >
              <div class="cand-cover">
                <img
                  v-if="item.cover_url && !brokenCovers.has(item.external_id)"
                  v-img-fade
                  :src="assetProxyUrl(item.cover_url)"
                  alt=""
                  loading="lazy"
                  decoding="async"
                  @error="markCoverBroken(item.external_id)"
                />
                <span v-else>{{ item.source.toUpperCase() }}</span>
              </div>
              <div class="cand-info">
                <div class="cand-title" :title="item.title">{{ item.title }}</div>
                <div v-if="item.sub_title" class="cand-sub" :title="item.sub_title">
                  {{ item.sub_title }}
                </div>
                <div class="cand-meta">
                  <span v-if="item.developer" class="cand-dev">{{ item.developer }}</span>
                  <span v-if="extractYear(item.release_date)" class="cand-year tabular-nums">
                    {{ extractYear(item.release_date) }}
                  </span>
                </div>
              </div>
            </button>
          </div>

          <div v-else-if="searchedOnce" class="mp-left-state">
            未找到匹配条目
          </div>
          <div v-else class="mp-left-state">
            输入关键词搜索
          </div>
        </aside>

        <!-- 右侧字段选择与预览 -->
        <section class="mp-right">
          <div v-if="loadingDetail" class="mp-right-state">
            正在读取条目字段…
          </div>

          <div v-else-if="detailError" class="mp-right-state error">
            {{ detailError }}
          </div>

          <div v-else-if="detail" class="fields-card">
            <div
              v-for="field in visibleFields"
              :key="field"
              class="field-row"
              :class="{
                disabled: !hasNewValue(detail, field),
                checked: checkedFields[field] && hasNewValue(detail, field),
                focused: focusField === field,
              }"
              @click="toggleField(field)"
            >
              <div class="field-top">
                <div class="field-left-label">
                  <input
                    type="checkbox"
                    class="field-checkbox"
                    :checked="checkedFields[field]"
                    :disabled="!hasNewValue(detail, field)"
                    @click.stop
                    @change="toggleField(field)"
                  />
                  <span class="field-name">{{ FIELD_LABELS[field] }}</span>
                  <span v-if="isFieldLocked(field)" class="locked-chip" title="编辑页中已锁定此字段">
                    <svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.6">
                      <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
                      <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" />
                    </svg>
                    <span>已锁</span>
                  </span>
                </div>

                <!-- 标签替换模式开关 -->
                <div
                  v-if="field === 'tags' && hasNewValue(detail, 'tags')"
                  class="tags-mode-switch"
                  @click.stop
                >
                  <button
                    type="button"
                    :class="{ active: tagsMode === 'replace' }"
                    @click="tagsMode = 'replace'"
                  >
                    替换全部
                  </button>
                  <button
                    type="button"
                    :class="{ active: tagsMode === 'merge' }"
                    @click="tagsMode = 'merge'"
                  >
                    合并追加
                  </button>
                </div>
              </div>

              <!-- 当前值简明对比 -->
              <div class="field-old" :title="currentValuePreview(field)">
                当前：{{ currentValuePreview(field) }}
              </div>

              <!-- 新抓取内容预览 -->
              <div v-if="!hasNewValue(detail, field)" class="field-new empty">
                该数据源未提供此字段
              </div>

              <div v-else-if="field === 'tags'" class="new-tags-flow">
                <span v-for="tag in detail.tags" :key="tag" class="new-tag-chip">
                  {{ tag }}
                </span>
              </div>

              <div
                v-else-if="field === 'description'"
                class="field-new desc-box"
                @click.stop
              >
                {{ detail.description }}
              </div>

              <div
                v-else
                class="field-new"
                :class="{ 'tabular-nums': field === 'release_date' || field === 'bangumi_id' }"
              >
                {{ detail[field] }}
              </div>
            </div>
          </div>

          <div v-else class="mp-right-state">
            从左侧选择一个条目以预览可替换字段
          </div>
        </section>
      </div>

      <!-- 底部操作栏 -->
      <div class="mp-foot">
        <span class="mp-count tabular-nums">已选择 {{ selectedCount }} 项</span>
        <div class="mp-foot-actions">
          <button type="button" class="btn btn-ghost btn-sm" @click="emit('close')">
            取消
          </button>
          <button
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="selectedCount === 0"
            @click="applySelection"
          >
            应用到表单
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.meta-picker-backdrop {
  position: fixed;
  inset: 0;
  z-index: 98;
  background: rgba(4, 4, 6, 0.76);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.meta-picker-card {
  width: 860px;
  max-width: calc(100vw - 40px);
  height: min(600px, 86vh);
}

.mp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 22px 10px;
  flex-shrink: 0;
}

.mp-head h2 {
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

.close-icon-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.mp-controls {
  padding: 0 22px 12px;
  display: flex;
  flex-direction: column;
  gap: 9px;
  border-bottom: 1px solid var(--divider-subtle);
  flex-shrink: 0;
}

.mp-search-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.mp-search-input {
  flex: 1;
  font-size: 13.5px;
  font-weight: 400;
}

.mp-search-btn {
  min-width: 72px;
  height: 37px;
}

.mp-sub-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.source-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
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

.quick-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.quick-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 210px;
  padding: 4px 9px;
  border: none;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.045);
  color: var(--text-secondary);
  font-size: 11.5px;
}

.quick-chip:hover,
.quick-chip.active {
  background: rgba(255, 255, 255, 0.12);
  color: var(--text-primary);
}

.quick-tag {
  font-size: 10px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.quick-val {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 左右分栏主体 */
.mp-split {
  flex: 1;
  min-height: 0;
  display: flex;
  overflow: hidden;
}

.mp-left {
  width: 308px;
  flex-shrink: 0;
  overflow-y: auto;
  padding: 12px 10px 14px 16px;
  border-right: 1px solid var(--divider-subtle);
}

.cand-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.cand-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  padding: 8px 9px;
  border: none;
  border-radius: 10px;
  background: transparent;
  text-align: left;
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.cand-row:hover {
  background: rgba(255, 255, 255, 0.05);
}

.cand-row.active {
  background: rgba(255, 255, 255, 0.11);
}

.cand-cover {
  width: 40px;
  height: 56px;
  border-radius: 6px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.06);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 9.5px;
  color: var(--text-muted);
}

.cand-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cand-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cand-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.35;
}

.cand-sub {
  font-size: 11.5px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cand-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-muted);
}

.cand-dev {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cand-year {
  flex-shrink: 0;
  font-family: var(--font-mono);
  color: var(--text-secondary);
}

.mp-left-state,
.mp-right-state {
  height: 100%;
  min-height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--text-muted);
  text-align: center;
  padding: 20px;
}

.mp-right-state.error {
  color: var(--danger-text);
}

/* 右侧字段预览与勾选 */
.mp-right {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 14px 20px 18px 16px;
}

.fields-card {
  background: rgba(255, 255, 255, 0.028);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  overflow: hidden;
}

.field-row {
  padding: 12px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  flex-direction: column;
  gap: 5px;
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.field-row:last-child {
  border-bottom: none;
}

.field-row:hover:not(.disabled) {
  background: rgba(255, 255, 255, 0.03);
}

.field-row.checked {
  background: rgba(255, 255, 255, 0.055);
}

.field-row.disabled {
  opacity: 0.42;
  cursor: default;
}

.field-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.field-left-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.field-checkbox {
  width: 15px;
  height: 15px;
  accent-color: #f5f5f7;
  cursor: pointer;
}

.field-row.disabled .field-checkbox {
  cursor: default;
}

.field-name {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-primary);
}

.locked-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 6px;
  border-radius: 5px;
  background: var(--amber-bg);
  color: var(--amber-text);
  font-size: 10.5px;
}

.tags-mode-switch {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.06);
}

.tags-mode-switch button {
  padding: 2px 8px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--text-muted);
  font-size: 11px;
  transition: background-color var(--duration-fast) ease, color var(--duration-fast) ease;
}

.tags-mode-switch button.active {
  background: #f5f5f7;
  color: #0a0a0c;
  font-weight: 500;
}

.field-old {
  padding-left: 23px;
  font-size: 11.5px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.field-new {
  padding-left: 23px;
  font-size: 13px;
  font-weight: 400;
  color: #f4f4f5;
  line-height: 1.5;
  word-break: break-word;
}

.field-new.empty {
  font-size: 12px;
  color: var(--text-muted);
}

.new-tags-flow {
  padding-left: 23px;
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 2px;
}

.new-tag-chip {
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.09);
  color: var(--text-primary);
  font-size: 11.5px;
}

.desc-box {
  margin-left: 23px;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.24);
  max-height: 150px;
  overflow-y: auto;
  white-space: pre-line;
  font-size: 12.5px;
  line-height: 1.65;
  color: rgba(244, 244, 245, 0.9);
  cursor: text;
}

/* 底部操作栏 */
.mp-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 13px 22px;
  border-top: 1px solid var(--divider-subtle);
  flex-shrink: 0;
}

.mp-count {
  font-size: 12px;
  color: var(--text-muted);
}

.mp-foot-actions {
  display: flex;
  gap: 8px;
}

@media (max-width: 720px) {
  .mp-split {
    flex-direction: column;
  }
  .mp-left {
    width: 100%;
    max-height: 200px;
    border-right: none;
    border-bottom: 1px solid var(--divider-subtle);
  }
}
</style>
