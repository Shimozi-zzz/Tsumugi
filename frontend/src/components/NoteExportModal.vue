<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { assetUrl, gamesApi } from '@/api/client'
import { useLibraryStore } from '@/stores/library'
import type { Game, GameNote } from '@/types'
import { saveBlobWithDialog } from '@/utils/fileExport'
import { renderNoteShareCard } from '@/utils/noteCardRenderer'
import { buildPlainTextExport } from '@/utils/noteDocExport'

const props = defineProps<{
  game: Game
  notes: GameNote[]
  activeNote: GameNote | null
}>()

const emit = defineEmits<{
  close: []
}>()

type ExportFormat = 'png' | 'md' | 'txt'
type ExportScope = 'single' | 'all'

const store = useLibraryStore()

const format = ref<ExportFormat>('png')
const scope = ref<ExportScope>(props.activeNote ? 'single' : 'all')
const maskSpoilers = ref(true)
const showRatings = ref(true)
const showWatermark = ref(true)
const blurCover = ref(Boolean(props.game.is_nsfw && store.privacyBlurMode))

const canvasRef = ref<HTMLCanvasElement | null>(null)
const rendering = ref(false)
const exporting = ref(false)
const canvasSize = ref<{ width: number; height: number } | null>(null)
const markdownPreview = ref('')
const loadingMd = ref(false)
let renderSeq = 0

const selectedNotes = computed<GameNote[]>(() => {
  if (scope.value === 'single' && props.activeNote) {
    return [props.activeNote]
  }
  return props.notes
})

const canChooseScope = computed(() => Boolean(props.activeNote) && props.notes.length > 1)

const hasRatingData = computed(() => {
  const g = props.game
  const dims = g.rating_dimensions || {}
  return (
    g.rating_overall != null ||
    Object.values(dims).some((v) => v != null) ||
    Boolean((g.short_review || '').trim())
  )
})

const resolvedCoverSrc = computed(() => {
  const rel = props.game.media?.cover_path || props.game.media?.cover_thumb_path || ''
  return rel ? assetUrl(rel, store.assetVersion) : ''
})

const plainTextPreview = computed(() =>
  buildPlainTextExport(props.game, selectedNotes.value, { maskSpoilers: maskSpoilers.value }),
)

const defaultFileBase = computed(() => {
  if (scope.value === 'single' && props.activeNote) {
    return `${props.game.title}-${props.activeNote.title || '手记'}`
  }
  return `${props.game.title}-手记`
})

async function refreshPreview() {
  if (format.value === 'png') {
    await nextTick()
    const canvas = canvasRef.value
    if (!canvas) return
    const seq = ++renderSeq
    rendering.value = true
    try {
      const dims = await renderNoteShareCard(canvas, {
        game: props.game,
        notes: selectedNotes.value,
        coverSrc: resolvedCoverSrc.value,
        playSeconds: props.game.play_record?.total_seconds || 0,
        maskSpoilers: maskSpoilers.value,
        blurCover: blurCover.value,
        showRatings: showRatings.value,
        showWatermark: showWatermark.value,
      })
      if (seq === renderSeq) {
        canvasSize.value = dims
      }
    } catch (err) {
      if (seq === renderSeq) {
        store.notify(err instanceof Error ? err.message : '生成分享长图预览失败', 'error')
      }
    } finally {
      if (seq === renderSeq) {
        rendering.value = false
      }
    }
    return
  }

  if (format.value === 'md') {
    const seq = ++renderSeq
    loadingMd.value = true
    try {
      const noteId =
        scope.value === 'single' && props.activeNote ? props.activeNote.id : undefined
      const txt = await gamesApi.fetchNotesMarkdown(props.game.id, noteId)
      if (seq === renderSeq) {
        markdownPreview.value = txt
      }
    } catch (err) {
      if (seq === renderSeq) {
        markdownPreview.value = ''
        store.notify(err instanceof Error ? err.message : '读取 Markdown 内容失败', 'error')
      }
    } finally {
      if (seq === renderSeq) {
        loadingMd.value = false
      }
    }
  }
}

async function handleExport() {
  if (exporting.value) return
  exporting.value = true
  try {
    if (format.value === 'png') {
      const canvas = canvasRef.value
      if (!canvas) return
      if (rendering.value) {
        await refreshPreview()
      }
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob((b) => resolve(b), 'image/png'),
      )
      if (!blob) {
        store.notify('生成 PNG 图片失败，请重试', 'error')
        return
      }
      const res = await saveBlobWithDialog(blob, defaultFileBase.value, {
        description: 'PNG 图片',
        mimeType: 'image/png',
        ext: '.png',
        pywebviewFileTypes: ['PNG Image (*.png)', 'All files (*.*)'],
      })
      if (!res.cancelled) {
        store.notify(res.path ? `已保存至 ${res.path}` : `已导出 ${res.filename}`, 'success')
        emit('close')
      }
      return
    }

    if (format.value === 'md') {
      const noteId =
        scope.value === 'single' && props.activeNote ? props.activeNote.id : undefined
      const mdText = markdownPreview.value || (await gamesApi.fetchNotesMarkdown(props.game.id, noteId))
      const blob = new Blob([mdText], { type: 'text/markdown;charset=utf-8' })
      const res = await saveBlobWithDialog(blob, defaultFileBase.value, {
        description: 'Markdown 文档',
        mimeType: 'text/markdown',
        ext: '.md',
        pywebviewFileTypes: ['Markdown (*.md)', 'All files (*.*)'],
      })
      if (!res.cancelled) {
        store.notify(res.path ? `已保存至 ${res.path}` : `已导出 ${res.filename}`, 'success')
        emit('close')
      }
      return
    }

    const blob = new Blob([plainTextPreview.value], { type: 'text/plain;charset=utf-8' })
    const res = await saveBlobWithDialog(blob, defaultFileBase.value, {
      description: '纯文本文档',
      mimeType: 'text/plain',
      ext: '.txt',
      pywebviewFileTypes: ['Plain Text (*.txt)', 'All files (*.*)'],
    })
    if (!res.cancelled) {
      store.notify(res.path ? `已保存至 ${res.path}` : `已导出 ${res.filename}`, 'success')
      emit('close')
    }
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '导出失败', 'error')
  } finally {
    exporting.value = false
  }
}

function handleKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Escape' && !exporting.value) {
    ev.preventDefault()
    ev.stopPropagation()
    emit('close')
  }
}

watch(
  [format, scope, maskSpoilers, showRatings, showWatermark, blurCover],
  () => {
    void refreshPreview()
  },
  { immediate: true },
)

onMounted(() => {
  window.addEventListener('keydown', handleKeydown, true)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown, true)
})
</script>

<template>
  <div class="modal-backdrop export-backdrop" @click.self="!exporting && emit('close')">
    <div class="modal-card export-card">
      <div class="export-head">
        <div>
          <h2>导出手记</h2>
          <p class="export-sub">{{ game.title }}</p>
        </div>
        <button
          type="button"
          class="close-icon-btn"
          aria-label="关闭"
          :disabled="exporting"
          @click="emit('close')"
        >
          <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" />
          </svg>
        </button>
      </div>

      <!-- 参数控制栏 -->
      <div class="export-controls">
        <div class="ctrl-row">
          <div class="ctrl-group">
            <span class="ctrl-label">格式</span>
            <div class="seg-pills" role="tablist" aria-label="导出格式">
              <button
                type="button"
                class="seg-pill"
                :class="{ active: format === 'png' }"
                @click="format = 'png'"
              >
                分享长图 (.png)
              </button>
              <button
                type="button"
                class="seg-pill"
                :class="{ active: format === 'md' }"
                @click="format = 'md'"
              >
                Markdown (.md)
              </button>
              <button
                type="button"
                class="seg-pill"
                :class="{ active: format === 'txt' }"
                @click="format = 'txt'"
              >
                纯文本 (.txt)
              </button>
            </div>
          </div>

          <div v-if="canChooseScope" class="ctrl-group">
            <span class="ctrl-label">范围</span>
            <div class="seg-pills" role="tablist" aria-label="导出范围">
              <button
                type="button"
                class="seg-pill"
                :class="{ active: scope === 'single' }"
                @click="scope = 'single'"
              >
                当前手记
              </button>
              <button
                type="button"
                class="seg-pill"
                :class="{ active: scope === 'all' }"
                @click="scope = 'all'"
              >
                全部手记 ({{ notes.length }})
              </button>
            </div>
          </div>
        </div>

        <div class="ctrl-checks">
          <label v-if="format !== 'md'" class="check-opt">
            <input v-model="maskSpoilers" type="checkbox" class="native-switch" />
            <span>遮蔽防剧透</span>
          </label>
          <label v-if="format === 'png' && hasRatingData" class="check-opt">
            <input v-model="showRatings" type="checkbox" class="native-switch" />
            <span>显示评分</span>
          </label>
          <label v-if="format === 'png'" class="check-opt">
            <input v-model="showWatermark" type="checkbox" class="native-switch" />
            <span>底部署名</span>
          </label>
          <label v-if="format === 'png' && game.is_nsfw" class="check-opt">
            <input v-model="blurCover" type="checkbox" class="native-switch" />
            <span>模糊封面</span>
          </label>
          <span v-if="format === 'png' && canvasSize" class="dim-badge tabular-nums">
            {{ canvasSize.width }}×{{ canvasSize.height }} px
          </span>
        </div>
      </div>

      <!-- 实时预览区 -->
      <div class="export-preview-stage">
        <div v-if="format === 'png'" class="png-stage">
          <canvas ref="canvasRef" class="preview-canvas" />
          <div v-if="rendering" class="stage-overlay">渲染长图中…</div>
        </div>

        <div v-else-if="format === 'md'" class="doc-stage">
          <div v-if="loadingMd" class="doc-loading">生成 Markdown 文档中…</div>
          <pre v-else class="doc-pre">{{ markdownPreview }}</pre>
        </div>

        <div v-else class="doc-stage">
          <pre class="doc-pre">{{ plainTextPreview }}</pre>
        </div>
      </div>

      <div class="export-foot">
        <span class="foot-hint">支持手动选择保存目录与文件名</span>
        <div class="foot-actions">
          <button type="button" class="btn btn-sm btn-ghost" :disabled="exporting" @click="emit('close')">
            取消
          </button>
          <button
            type="button"
            class="btn btn-sm btn-primary"
            :disabled="exporting || rendering || loadingMd"
            @click="handleExport"
          >
            {{ exporting ? '正在保存…' : '选择位置并导出' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.export-backdrop {
  position: fixed;
  inset: 0;
  z-index: 95;
  background: rgba(4, 4, 6, 0.78);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.export-card {
  width: 820px;
  max-width: calc(100vw - 32px);
  height: min(86vh, 780px);
  display: flex;
  flex-direction: column;
}

.export-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 18px 22px 12px;
}

.export-head h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.export-sub {
  margin: 3px 0 0;
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
  cursor: pointer;
}

.close-icon-btn:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.export-controls {
  padding: 0 22px 14px;
  border-bottom: 1px solid var(--divider-subtle);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ctrl-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.ctrl-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.ctrl-label {
  font-size: 11.5px;
  color: var(--text-muted);
}

.seg-pills {
  display: inline-flex;
  padding: 2px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.05);
  gap: 2px;
}

.seg-pill {
  padding: 4px 11px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: background-color 140ms ease, color 140ms ease;
}

.seg-pill:hover {
  color: var(--text-primary);
}

.seg-pill.active {
  background: #f5f5f7;
  color: #0a0a0c;
  font-weight: 600;
}

.ctrl-checks {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.check-opt {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
}

.dim-badge {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
}

.export-preview-stage {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 22px;
  background: rgba(0, 0, 0, 0.28);
}

.png-stage {
  position: relative;
  display: flex;
  justify-content: center;
  align-items: flex-start;
}

.preview-canvas {
  width: 100%;
  max-width: 720px;
  height: auto;
  border-radius: 10px;
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.55);
}

.stage-overlay {
  position: absolute;
  top: 16px;
  right: 16px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(10, 10, 12, 0.8);
  color: var(--text-secondary);
  font-size: 11.5px;
}

.doc-stage {
  border-radius: 10px;
  border: 1px solid var(--divider-subtle);
  background: rgba(255, 255, 255, 0.025);
  padding: 16px 18px;
  min-height: 280px;
}

.doc-loading {
  font-size: 12.5px;
  color: var(--text-muted);
}

.doc-pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.7;
  color: rgba(244, 244, 245, 0.88);
}

.export-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 22px 16px;
  border-top: 1px solid var(--divider-subtle);
}

.foot-hint {
  font-size: 11.5px;
  color: var(--text-muted);
}

.foot-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
