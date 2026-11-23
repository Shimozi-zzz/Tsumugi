<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  externalImportApi,
  isDesktopBridgeAvailable,
  pickNativeFile,
  pickNativeFolder,
} from '@/api/client'
import { useLibraryStore } from '@/stores/library'
import type {
  ExternalDetectResponse,
  ExternalDuplicateStrategy,
  ExternalExecuteResponse,
  ExternalGameCandidate,
  ExternalImportSource,
} from '@/types'

const store = useLibraryStore()
const hasBridge = isDesktopBridgeAvailable()

const sources: { id: ExternalImportSource; label: string; desc: string }[] = [
  { id: 'playnite', label: 'Playnite', desc: 'LiteDB v4 / Playnite 9' },
  { id: 'vnite', label: 'Vnite', desc: '数据目录 / JSON · ZIP 备份' },
]

const activeSource = ref<ExternalImportSource>(store.externalImportSource || 'playnite')
const step = ref<1 | 2>(1)

// Step 1: 路径探测与扫描
const detecting = ref(false)
const detectInfo = ref<ExternalDetectResponse | null>(null)
const inputPath = ref('')
const scanning = ref(false)
const scanError = ref('')

// Step 2: 候选列表预览与勾选
const candidates = ref<ExternalGameCandidate[]>([])
const scanStats = ref({ total: 0, new: 0, existing: 0 })
const selectedIds = ref<Set<string>>(new Set())
const searchQuery = ref('')
const duplicateStrategy = ref<ExternalDuplicateStrategy>('skip')
const executing = ref(false)
const executeResult = ref<ExternalExecuteResponse | null>(null)

const filteredCandidates = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return candidates.value
  return candidates.value.filter((item) => {
    const haystack = [
      item.name,
      item.original_name,
      item.platform_source,
      ...item.developers,
      ...item.publishers,
      ...item.tags,
    ]
      .join(' ')
      .toLowerCase()
    return haystack.includes(q)
  })
})

const selectedCount = computed(() => selectedIds.value.size)

const selectedExistingCount = computed(() => {
  let count = 0
  for (const item of candidates.value) {
    if (item.exists_in_tsumugi && selectedIds.value.has(item.external_id)) {
      count++
    }
  }
  return count
})

const pathPlaceholder = computed(() =>
  activeSource.value === 'playnite'
    ? '例如 C:\\Users\\你的用户名\\AppData\\Roaming\\Playnite\\library 或便携版目录'
    : '填写 Vnite 数据目录，或导出的 .json / .zip 备份文件路径',
)

const pathHint = computed(() =>
  activeSource.value === 'playnite'
    ? '自动以只读快照方式读取 Playnite 的 games.db（含 Playnite 9 JSON 目录），不会影响运行中的 Playnite，封面与背景图会独立拷贝到 Tsumugi 本地目录。'
    : '支持自动扫描 Vnite 本地数据目录，或直接填写 Vnite 导出的 .json / .zip 备份文件路径；若本地为加密/二进制 LevelDB，请先在 Vnite 中导出备份文件。',
)

function closeModal() {
  if (executing.value) return
  store.showExternalImportModal = false
}

async function runDetect(source: ExternalImportSource) {
  detecting.value = true
  scanError.value = ''
  detectInfo.value = null
  try {
    const res = await externalImportApi.detect(source)
    if (activeSource.value !== source) return
    const isFound = Boolean(res.found ?? res.valid)
    const detected = (res.path || res.detected_path || '').trim()
    detectInfo.value = {
      ...res,
      found: isFound,
      valid: isFound,
      path: isFound ? detected : '',
      detected_path: isFound ? detected : '',
      message: res.message || (isFound ? '已自动检测到默认路径' : '未自动检测到默认路径，请手动输入路径或选择目录'),
    }
    inputPath.value = isFound ? detected : ''
  } catch {
    if (activeSource.value !== source) return
    // 自动探测失败时使用中性灰色提示条引导手动输入，不触发红色报错弹窗
    detectInfo.value = {
      source,
      found: false,
      valid: false,
      path: '',
      detected_path: '',
      message: '未自动检测到默认路径，请手动输入路径或选择目录',
    }
    inputPath.value = ''
  } finally {
    if (activeSource.value === source) {
      detecting.value = false
    }
  }
}

function switchSource(source: ExternalImportSource) {
  if (executing.value) return
  if (activeSource.value === source && step.value === 1) return
  activeSource.value = source
  step.value = 1
  candidates.value = []
  selectedIds.value = new Set()
  searchQuery.value = ''
  scanError.value = ''
  executeResult.value = null
  void runDetect(source)
}

async function pickDirectory() {
  const title =
    activeSource.value === 'playnite'
      ? '选择 Playnite 游戏库目录（library 或便携版根目录）'
      : '选择 Vnite 数据目录'
  const picked = await pickNativeFolder(title)
  if (picked) {
    inputPath.value = picked
    scanError.value = ''
  }
}

async function pickBackupFile() {
  const picked = await pickNativeFile('选择 Vnite 导出的备份文件 (.json / .zip)', [
    'Vnite 备份 (*.json;*.zip)',
    'All files (*.*)',
  ])
  if (picked) {
    inputPath.value = picked
    scanError.value = ''
  }
}

async function runScan() {
  const target = inputPath.value.trim()
  if (!target) {
    scanError.value = '请先填写或选择外部游戏库路径'
    return
  }
  scanning.value = true
  scanError.value = ''
  executeResult.value = null
  try {
    const res = await externalImportApi.scan(activeSource.value, target)
    candidates.value = res.items || []
    scanStats.value = res.stats || {
      total: candidates.value.length,
      new: candidates.value.filter((c) => !c.exists_in_tsumugi).length,
      existing: candidates.value.filter((c) => c.exists_in_tsumugi).length,
    }
    // 默认勾选所有尚未入库的条目
    const nextSelected = new Set<string>()
    for (const item of candidates.value) {
      if (!item.exists_in_tsumugi) {
        nextSelected.add(item.external_id)
      }
    }
    selectedIds.value = nextSelected
    searchQuery.value = ''
    step.value = 2
  } catch (err) {
    scanError.value = err instanceof Error ? err.message : '扫描外部游戏库失败'
  } finally {
    scanning.value = false
  }
}

function toggleItem(externalId: string) {
  const next = new Set(selectedIds.value)
  if (next.has(externalId)) {
    next.delete(externalId)
  } else {
    next.add(externalId)
  }
  selectedIds.value = next
}

function selectAllFiltered() {
  const next = new Set(selectedIds.value)
  for (const item of filteredCandidates.value) {
    next.add(item.external_id)
  }
  selectedIds.value = next
}

function invertFilteredSelection() {
  const next = new Set(selectedIds.value)
  for (const item of filteredCandidates.value) {
    if (next.has(item.external_id)) {
      next.delete(item.external_id)
    } else {
      next.add(item.external_id)
    }
  }
  selectedIds.value = next
}

function selectOnlyNew() {
  const next = new Set<string>()
  for (const item of candidates.value) {
    if (!item.exists_in_tsumugi) {
      next.add(item.external_id)
    }
  }
  selectedIds.value = next
}

function formatPlaytime(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds || 0))
  if (s === 0) return '未游玩'
  if (s < 60) return `${s} 秒`
  const mins = Math.floor(s / 60)
  if (mins < 60) return `${mins} 分钟`
  return `${(s / 3600).toFixed(1)} 小时`
}

function statusLabel(status: string): string {
  const s = (status || '').toLowerCase()
  if (s === 'done' || s === 'completed') return '已通关'
  if (s === 'playing') return '攻略中'
  return '未开始'
}

async function runImport() {
  if (selectedIds.value.size === 0) {
    store.notify('请至少勾选一款待导入的游戏', 'warning')
    return
  }
  executing.value = true
  try {
    const res = await externalImportApi.execute(activeSource.value, {
      path: inputPath.value.trim(),
      selected_ids: Array.from(selectedIds.value),
      duplicate_strategy: duplicateStrategy.value,
    })
    executeResult.value = res
    await store.refreshGames()
    store.bumpAssetVersion()

    const focusId =
      res.imported_ids?.[res.imported_ids.length - 1] ??
      res.merged_ids?.[res.merged_ids.length - 1]
    if (focusId != null) {
      await store.selectGame(focusId, { switchToDetail: store.games.length === res.imported })
    }

    const parts: string[] = []
    if (res.imported > 0) parts.push(`新导入 ${res.imported} 款`)
    if (res.merged > 0) parts.push(`合并 ${res.merged} 款`)
    if (res.skipped > 0) parts.push(`跳过 ${res.skipped} 款`)
    store.notify(
      parts.length > 0 ? `外部库导入完成：${parts.join('，')}` : '导入完成，未产生变更',
      res.errors?.length ? 'warning' : 'success',
    )
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '执行外部导入失败', 'error')
  } finally {
    executing.value = false
  }
}

onMounted(() => {
  void runDetect(activeSource.value)
})
</script>

<template>
  <div class="modal-backdrop" @click.self="closeModal">
    <div class="modal-card ext-import-card">
      <!-- 顶部标题与关闭 -->
      <div class="modal-head">
        <div class="head-title-wrap">
          <h2>导入外部游戏库</h2>
          <span class="head-sub">从 Playnite 或 Vnite 迁移收藏、游玩时长与本地封面</span>
        </div>
        <button class="close-icon-btn" aria-label="关闭" :disabled="executing" @click="closeModal">
          <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" />
          </svg>
        </button>
      </div>

      <!-- 顶部来源切换标签：Playnite | Vnite -->
      <div class="source-tabs" role="tablist" aria-label="外部游戏库来源">
        <button
          v-for="src in sources"
          :key="src.id"
          type="button"
          role="tab"
          class="source-tab-btn"
          :class="{ active: activeSource === src.id }"
          :aria-selected="activeSource === src.id"
          @click="switchSource(src.id)"
        >
          <span class="source-tab-name">{{ src.label }}</span>
          <span class="source-tab-desc">{{ src.desc }}</span>
        </button>

        <div class="step-indicator tabular-nums">
          <span :class="{ active: step === 1 }">1. 选择路径</span>
          <span class="step-sep">→</span>
          <span :class="{ active: step === 2 }">2. 预览与勾选</span>
        </div>
      </div>

      <!-- 主体区域 -->
      <div class="modal-body">
        <!-- ══════════ 步骤一：选择路径 ══════════ -->
        <section v-if="step === 1" class="step-panel">
          <div class="detect-banner" :class="{ valid: Boolean(detectInfo?.found ?? detectInfo?.valid) }">
            <span class="detect-dot" />
            <span v-if="detecting">正在自动探测本地 {{ activeSource === 'playnite' ? 'Playnite' : 'Vnite' }} 路径…</span>
            <span v-else-if="detectInfo">{{ detectInfo.message }}</span>
            <span v-else>未自动检测到默认路径，请手动输入路径或选择目录</span>
          </div>

          <div class="field-group">
            <label class="field-label">
              {{ activeSource === 'playnite' ? 'Playnite 游戏库路径' : 'Vnite 数据目录或备份文件路径' }}
            </label>
            <div class="path-input-row">
              <input
                v-model="inputPath"
                type="text"
                class="input path-input"
                :placeholder="pathPlaceholder"
                @keydown.enter="runScan"
              />
              <button
                v-if="hasBridge"
                type="button"
                class="btn btn-sm"
                @click="pickDirectory"
              >
                选目录
              </button>
              <button
                v-if="hasBridge && activeSource === 'vnite'"
                type="button"
                class="btn btn-sm"
                @click="pickBackupFile"
              >
                选备份文件
              </button>
              <button
                type="button"
                class="btn btn-ghost btn-sm"
                :disabled="detecting"
                title="重新自动探测"
                @click="runDetect(activeSource)"
              >
                重新探测
              </button>
            </div>
            <p class="field-hint">{{ pathHint }}</p>
          </div>

          <div v-if="scanError" class="error-banner" role="alert">
            <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8">
              <circle cx="10" cy="10" r="8" />
              <path d="M10 6v4.5M10 13.5h.01" stroke-linecap="round" />
            </svg>
            <span>{{ scanError }}</span>
          </div>

          <div class="step1-actions">
            <button
              type="button"
              class="btn btn-primary"
              :disabled="scanning || !inputPath.trim()"
              @click="runScan"
            >
              <svg v-if="!scanning" viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.9">
                <circle cx="9" cy="9" r="5.5" />
                <path d="M13.5 13.5L17 17" stroke-linecap="round" />
              </svg>
              <span>{{ scanning ? '正在扫描游戏库…' : '扫描游戏库' }}</span>
            </button>
          </div>
        </section>

        <!-- ══════════ 步骤二：预览与勾选 / 导入结果 ══════════ -->
        <section v-else class="step-panel step2-panel">
          <!-- 导入结果汇总视图 -->
          <div v-if="executeResult" class="result-card">
            <div class="result-head">
              <div class="result-icon">
                <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.2">
                  <path d="M5 13l4 4L19 7" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </div>
              <div>
                <h3>导入已完成</h3>
                <p>主游戏库已自动刷新，拷贝的封面与背景已独立落盘至本地 data/ 目录。</p>
              </div>
            </div>

            <div class="result-metrics tabular-nums">
              <div class="metric-box metric-imported">
                <span class="metric-value">{{ executeResult.imported }}</span>
                <span class="metric-label">新导入</span>
              </div>
              <div class="metric-box metric-merged">
                <span class="metric-value">{{ executeResult.merged }}</span>
                <span class="metric-label">已合并时长</span>
              </div>
              <div class="metric-box metric-skipped">
                <span class="metric-value">{{ executeResult.skipped }}</span>
                <span class="metric-label">已跳过</span>
              </div>
              <div class="metric-box" :class="{ 'metric-error': executeResult.errors.length > 0 }">
                <span class="metric-value">{{ executeResult.errors.length }}</span>
                <span class="metric-label">失败条目</span>
              </div>
            </div>

            <div v-if="executeResult.errors.length > 0" class="result-errors">
              <div class="result-errors-title">部分条目处理失败：</div>
              <ul>
                <li v-for="(err, idx) in executeResult.errors" :key="idx">
                  <strong>{{ err.name || err.external_id }}</strong>：{{ err.error }}
                </li>
              </ul>
            </div>

            <div class="result-actions">
              <button type="button" class="btn" @click="step = 1; executeResult = null">
                继续导入其他库
              </button>
              <button type="button" class="btn btn-primary" @click="closeModal">
                完成并返回游戏库
              </button>
            </div>
          </div>

          <!-- 候选游戏预览与勾选视图 -->
          <template v-else>
            <div class="preview-toolbar">
              <div class="toolbar-top">
                <button type="button" class="btn btn-ghost btn-sm" @click="step = 1">
                  ← 修改路径
                </button>

                <div class="stats-pills tabular-nums">
                  <span class="stat-pill">共 {{ scanStats.total }} 款</span>
                  <span class="stat-pill pill-new">新增 {{ scanStats.new }}</span>
                  <span class="stat-pill pill-existing">已入库 {{ scanStats.existing }}</span>
                </div>
              </div>

              <div class="toolbar-controls">
                <input
                  v-model="searchQuery"
                  type="text"
                  class="input filter-input"
                  placeholder="搜索标题、原名、开发商或来源…"
                />

                <div class="bulk-btns">
                  <button type="button" class="btn btn-sm" @click="selectAllFiltered">全选</button>
                  <button type="button" class="btn btn-sm" @click="selectOnlyNew">仅未入库</button>
                  <button type="button" class="btn btn-sm" @click="invertFilteredSelection">反选</button>
                </div>
              </div>

              <div class="strategy-bar">
                <span class="strategy-label">重复条目处理策略：</span>
                <div class="strategy-toggle">
                  <button
                    type="button"
                    class="strategy-btn"
                    :class="{ active: duplicateStrategy === 'skip' }"
                    @click="duplicateStrategy = 'skip'"
                  >
                    跳过已存在
                  </button>
                  <button
                    type="button"
                    class="strategy-btn"
                    :class="{ active: duplicateStrategy === 'merge_playtime' }"
                    @click="duplicateStrategy = 'merge_playtime'"
                  >
                    合并游玩时长
                  </button>
                </div>
                <span class="strategy-desc">
                  {{
                    duplicateStrategy === 'skip'
                      ? '保留库内已有条目不做改动'
                      : '保留现有资料，游玩时长取较大值并补齐缺失封面与外部 ID'
                  }}
                </span>
              </div>
            </div>

            <!-- 游戏候选列表 -->
            <div class="candidate-list">
              <div v-if="filteredCandidates.length === 0" class="empty-candidates">
                {{ candidates.length === 0 ? '该路径下未扫描到任何游戏条目' : '没有匹配当前筛选条件的作品' }}
              </div>

              <label
                v-for="item in filteredCandidates"
                :key="item.external_id"
                class="candidate-row"
                :class="{
                  selected: selectedIds.has(item.external_id),
                  existing: item.exists_in_tsumugi,
                }"
              >
                <input
                  type="checkbox"
                  class="row-checkbox"
                  :checked="selectedIds.has(item.external_id)"
                  @change="toggleItem(item.external_id)"
                />

                <div class="row-main">
                  <div class="row-title-line">
                    <span class="row-title" :title="item.name">{{ item.name }}</span>
                    <span class="badge badge-source">
                      {{ item.platform_source || (item.source_app === 'playnite' ? 'Playnite' : 'Vnite') }}
                    </span>
                    <span
                      class="badge"
                      :class="item.exists_in_tsumugi ? 'badge-existing' : 'badge-new'"
                    >
                      {{ item.exists_in_tsumugi ? '已入库' : '新作品' }}
                    </span>
                  </div>
                  <div class="row-sub-line">
                    <span v-if="item.original_name" class="sub-item">{{ item.original_name }}</span>
                    <span v-if="item.developers.length" class="sub-item">{{ item.developers.join(' / ') }}</span>
                    <span v-if="item.release_date" class="sub-item tabular-nums">{{ item.release_date }}</span>
                    <span class="sub-item">{{ statusLabel(item.play_status) }}</span>
                  </div>
                </div>

                <div class="row-meta tabular-nums">
                  <span class="meta-playtime" :class="{ muted: item.playtime_seconds === 0 }">
                    {{ formatPlaytime(item.playtime_seconds) }}
                  </span>
                  <span
                    class="badge"
                    :class="item.cover_path ? 'badge-cover-ok' : 'badge-cover-none'"
                    :title="item.cover_path || '未找到本地封面图片'"
                  >
                    {{ item.cover_path ? (item.background_path ? '封面 + 背景' : '本地封面') : '无封面' }}
                  </span>
                </div>
              </label>
            </div>

            <!-- 底部执行栏 -->
            <div class="preview-footer">
              <div class="footer-info tabular-nums">
                <span>已勾选 <strong>{{ selectedCount }}</strong> 款作品</span>
                <span v-if="selectedExistingCount > 0" class="footer-sub">
                  （含 {{ selectedExistingCount }} 款已入库：将{{
                    duplicateStrategy === 'merge_playtime' ? '合并时长' : '自动跳过'
                  }}）
                </span>
              </div>

              <div class="footer-actions">
                <button type="button" class="btn btn-ghost" :disabled="executing" @click="closeModal">
                  取消
                </button>
                <button
                  type="button"
                  class="btn btn-primary"
                  :disabled="executing || selectedCount === 0"
                  @click="runImport"
                >
                  {{ executing ? '正在导入并拷贝封面…' : `开始导入 (${selectedCount})` }}
                </button>
              </div>
            </div>
          </template>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ext-import-card {
  max-width: 820px;
  height: min(760px, 88vh);
}

.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px 14px;
  border-bottom: 1px solid var(--divider-subtle);
}

.head-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.modal-head h2 {
  margin: 0;
  font-size: 16.5px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--text-primary);
}

.head-sub {
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
  transition: background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.close-icon-btn:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--text-primary);
}

/* Source Switcher Tabs */
.source-tabs {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 22px;
  border-bottom: 1px solid var(--divider-subtle);
  background: rgba(255, 255, 255, 0.015);
}

.source-tab-btn {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
  padding: 7px 14px;
  border-radius: 999px;
  border: 1px solid transparent;
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-secondary);
  transition: background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo),
    border-color var(--duration-fast) var(--ease-out-expo);
}

.source-tab-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
}

.source-tab-btn.active {
  background: var(--cta-bg);
  color: var(--cta-text);
}

.source-tab-name {
  font-size: 13px;
  font-weight: 600;
}

.source-tab-desc {
  font-size: 11px;
  opacity: 0.72;
}

.step-indicator {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
  color: var(--text-muted);
}

.step-indicator .active {
  color: var(--text-primary);
  font-weight: 500;
}

.step-sep {
  opacity: 0.4;
}

/* Modal Body */
.modal-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 18px 22px 20px;
  overflow: hidden;
}

.step-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  min-height: 0;
}

.detect-banner {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
  font-size: 12.5px;
  color: var(--text-secondary);
}

.detect-banner.valid {
  background: rgba(16, 185, 129, 0.08);
  border-color: rgba(16, 185, 129, 0.2);
  color: var(--emerald-text);
}

.detect-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--text-muted);
}

.detect-banner.valid .detect-dot {
  background: var(--emerald);
}

.field-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-label {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-secondary);
}

.path-input-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.path-input {
  flex: 1;
  font-family: var(--font-mono);
  font-size: 12.5px;
}

.field-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-muted);
}

.error-banner {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 11px 14px;
  border-radius: 10px;
  background: var(--danger-bg);
  border: 1px solid rgba(239, 68, 68, 0.25);
  color: var(--danger-text);
  font-size: 12.5px;
  line-height: 1.55;
}

.error-banner svg {
  flex-shrink: 0;
  margin-top: 2px;
}

.step1-actions {
  margin-top: auto;
  display: flex;
  justify-content: flex-end;
  padding-top: 12px;
  border-top: 1px solid var(--divider-subtle);
}

/* Step 2 Toolbar & List */
.step2-panel {
  gap: 12px;
}

.preview-toolbar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex-shrink: 0;
}

.toolbar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.stats-pills {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.stat-pill {
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11.5px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-secondary);
}

.stat-pill.pill-new {
  background: rgba(16, 185, 129, 0.14);
  color: var(--emerald-text);
}

.stat-pill.pill-existing {
  background: rgba(245, 158, 11, 0.12);
  color: var(--amber-text);
}

.toolbar-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-input {
  flex: 1;
  padding: 7px 12px;
  font-size: 12.5px;
}

.bulk-btns {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.strategy-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--divider-subtle);
}

.strategy-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.strategy-toggle {
  display: inline-flex;
  padding: 2px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.06);
}

.strategy-btn {
  padding: 4px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 500;
  transition: background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.strategy-btn.active {
  background: var(--cta-bg);
  color: var(--cta-text);
}

.strategy-desc {
  font-size: 11.5px;
  color: var(--text-muted);
}

.candidate-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-right: 4px;
}

.empty-candidates {
  padding: 48px 16px;
  text-align: center;
  font-size: 13px;
  color: var(--text-muted);
}

.candidate-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid rgba(255, 255, 255, 0.05);
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-out-expo),
    border-color var(--duration-fast) var(--ease-out-expo);
}

.candidate-row:hover {
  background: rgba(255, 255, 255, 0.055);
}

.candidate-row.selected {
  background: rgba(255, 255, 255, 0.07);
  border-color: rgba(255, 255, 255, 0.16);
}

.candidate-row.existing {
  opacity: 0.88;
}

.row-checkbox {
  width: 16px;
  height: 16px;
  accent-color: #f5f5f7;
  flex-shrink: 0;
  cursor: pointer;
}

.row-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.row-title-line {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.row-title {
  font-size: 13.5px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.row-sub-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 11.5px;
  color: var(--text-muted);
}

.sub-item {
  max-width: 240px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.row-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.meta-playtime {
  font-size: 12px;
  color: var(--text-secondary);
  min-width: 56px;
  text-align: right;
}

.meta-playtime.muted {
  color: var(--text-muted);
}

.badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 10.5px;
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
}

.badge-source {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
}

.badge-new {
  background: rgba(16, 185, 129, 0.14);
  color: var(--emerald-text);
}

.badge-existing {
  background: rgba(245, 158, 11, 0.14);
  color: var(--amber-text);
}

.badge-cover-ok {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
}

.badge-cover-none {
  background: rgba(255, 255, 255, 0.03);
  color: var(--text-muted);
}

.preview-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--divider-subtle);
  flex-shrink: 0;
}

.footer-info {
  font-size: 12.5px;
  color: var(--text-secondary);
}

.footer-info strong {
  color: var(--text-primary);
}

.footer-sub {
  font-size: 11.5px;
  color: var(--text-muted);
}

.footer-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

/* Result Summary Card */
.result-card {
  display: flex;
  flex-direction: column;
  gap: 18px;
  margin: auto 0;
  padding: 20px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border-subtle);
}

.result-head {
  display: flex;
  align-items: center;
  gap: 14px;
}

.result-icon {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: var(--emerald-bg);
  color: var(--emerald-text);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.result-head h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.result-head p {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: var(--text-secondary);
}

.result-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.metric-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 14px 10px;
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.04);
}

.metric-value {
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
}

.metric-label {
  font-size: 11.5px;
  color: var(--text-muted);
}

.metric-imported .metric-value {
  color: var(--emerald-text);
}

.metric-merged .metric-value {
  color: var(--amber-text);
}

.metric-error .metric-value {
  color: var(--danger-text);
}

.result-errors {
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--danger-bg);
  color: var(--danger-text);
  font-size: 12px;
}

.result-errors-title {
  font-weight: 600;
  margin-bottom: 6px;
}

.result-errors ul {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.result-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
