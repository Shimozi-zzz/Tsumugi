<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { assetUrl, statsApi } from '@/api/client'
import JourneyCollagePanel from '@/components/JourneyCollagePanel.vue'
import { useLibraryStore } from '@/stores/library'
import type { LedgerHeatmapDay, TimeLedgerResponse } from '@/types'

const store = useLibraryStore()
const activeTab = ref<'overview' | 'collage'>('overview')
const loading = ref(true)
const errorMsg = ref('')
const ledger = ref<TimeLedgerResponse | null>(null)
const activeDateKey = ref<string | null>(null)

interface CalendarCell {
  date: string
  inRange: boolean
  seconds: number
  level: 0 | 1 | 2 | 3 | 4
  detail: LedgerHeatmapDay | null
}

function formatDurationShort(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  if (s === 0) return '0 分钟'
  if (s < 60) return `${s} 秒`
  const mins = Math.floor(s / 60)
  if (mins < 60) return `${mins} 分钟`
  const hours = s / 3600
  return hours >= 10 ? `${hours.toFixed(1)} 小时` : `${hours.toFixed(1)} 小时`
}

function formatHoursBrief(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  if (s === 0) return '0h'
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m`
  return `${(s / 3600).toFixed(1)}h`
}

function formatDateTime(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatDateShort(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function toIsoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const heatmapMap = computed(() => {
  const map = new Map<string, LedgerHeatmapDay>()
  for (const item of ledger.value?.heatmap || []) {
    map.set(item.date, item)
  }
  return map
})

const maxDaySeconds = computed(() => {
  let max = 0
  for (const item of ledger.value?.heatmap || []) {
    if (item.total_seconds > max) max = item.total_seconds
  }
  return max
})

const heatmapWeeks = computed(() => {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const start = new Date(today)
  start.setDate(start.getDate() - 364)

  // 回退到该周的周日，对齐 52~53 列 7 行网格
  const gridStart = new Date(start)
  gridStart.setDate(gridStart.getDate() - gridStart.getDay())

  const weeks: { cells: CalendarCell[]; monthLabel: string }[] = []
  const cursor = new Date(gridStart)
  let lastLabeledMonth = -1
  const maxSec = maxDaySeconds.value

  while (cursor <= today) {
    const cells: CalendarCell[] = []
    let monthLabel = ''
    for (let dow = 0; dow < 7; dow++) {
      const iso = toIsoDate(cursor)
      const inRange = cursor >= start && cursor <= today
      const detail = inRange ? heatmapMap.value.get(iso) || null : null
      const seconds = detail?.total_seconds || 0

      let level: 0 | 1 | 2 | 3 | 4 = 0
      if (seconds > 0) {
        if (maxSec <= 60) {
          level = 3
        } else {
          const ratio = seconds / maxSec
          if (ratio >= 0.75) level = 4
          else if (ratio >= 0.45) level = 3
          else if (ratio >= 0.2) level = 2
          else level = 1
        }
      }

      if (dow === 0 && inRange) {
        const m = cursor.getMonth()
        if (m !== lastLabeledMonth) {
          monthLabel = `${m + 1}月`
          lastLabeledMonth = m
        }
      }

      cells.push({ date: iso, inRange, seconds, level, detail })
      cursor.setDate(cursor.getDate() + 1)
    }
    weeks.push({ cells, monthLabel })
  }
  return weeks
})

const selectedDayDetail = computed(() => {
  if (!activeDateKey.value) return null
  return {
    date: activeDateKey.value,
    detail: heatmapMap.value.get(activeDateKey.value) || null,
  }
})

const maxMonthSeconds = computed(() => {
  let max = 0
  for (const m of ledger.value?.monthly || []) {
    if (m.total_seconds > max) max = m.total_seconds
  }
  return max
})

const maxTopGameSeconds = computed(() => {
  const first = ledger.value?.top_games?.[0]
  return first ? Math.max(first.total_seconds, 1) : 1
})

function close() {
  store.showTimeLedger = false
}

function jumpToGame(gameId: number) {
  void store.selectGame(gameId, { switchToDetail: true })
  close()
}

function isGameBlurred(isNsfw: boolean): boolean {
  return store.privacyBlurMode && isNsfw
}

async function fetchLedger() {
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await statsApi.ledger(365)
    ledger.value = res
    if (res.heatmap.length > 0) {
      activeDateKey.value = res.heatmap[res.heatmap.length - 1].date
    }
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : '加载时间账本失败'
  } finally {
    loading.value = false
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') close()
}

onMounted(() => {
  void fetchLedger()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="modal-backdrop" @click.self="close">
    <div class="modal-card ledger-window" :class="{ 'is-collage': activeTab === 'collage' }">
      <header class="ledger-head">
        <div class="ledger-head-left">
          <div class="ledger-title-group">
            <h2>时间账本</h2>
            <span class="ledger-en">TIME LEDGER</span>
          </div>

          <nav class="ledger-tabs" role="tablist" aria-label="时间账本视图切换">
            <button
              type="button"
              role="tab"
              class="ledger-tab"
              :class="{ active: activeTab === 'overview' }"
              :aria-selected="activeTab === 'overview'"
              @click="activeTab = 'overview'"
            >
              游玩总览
            </button>
            <button
              type="button"
              role="tab"
              class="ledger-tab"
              :class="{ active: activeTab === 'collage' }"
              :aria-selected="activeTab === 'collage'"
              @click="activeTab = 'collage'"
            >
              历程拼图
            </button>
          </nav>
        </div>
        <button type="button" class="close-icon-btn" aria-label="关闭时间账本" @click="close">
          <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" />
          </svg>
        </button>
      </header>

      <template v-if="activeTab === 'overview'">
        <div v-if="loading" class="ledger-state">
          <div class="spinner" />
          <span>正在汇总游玩轨迹…</span>
        </div>

        <div v-else-if="errorMsg" class="ledger-state error">
          <span>{{ errorMsg }}</span>
        </div>

        <div v-else-if="ledger" class="ledger-body">
        <!-- 顶部核心指标卡 -->
        <section class="kpi-grid">
          <div class="kpi-card">
            <span class="kpi-label">总游玩时长</span>
            <strong class="kpi-value tabular-nums">{{ formatDurationShort(ledger.summary.total_seconds) }}</strong>
            <span class="kpi-sub tabular-nums">{{ ledger.summary.total_sessions }} 次会话记录</span>
          </div>

          <div class="kpi-card">
            <span class="kpi-label">累计活跃天数</span>
            <strong class="kpi-value tabular-nums">{{ ledger.summary.active_days }} 天</strong>
            <span class="kpi-sub tabular-nums">当前连续 {{ ledger.summary.current_streak }} 天</span>
          </div>

          <div class="kpi-card">
            <span class="kpi-label">最长连续游玩</span>
            <strong class="kpi-value tabular-nums">{{ ledger.summary.longest_streak }} 天</strong>
            <span class="kpi-sub">最高连续记录</span>
          </div>

          <div class="kpi-card">
            <span class="kpi-label">在库 / 已通关</span>
            <strong class="kpi-value tabular-nums">
              {{ ledger.summary.total_games }}
              <span class="kpi-slash">/</span>
              {{ ledger.summary.done_games }}
            </strong>
            <span class="kpi-sub tabular-nums">攻略中 {{ ledger.summary.playing_games }} 部</span>
          </div>
        </section>

        <!-- GitHub 风格 52 周年度游玩热力图 -->
        <section class="ledger-panel">
          <div class="panel-head">
            <h3>年度游玩热力图</h3>
            <div class="heatmap-legend">
              <span>少</span>
              <i class="cell lv-0" />
              <i class="cell lv-1" />
              <i class="cell lv-2" />
              <i class="cell lv-3" />
              <i class="cell lv-4" />
              <span>多</span>
            </div>
          </div>

          <div class="heatmap-scroll">
            <div class="heatmap-canvas">
              <div class="weekday-col">
                <span />
                <span>一</span>
                <span />
                <span>三</span>
                <span />
                <span>五</span>
                <span />
              </div>

              <div class="weeks-wrap">
                <div class="month-row">
                  <span v-for="(wk, i) in heatmapWeeks" :key="i" class="month-tick">
                    {{ wk.monthLabel }}
                  </span>
                </div>
                <div class="week-cols">
                  <div v-for="(wk, wIdx) in heatmapWeeks" :key="wIdx" class="week-col">
                    <button
                      v-for="cell in wk.cells"
                      :key="cell.date"
                      type="button"
                      class="cell"
                      :class="[
                        `lv-${cell.level}`,
                        {
                          'out-range': !cell.inRange,
                          selected: activeDateKey === cell.date,
                        },
                      ]"
                      :disabled="!cell.inRange"
                      :title="`${cell.date} · ${formatDurationShort(cell.seconds)}`"
                      @mouseenter="cell.inRange && (activeDateKey = cell.date)"
                      @click="cell.inRange && (activeDateKey = cell.date)"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 选中/悬停单日游玩明细条 -->
          <div class="day-inspector">
            <template v-if="selectedDayDetail">
              <div class="day-head">
                <span class="day-date tabular-nums">{{ selectedDayDetail.date }}</span>
                <span class="day-total tabular-nums">
                  {{
                    selectedDayDetail.detail
                      ? `累计 ${formatDurationShort(selectedDayDetail.detail.total_seconds)} · ${selectedDayDetail.detail.sessions_count} 次`
                      : '当日无游玩记录'
                  }}
                </span>
              </div>
              <div v-if="selectedDayDetail.detail?.games.length" class="day-games">
                <button
                  v-for="g in selectedDayDetail.detail.games"
                  :key="g.game_id"
                  type="button"
                  class="day-game-pill"
                  @click="jumpToGame(g.game_id)"
                >
                  <span>{{ g.title }}</span>
                  <span class="pill-dur tabular-nums">{{ formatDurationShort(g.duration_seconds) }}</span>
                </button>
              </div>
            </template>
            <span v-else class="day-placeholder">悬停或点击任意日期查看当日游玩明细</span>
          </div>
        </section>

        <!-- 近 12 个月极简月度柱状图 -->
        <section class="ledger-panel">
          <div class="panel-head">
            <h3>近 12 个月时长分布</h3>
          </div>
          <div class="monthly-bars">
            <div v-for="m in ledger.monthly" :key="m.month" class="month-col">
              <span class="bar-val tabular-nums">
                {{ m.total_seconds > 0 ? formatHoursBrief(m.total_seconds) : '' }}
              </span>
              <div class="bar-track">
                <div
                  class="bar-fill"
                  :style="{
                    height:
                      maxMonthSeconds > 0 && m.total_seconds > 0
                        ? `${Math.max(8, Math.round((m.total_seconds / maxMonthSeconds) * 100))}%`
                        : '2px',
                    opacity: m.total_seconds > 0 ? 1 : 0.16,
                  }"
                />
              </div>
              <span class="bar-month tabular-nums">{{ m.month.slice(5) }}月</span>
            </div>
          </div>
        </section>

        <!-- 底部双栏：作品时长榜 + 近期游玩流水 -->
        <section class="bottom-grid">
          <div class="ledger-panel">
            <div class="panel-head">
              <h3>作品时长榜</h3>
              <span class="panel-count tabular-nums">{{ ledger.top_games.length }}</span>
            </div>

            <div v-if="ledger.top_games.length === 0" class="empty-list">暂无游玩时长记录</div>
            <div v-else class="rank-list">
              <button
                v-for="(g, idx) in ledger.top_games"
                :key="g.game_id"
                type="button"
                class="rank-row"
                @click="jumpToGame(g.game_id)"
              >
                <span class="rank-idx tabular-nums">{{ String(idx + 1).padStart(2, '0') }}</span>
                <div class="row-thumb">
                  <img
                    v-if="g.cover_thumb_path"
                    :src="assetUrl(g.cover_thumb_path, store.assetVersion)"
                    :class="{ 'privacy-blur-img': isGameBlurred(g.is_nsfw) }"
                    alt=""
                  />
                  <span v-else>{{ g.title.slice(0, 1) }}</span>
                </div>
                <div class="rank-main">
                  <div class="rank-top">
                    <span class="rank-title">{{ g.title }}</span>
                    <span class="rank-dur tabular-nums">{{ formatDurationShort(g.total_seconds) }}</span>
                  </div>
                  <div class="rank-bar">
                    <div
                      class="rank-bar-fill"
                      :style="{ width: `${Math.max(4, Math.round((g.total_seconds / maxTopGameSeconds) * 100))}%` }"
                    />
                  </div>
                  <div class="rank-meta tabular-nums">
                    <span>初见 {{ formatDateShort(g.first_played_at) }}</span>
                    <span>最近 {{ formatDateShort(g.last_played_at) }}</span>
                  </div>
                </div>
              </button>
            </div>
          </div>

          <div class="ledger-panel">
            <div class="panel-head">
              <h3>近期游玩流水</h3>
              <span class="panel-count tabular-nums">{{ ledger.recent_sessions.length }}</span>
            </div>

            <div v-if="ledger.recent_sessions.length === 0" class="empty-list">暂无近期会话明细</div>
            <div v-else class="session-list">
              <button
                v-for="s in ledger.recent_sessions"
                :key="s.id"
                type="button"
                class="session-row"
                @click="jumpToGame(s.game_id)"
              >
                <div class="row-thumb">
                  <img
                    v-if="s.cover_thumb_path"
                    :src="assetUrl(s.cover_thumb_path, store.assetVersion)"
                    :class="{ 'privacy-blur-img': isGameBlurred(s.is_nsfw) }"
                    alt=""
                  />
                  <span v-else>{{ s.title.slice(0, 1) }}</span>
                </div>
                <div class="session-main">
                  <div class="session-title">{{ s.title }}</div>
                  <div class="session-time tabular-nums">{{ formatDateTime(s.started_at) }}</div>
                </div>
                <span class="session-dur tabular-nums">{{ formatDurationShort(s.duration_seconds) }}</span>
              </button>
            </div>
          </div>
        </section>
      </div>
      </template>

      <JourneyCollagePanel v-else />
    </div>
  </div>
</template>

<style scoped>
.ledger-window {
  width: 1020px;
  max-width: calc(100vw - 44px);
  height: 86vh;
  transition: width 0.2s ease;
}

.ledger-window.is-collage {
  width: 1120px;
}

.ledger-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 26px;
  min-height: 60px;
  border-bottom: 1px solid var(--divider-subtle);
  flex-shrink: 0;
}

.ledger-head-left {
  display: flex;
  align-items: center;
  gap: 28px;
  height: 60px;
}

.ledger-tabs {
  display: inline-flex;
  align-items: stretch;
  gap: 18px;
  height: 100%;
}

.ledger-tab {
  position: relative;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 13.5px;
  font-weight: 500;
  padding: 0 2px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  transition: color 0.16s ease;
}

.ledger-tab:hover {
  color: var(--text-secondary);
}

.ledger-tab.active {
  color: #f5f5f7;
}

.ledger-tab.active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: #f5f5f7;
}

.ledger-title-group {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.ledger-title-group h2 {
  margin: 0;
  font-family: var(--font-serif);
  font-size: 20px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.ledger-en {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.16em;
  color: var(--text-muted);
  opacity: 0.72;
}

.close-icon-btn {
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 8px;
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

.ledger-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  font-size: 13px;
  color: var(--text-secondary);
}

.ledger-state.error {
  color: var(--danger-text);
}

.spinner {
  width: 22px;
  height: 22px;
  border: 2px solid rgba(255, 255, 255, 0.14);
  border-top-color: #f4f4f5;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.ledger-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 22px 26px 28px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* KPI Grid */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.kpi-card {
  padding: 16px 18px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.028);
  box-shadow: inset 0 1px 0 var(--divider-subtle);
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.kpi-label {
  font-size: 11.5px;
  color: var(--text-muted);
}

.kpi-value {
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
}

.kpi-slash {
  color: var(--text-muted);
  font-weight: 400;
  margin: 0 2px;
}

.kpi-sub {
  font-size: 11.5px;
  color: var(--text-secondary);
}

/* Panels */
.ledger-panel {
  padding: 18px 20px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.025);
  box-shadow: inset 0 1px 0 var(--divider-subtle);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.panel-head h3 {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-primary);
}

.panel-count {
  font-size: 11.5px;
  color: var(--text-muted);
}

/* Annual Heatmap */
.heatmap-legend {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text-muted);
}

.heatmap-scroll {
  overflow-x: auto;
  padding-bottom: 4px;
}

.heatmap-canvas {
  display: flex;
  gap: 8px;
  min-width: max-content;
}

.weekday-col {
  display: grid;
  grid-template-rows: repeat(7, 12px);
  gap: 3px;
  padding-top: 18px;
  font-size: 10px;
  color: var(--text-muted);
  line-height: 12px;
}

.weeks-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.month-row {
  display: flex;
  gap: 3px;
  height: 14px;
}

.month-tick {
  width: 12px;
  font-size: 10px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: visible;
}

.week-cols {
  display: flex;
  gap: 3px;
}

.week-col {
  display: grid;
  grid-template-rows: repeat(7, 12px);
  gap: 3px;
}

.cell {
  display: block;
  width: 12px;
  height: 12px;
  padding: 0;
  border: none;
  border-radius: 3px;
  transition: transform 120ms var(--ease-out-expo), box-shadow 120ms var(--ease-out-expo);
}

.cell.out-range {
  opacity: 0;
  pointer-events: none;
}

.cell.lv-0 {
  background: rgba(255, 255, 255, 0.045);
}

.cell.lv-1 {
  background: rgba(16, 185, 129, 0.24);
}

.cell.lv-2 {
  background: rgba(16, 185, 129, 0.46);
}

.cell.lv-3 {
  background: rgba(16, 185, 129, 0.72);
}

.cell.lv-4 {
  background: #34d399;
}

button.cell:hover,
button.cell.selected {
  transform: scale(1.18);
  box-shadow: 0 0 0 1.5px rgba(244, 244, 245, 0.85);
}

.day-inspector {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.028);
  min-height: 40px;
}

.day-head {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.day-date {
  font-family: var(--font-mono);
  color: var(--text-primary);
  font-weight: 500;
}

.day-total,
.day-placeholder {
  font-size: 12px;
  color: var(--text-muted);
}

.day-games {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.day-game-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 4px 10px;
  border: none;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.07);
  color: var(--text-primary);
  font-size: 11.5px;
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.day-game-pill:hover {
  background: rgba(255, 255, 255, 0.14);
}

.pill-dur {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-secondary);
}

/* Monthly Minimal Bar Chart */
.monthly-bars {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 10px;
  align-items: end;
  height: 112px;
  padding-top: 8px;
}

.month-col {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.bar-val {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  height: 14px;
}

.bar-track {
  flex: 1;
  width: 100%;
  max-width: 22px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.bar-fill {
  width: 100%;
  border-radius: 4px 4px 2px 2px;
  background: linear-gradient(180deg, rgba(244, 244, 245, 0.85), rgba(244, 244, 245, 0.32));
  transition: height 0.42s var(--ease-out-expo);
}

.bar-month {
  font-size: 11px;
  color: var(--text-muted);
}

/* Bottom Two-Column Rankings & Recent Sessions */
.bottom-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.rank-list,
.session-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 300px;
  overflow-y: auto;
}

.rank-row,
.session-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 9px;
  background: transparent;
  text-align: left;
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.rank-row:hover,
.session-row:hover {
  background: var(--surface-hover);
}

.rank-idx {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  width: 20px;
  flex-shrink: 0;
}

.row-thumb {
  width: 28px;
  height: 38px;
  border-radius: 5px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-family: var(--font-serif);
  font-size: 12px;
  color: var(--text-muted);
}

.row-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.rank-main,
.session-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.rank-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.rank-title,
.session-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rank-dur,
.session-dur {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.rank-bar {
  height: 3px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.07);
  overflow: hidden;
}

.rank-bar-fill {
  height: 100%;
  border-radius: 999px;
  background: rgba(244, 244, 245, 0.72);
}

.rank-meta,
.session-time {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--text-muted);
}

.empty-list {
  padding: 28px 0;
  text-align: center;
  font-size: 12.5px;
  color: var(--text-muted);
}

@media (max-width: 820px) {
  .kpi-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .bottom-grid {
    grid-template-columns: 1fr;
  }
}
</style>
