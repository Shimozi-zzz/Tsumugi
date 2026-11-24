<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, gamesApi } from '@/api/client'
import { useLibraryStore } from '@/stores/library'
import type { BangumiSyncResponse, Game, GameNote } from '@/types'

const props = defineProps<{
  game: Game
  notes?: GameNote[]
  activeNote?: GameNote | null
}>()

const emit = defineEmits<{
  close: []
  'need-bind': []
  synced: [res: BangumiSyncResponse]
}>()

const store = useLibraryStore()

const STATUS_MAP: Record<string, string> = {
  todo: '想玩',
  unplayed: '想玩',
  playing: '在玩',
  done: '玩过',
  completed: '玩过',
}

const resolvedBangumiId = computed(() => {
  const g = props.game
  return (
    (g.bangumi_id || '').trim() ||
    String(g.external_ids?.bgm || g.external_ids?.bangumi || '').trim()
  )
})

const bangumiStatusLabel = computed(() => {
  const s = (props.game.status || 'todo').trim().toLowerCase()
  return STATUS_MAP[s] || '想玩'
})

const localOverall = computed<number | null>(() =>
  props.game.rating_overall != null ? Number(props.game.rating_overall) : null,
)

const roundedInitialRate = computed<number | null>(() => {
  if (localOverall.value == null || Number.isNaN(localOverall.value)) return null
  return Math.min(10, Math.max(1, Math.floor(localOverall.value + 0.5)))
})

const syncRating = ref(roundedInitialRate.value != null)
const integerRate = ref<number>(roundedInitialRate.value ?? 8)
const syncComment = ref(Boolean((props.game.short_review || '').trim()))
const commentText = ref((props.game.short_review || '').trim().slice(0, 200))
const isPrivate = ref(Boolean(props.game.is_nsfw))
const submitting = ref(false)

const hasExcerptSource = computed(() => {
  if (props.activeNote && (props.activeNote.content_md || '').trim()) return true
  return Boolean(props.notes?.some((n) => (n.content_md || '').trim()))
})

const isHalfStepRounded = computed(
  () =>
    syncRating.value &&
    localOverall.value != null &&
    Math.abs(localOverall.value - integerRate.value) >= 0.05,
)

function stripMarkdownAndSpoilers(raw: string): string {
  return raw
    .replace(/<details\b[^>]*>[\s\S]*?<\/details>/gi, ' ')
    .replace(/>![\s\S]*?!</g, ' ')
    .replace(/\|\|[^|\n]+?\|\|/g, ' ')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`\n]+)`/g, '$1')
    .replace(/\[([^\]\n]+)\]\([^)\s]+\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^\s*[-*+>\d.]+\s+/gm, '')
    .replace(/[*_~]+/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function fillExcerptFromNote() {
  const sourceNote =
    (props.activeNote && (props.activeNote.content_md || '').trim() ? props.activeNote : null) ||
    props.notes?.find((n) => (n.content_md || '').trim()) ||
    null
  if (!sourceNote) return
  const cleaned = stripMarkdownAndSpoilers(sourceNote.content_md || '')
  if (!cleaned) {
    store.notify('手记中没有可摘录的非剧透正文', 'info')
    return
  }
  commentText.value = cleaned.slice(0, 200)
  syncComment.value = true
}

function stepRate(delta: number) {
  syncRating.value = true
  integerRate.value = Math.min(10, Math.max(1, integerRate.value + delta))
}

async function submitSync() {
  if (submitting.value) return
  submitting.value = true
  try {
    const cleanComment = commentText.value.trim().slice(0, 200)
    const shouldSendComment = syncComment.value && Boolean(cleanComment)
    const res = await gamesApi.syncBangumi(props.game.id, {
      sync_rating: syncRating.value,
      rate: syncRating.value ? integerRate.value : null,
      sync_comment: shouldSendComment,
      comment: shouldSendComment ? cleanComment : null,
      private: isPrivate.value,
    })
    const parts = [res.bangumi_type_label]
    if (res.synced_rate != null) parts.push(`${res.synced_rate} 分`)
    if (res.synced_comment) parts.push('含吐槽')
    store.notify(`已同步至 Bangumi · ${parts.join(' · ')}`, 'success')
    emit('synced', res)
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.code === 'MISSING_BANGUMI_TOKEN') {
        store.notify('尚未配置 Bangumi Access Token', 'warning', 5000, {
          label: '前往设置',
          onClick: () => store.openSettings('sources', 'bangumi'),
        })
        emit('close')
        return
      }
      if (err.code === 'MISSING_BANGUMI_ID') {
        emit('need-bind')
        return
      }
    }
    store.notify(err instanceof Error ? err.message : '同步至 Bangumi 失败', 'error')
  } finally {
    submitting.value = false
  }
}

function handleKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Escape' && !submitting.value) {
    ev.preventDefault()
    ev.stopPropagation()
    emit('close')
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown, true)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown, true)
})
</script>

<template>
  <div class="modal-backdrop bgm-sync-backdrop" @click.self="!submitting && emit('close')">
    <div class="modal-card bgm-sync-card">
      <div class="sync-head">
        <div>
          <h2>同步至 Bangumi</h2>
          <p class="sync-sub">
            <span>{{ game.title }}</span>
            <span v-if="resolvedBangumiId" class="bgm-id-tag tabular-nums">
              subject/{{ resolvedBangumiId }}
            </span>
          </p>
        </div>
        <button
          type="button"
          class="close-icon-btn"
          aria-label="关闭"
          :disabled="submitting"
          @click="emit('close')"
        >
          <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" />
          </svg>
        </button>
      </div>

      <div class="sync-body">
        <!-- 1. 收藏状态 + 换绑 -->
        <div class="sync-status-row">
          <div class="status-info">
            <span class="field-label">收藏状态</span>
            <span class="status-pill">{{ bangumiStatusLabel }}</span>
          </div>
          <button type="button" class="rebind-link" @click="emit('need-bind')">
            更换绑定条目
          </button>
        </div>

        <!-- 2. 整数评分 -->
        <div class="sync-block">
          <div class="block-head">
            <label class="check-row">
              <input v-model="syncRating" type="checkbox" class="native-switch" />
              <span>同步评分</span>
            </label>
            <span v-if="isHalfStepRounded" class="round-hint tabular-nums">
              本地 {{ localOverall!.toFixed(1) }} → Bangumi 整数 {{ integerRate }}
            </span>
          </div>

          <div class="rate-picker-row" :class="{ disabled: !syncRating }">
            <button
              type="button"
              class="step-btn"
              :disabled="!syncRating || integerRate <= 1"
              @click="stepRate(-1)"
            >
              −
            </button>
            <div class="rate-display tabular-nums">
              <span class="rate-star">★</span>
              <span class="rate-num">{{ syncRating ? integerRate : '—' }}</span>
              <span class="rate-max">/ 10</span>
            </div>
            <button
              type="button"
              class="step-btn"
              :disabled="!syncRating || integerRate >= 10"
              @click="stepRate(1)"
            >
              +
            </button>
            <button
              v-if="syncRating"
              type="button"
              class="subtle-clear-btn"
              @click="syncRating = false"
            >
              不同步评分
            </button>
          </div>
        </div>

        <!-- 3. 吐槽评论（≤ 200 字） -->
        <div class="sync-block">
          <div class="block-head">
            <label class="check-row">
              <input v-model="syncComment" type="checkbox" class="native-switch" />
              <span>同步吐槽评论</span>
            </label>
            <div class="comment-tools">
              <button
                v-if="hasExcerptSource"
                type="button"
                class="excerpt-btn"
                @click="fillExcerptFromNote"
              >
                从手记摘录
              </button>
              <span class="char-counter tabular-nums">{{ commentText.length }} / 200</span>
            </div>
          </div>

          <textarea
            v-model="commentText"
            class="textarea comment-textarea"
            rows="3"
            maxlength="200"
            :disabled="!syncComment"
            placeholder="填写将同步到 Bangumi 的短评（留空不覆盖 Bangumi 已有评论）"
            @input="syncComment = Boolean(commentText.trim())"
          />
          <p class="field-hint">仅同步填写的评分与吐槽，留空不会覆盖你在 Bangumi 的已有内容。</p>
        </div>

        <!-- 4. 仅自己可见 -->
        <label class="private-row">
          <div>
            <div class="private-title">仅自己可见</div>
            <div class="private-desc">勾选后不会在 Bangumi 公开时间线展示此条动态</div>
          </div>
          <input v-model="isPrivate" type="checkbox" class="native-switch" />
        </label>
      </div>

      <div class="sync-foot">
        <button type="button" class="btn btn-sm btn-ghost" :disabled="submitting" @click="emit('close')">
          取消
        </button>
        <button type="button" class="btn btn-sm btn-primary" :disabled="submitting" @click="submitSync">
          {{ submitting ? '同步中…' : '确认同步' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bgm-sync-backdrop {
  position: fixed;
  inset: 0;
  z-index: 96;
  background: rgba(4, 4, 6, 0.78);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.bgm-sync-card {
  width: 500px;
  max-width: calc(100vw - 32px);
  display: flex;
  flex-direction: column;
}

.sync-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 18px 22px 12px;
  border-bottom: 1px solid var(--divider-subtle);
}

.sync-head h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.sync-sub {
  margin: 4px 0 0;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

.bgm-id-tag {
  padding: 1px 6px;
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 10.5px;
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
  cursor: pointer;
}

.close-icon-btn:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.sync-body {
  padding: 16px 22px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.sync-status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.status-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.field-label {
  font-size: 12.5px;
  color: var(--text-secondary);
}

.status-pill {
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 500;
}

.rebind-link {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--text-muted);
  font-size: 11.5px;
  cursor: pointer;
}

.rebind-link:hover {
  color: var(--text-primary);
}

.sync-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--divider-subtle);
  background: rgba(255, 255, 255, 0.02);
}

.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.check-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  cursor: pointer;
}

.round-hint {
  font-size: 11px;
  color: var(--text-muted);
}

.rate-picker-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 2px;
}

.rate-picker-row.disabled {
  opacity: 0.45;
}

.step-btn {
  width: 28px;
  height: 26px;
  padding: 0;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-primary);
  font-size: 14px;
  cursor: pointer;
}

.step-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.14);
}

.step-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.rate-display {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  min-width: 72px;
  justify-content: center;
}

.rate-star {
  color: var(--amber-text);
  font-size: 15px;
}

.rate-num {
  font-family: var(--font-serif);
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
}

.rate-max {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}

.subtle-clear-btn {
  margin-left: auto;
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 11.5px;
  cursor: pointer;
}

.subtle-clear-btn:hover {
  color: var(--text-primary);
}

.comment-tools {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.excerpt-btn {
  padding: 2px 8px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
}

.excerpt-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-primary);
}

.char-counter {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}

.comment-textarea {
  font-size: 12.5px;
  line-height: 1.6;
  resize: vertical;
}

.field-hint {
  margin: 0;
  font-size: 11px;
  color: var(--text-muted);
}

.private-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid var(--divider-subtle);
  background: rgba(255, 255, 255, 0.02);
  cursor: pointer;
}

.private-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.private-desc {
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-muted);
}

.sync-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 22px 16px;
  border-top: 1px solid var(--divider-subtle);
}
</style>
