<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { gamesApi } from '@/api/client'
import { useLibraryStore } from '@/stores/library'
import type { Game, GameNote, NoteType, RatingDimensionKey } from '@/types'
import { renderNoteMarkdown, toggleSpoilerFromEvent } from '@/utils/markdown'

const props = defineProps<{
  game: Game
}>()

const store = useLibraryStore()

const DIMENSIONS: Array<{ key: RatingDimensionKey; label: string }> = [
  { key: 'story', label: '剧本' },
  { key: 'visual', label: '美术与演出' },
  { key: 'music', label: '音乐' },
  { key: 'atmosphere', label: '氛围与体验' },
]

const NOTE_TYPE_OPTIONS: Array<{ key: NoteType; label: string; short: string; placeholder: string }> = [
  { key: 'work', label: '作品总评', short: '总评', placeholder: '输入总评标题，例如：通关总评、二周目感想' },
  { key: 'character', label: '角色手记', short: '角色', placeholder: '输入角色姓名，例如：鸣濑白羽' },
  { key: 'misc', label: '随记', short: '随记', placeholder: '输入随记标题，例如：伏笔梳理、台词摘录' },
]

const NOTE_TEMPLATES: Record<
  NoteType,
  { defaultTitle: string; subtitle: string; outline: string }
> = {
  work: {
    defaultTitle: '作品总评',
    subtitle: '梳理整体观感、剧情结构与视听演出',
    outline: '## 整体感受\n\n\n## 剧情与演出\n\n\n## 角色印象\n\n',
  },
  character: {
    defaultTitle: '角色手记',
    subtitle: '记录角色初印象、弧光变化与名场面',
    outline: '## 初印象\n\n\n## 人物弧光\n\n\n## 难忘场景\n\n',
  },
  misc: {
    defaultTitle: '游玩随记',
    subtitle: '随手记下伏笔、台词摘录或通关感想',
    outline: '## 记录\n\n',
  },
}

const OUTLINE_SET = new Set(Object.values(NOTE_TEMPLATES).map((t) => t.outline.trim()))

// ──────────────────── 多维评分状态 ────────────────────

const dimScores = ref<Record<RatingDimensionKey, number | null>>({
  story: null,
  visual: null,
  music: null,
  atmosphere: null,
})
const overallScore = ref<number | null>(null)
const overallManualOverride = ref(false)
const shortReview = ref('')
const ratingSaveState = ref<'idle' | 'saving' | 'saved'>('idle')
let ratingSaveTimer: number | null = null

const computedDimAverage = computed<number | null>(() => {
  const vals = DIMENSIONS.map((d) => dimScores.value[d.key]).filter(
    (v): v is number => v != null && !Number.isNaN(v),
  )
  if (vals.length === 0) return null
  const avg = vals.reduce((acc, n) => acc + n, 0) / vals.length
  return Math.round(avg * 10) / 10
})

const hasAnyRating = computed(
  () => overallScore.value != null || computedDimAverage.value != null || Boolean(shortReview.value.trim()),
)

function syncRatingFromProps(g: Game) {
  if (ratingSaveTimer !== null) {
    clearTimeout(ratingSaveTimer)
    ratingSaveTimer = null
  }
  const dims = g.rating_dimensions || {}
  dimScores.value = {
    story: dims.story != null ? Number(dims.story) : null,
    visual: dims.visual != null ? Number(dims.visual) : null,
    music: dims.music != null ? Number(dims.music) : null,
    atmosphere: dims.atmosphere != null ? Number(dims.atmosphere) : null,
  }
  overallScore.value = g.rating_overall != null ? Number(g.rating_overall) : null
  shortReview.value = g.short_review || ''
  const autoAvg = computedDimAverage.value
  overallManualOverride.value =
    overallScore.value != null && autoAvg != null && Math.abs(overallScore.value - autoAvg) >= 0.05
  ratingSaveState.value = 'idle'
}

function formatScore(val: number | null): string {
  if (val == null || Number.isNaN(val)) return '—'
  return Number(val).toFixed(1)
}

function clampScore(raw: number, step = 0.5): number {
  const clamped = Math.min(10, Math.max(1, raw))
  return Math.round(clamped / step) * step
}

function setDimensionScore(key: RatingDimensionKey, val: number | null) {
  dimScores.value = {
    ...dimScores.value,
    [key]: val != null ? clampScore(val, 0.5) : null,
  }
  if (!overallManualOverride.value) {
    overallScore.value = computedDimAverage.value
  }
  scheduleRatingSave()
}

function onDimRangeInput(key: RatingDimensionKey, ev: Event) {
  const num = Number((ev.target as HTMLInputElement).value)
  if (!Number.isNaN(num)) {
    setDimensionScore(key, num)
  }
}

function stepOverall(delta: number) {
  const base = overallScore.value ?? computedDimAverage.value ?? 8.0
  const next = clampScore(base + delta, 0.5)
  overallScore.value = next
  overallManualOverride.value =
    computedDimAverage.value != null ? Math.abs(next - computedDimAverage.value) >= 0.05 : true
  scheduleRatingSave()
}

function resetOverallToAverage() {
  overallManualOverride.value = false
  overallScore.value = computedDimAverage.value
  scheduleRatingSave()
}

function scheduleRatingSave(delayMs = 420) {
  if (ratingSaveTimer !== null) clearTimeout(ratingSaveTimer)
  ratingSaveState.value = 'saving'
  const targetGameId = props.game.id
  ratingSaveTimer = window.setTimeout(() => {
    ratingSaveTimer = null
    void persistRating(targetGameId)
  }, delayMs)
}

async function persistRating(targetGameId = props.game.id, clearAll = false) {
  if (ratingSaveTimer !== null) {
    clearTimeout(ratingSaveTimer)
    ratingSaveTimer = null
  }
  ratingSaveState.value = 'saving'
  try {
    const payload = clearAll
      ? { clear: true, short_review: '' }
      : {
          rating_overall: overallManualOverride.value ? overallScore.value : null,
          rating_dimensions: {
            story: dimScores.value.story,
            visual: dimScores.value.visual,
            music: dimScores.value.music,
            atmosphere: dimScores.value.atmosphere,
          },
          short_review: shortReview.value.trim(),
        }
    const updated = await gamesApi.updateRating(targetGameId, payload)
    store.syncGameFromServer(updated, { bumpAsset: false })
    if (props.game.id === targetGameId) {
      overallScore.value = updated.rating_overall != null ? Number(updated.rating_overall) : null
      ratingSaveState.value = 'saved'
    }
    void store.fetchCollections().catch(() => {})
  } catch (err) {
    ratingSaveState.value = 'idle'
    store.notify(err instanceof Error ? err.message : '保存评分失败', 'error')
  }
}

async function clearRating() {
  dimScores.value = { story: null, visual: null, music: null, atmosphere: null }
  overallScore.value = null
  overallManualOverride.value = false
  shortReview.value = ''
  await persistRating(props.game.id, true)
  store.notify('已清空该作品评分', 'info')
}

// ──────────────────── 双栏长评手记工作台状态 ────────────────────

type TypeFilterKey = 'all' | NoteType
type EditorViewMode = 'edit' | 'split' | 'preview'

const notes = ref<GameNote[]>([])
const loadingNotes = ref(false)
const activeNoteId = ref<number | null>(null)
const activeTypeFilter = ref<TypeFilterKey>('all')
const editorMode = ref<EditorViewMode>('edit')
const noteSaveState = ref<'idle' | 'dirty' | 'saving' | 'saved'>('idle')
const confirmDeleteNoteId = ref<number | null>(null)
const exportingMd = ref(false)

// 右栏统一创作状态
const draftNewMode = ref(false)
const creatingBusy = ref(false)

// 当前编辑草稿
const draftTitle = ref('')
const draftType = ref<NoteType>('work')
const draftContent = ref('')
const noteTitleInputRef = ref<HTMLInputElement | null>(null)
const editorTextareaRef = ref<HTMLTextAreaElement | null>(null)
let noteSaveTimer: number | null = null
let notesLoadSeq = 0

const activeNote = computed<GameNote | null>(() => {
  if (draftNewMode.value || activeNoteId.value === null) return null
  return notes.value.find((n) => n.id === activeNoteId.value) || null
})

const typeCounts = computed(() => {
  let work = 0
  let character = 0
  let misc = 0
  for (const n of notes.value) {
    if (n.note_type === 'character') character++
    else if (n.note_type === 'misc') misc++
    else work++
  }
  return {
    all: notes.value.length,
    work,
    character,
    misc,
  }
})

const filterTabs = computed<Array<{ key: TypeFilterKey; label: string; count: number }>>(() => [
  { key: 'all', label: '全部', count: typeCounts.value.all },
  { key: 'work', label: '总评', count: typeCounts.value.work },
  { key: 'character', label: '角色', count: typeCounts.value.character },
  { key: 'misc', label: '随记', count: typeCounts.value.misc },
])

const filteredNotes = computed<GameNote[]>(() => {
  if (activeTypeFilter.value === 'all') return notes.value
  return notes.value.filter((n) => n.note_type === activeTypeFilter.value)
})

const totalWordsCount = computed(() =>
  notes.value.reduce((acc, n) => acc + countTextChars(n.content_md || ''), 0),
)

const currentCharCount = computed(() => countTextChars(draftContent.value))
const currentReadMinutes = computed(() =>
  currentCharCount.value > 0 ? Math.max(1, Math.ceil(currentCharCount.value / 400)) : 0,
)

const renderedPreviewHtml = computed(() => renderNoteMarkdown(draftContent.value))

const draftTitlePlaceholder = computed(
  () => NOTE_TYPE_OPTIONS.find((o) => o.key === draftType.value)?.placeholder || '输入手记标题…',
)

const starterCards = computed(() =>
  NOTE_TYPE_OPTIONS.map((opt) => ({
    ...opt,
    subtitle: NOTE_TEMPLATES[opt.key].subtitle,
  })),
)

function countTextChars(text: string): number {
  return (text || '').replace(/\s+/g, '').length
}

function noteTypeShortLabel(type: string): string {
  return NOTE_TYPE_OPTIONS.find((o) => o.key === type)?.short || '手记'
}

function formatNoteDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  if (d.getFullYear() === now.getFullYear()) {
    return `${month}-${day}`
  }
  return `${d.getFullYear()}-${month}-${day}`
}

function formatNoteDateTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${y}-${m}-${day} ${hh}:${mm}`
}

function extractNoteExcerpt(md: string): string {
  if (!md || !md.trim()) return ''
  const plain = md
    .replace(/<details[\s\S]*?<\/details>/gi, ' [折叠内容] ')
    .replace(/>![\s\S]*?!</g, ' [剧透] ')
    .replace(/```[\s\S]*?```/g, ' [代码] ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^\s*[-*+>\d.]+\s+/gm, '')
    .replace(/[*_~]+/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  return plain
}

function bindDraftToNote(note: GameNote | null) {
  if (!note) {
    draftTitle.value = ''
    draftType.value = 'work'
    draftContent.value = ''
    noteSaveState.value = 'idle'
    confirmDeleteNoteId.value = null
    return
  }
  draftTitle.value = note.title
  draftType.value =
    note.note_type === 'character' || note.note_type === 'misc' ? note.note_type : 'work'
  draftContent.value = note.content_md || ''
  noteSaveState.value = 'idle'
  confirmDeleteNoteId.value = null
}

async function loadNotes(gameId: number) {
  const seq = ++notesLoadSeq
  loadingNotes.value = true
  draftNewMode.value = false
  activeTypeFilter.value = 'all'
  confirmDeleteNoteId.value = null
  try {
    const list = await gamesApi.listNotes(gameId)
    if (seq !== notesLoadSeq || props.game.id !== gameId) return
    notes.value = list
    store.setGameNotesCount(gameId, list.length)
    if (list.length > 0) {
      const keep = list.find((n) => n.id === activeNoteId.value) || list[0]
      activeNoteId.value = keep.id
      bindDraftToNote(keep)
      editorMode.value = keep.content_md.trim() ? 'preview' : 'edit'
    } else {
      activeNoteId.value = null
      bindDraftToNote(null)
    }
  } catch {
    if (seq !== notesLoadSeq) return
    notes.value = []
    activeNoteId.value = null
    bindDraftToNote(null)
  } finally {
    if (seq === notesLoadSeq) {
      loadingNotes.value = false
    }
  }
}

async function flushNoteSave() {
  if (noteSaveTimer !== null) {
    clearTimeout(noteSaveTimer)
    noteSaveTimer = null
  }
  const current = activeNote.value
  if (!current || draftNewMode.value) return
  const cleanTitle = draftTitle.value.trim() || current.title
  const changed =
    cleanTitle !== current.title ||
    draftType.value !== current.note_type ||
    draftContent.value !== current.content_md
  if (!changed) {
    if (noteSaveState.value === 'dirty') noteSaveState.value = 'saved'
    return
  }

  const targetGameId = current.game_id
  const targetNoteId = current.id
  noteSaveState.value = 'saving'
  try {
    const updated = await gamesApi.updateNote(targetGameId, targetNoteId, {
      title: cleanTitle,
      note_type: draftType.value,
      content_md: draftContent.value,
    })
    const idx = notes.value.findIndex((n) => n.id === targetNoteId)
    if (idx >= 0) {
      notes.value[idx] = updated
    }
    if (activeNoteId.value === targetNoteId) {
      noteSaveState.value = 'saved'
    }
  } catch (err) {
    noteSaveState.value = 'dirty'
    store.notify(err instanceof Error ? err.message : '保存手记失败', 'error')
  }
}

function scheduleNoteSave() {
  if (draftNewMode.value || !activeNote.value) return
  noteSaveState.value = 'dirty'
  if (noteSaveTimer !== null) clearTimeout(noteSaveTimer)
  noteSaveTimer = window.setTimeout(() => {
    noteSaveTimer = null
    void flushNoteSave()
  }, 800)
}

function onNoteContentInput() {
  if (!draftNewMode.value) {
    scheduleNoteSave()
  }
}

function onNoteContentBlur() {
  if (!draftNewMode.value) {
    void flushNoteSave()
  }
}

async function selectNote(note: GameNote) {
  if (!draftNewMode.value && activeNoteId.value === note.id) return
  await flushNoteSave()
  draftNewMode.value = false
  activeNoteId.value = note.id
  bindDraftToNote(note)
  editorMode.value = note.content_md.trim() ? 'preview' : 'edit'
}

async function openNewDraft(preferredType?: NoteType) {
  await flushNoteSave()
  const resolvedType: NoteType =
    preferredType || (activeTypeFilter.value !== 'all' ? activeTypeFilter.value : 'work')
  draftType.value = resolvedType
  draftTitle.value = ''
  draftContent.value = NOTE_TEMPLATES[resolvedType].outline
  confirmDeleteNoteId.value = null
  noteSaveState.value = 'idle'
  draftNewMode.value = true
  if (editorMode.value === 'preview') {
    editorMode.value = 'edit'
  }
  await nextTick()
  noteTitleInputRef.value?.focus()
}

function selectDraftNewType(nextType: NoteType) {
  const prevTrimmed = draftContent.value.trim()
  draftType.value = nextType
  if (!prevTrimmed || OUTLINE_SET.has(prevTrimmed)) {
    draftContent.value = NOTE_TEMPLATES[nextType].outline
  }
}

function clearNewDraftOutline() {
  draftContent.value = ''
  void nextTick(() => editorTextareaRef.value?.focus())
}

function cancelNewDraft() {
  if (creatingBusy.value) return
  draftNewMode.value = false
  const fallback =
    (activeNoteId.value !== null ? notes.value.find((n) => n.id === activeNoteId.value) : null) ||
    notes.value[0] ||
    null
  activeNoteId.value = fallback?.id ?? null
  bindDraftToNote(fallback)
}

function focusEditorTextarea() {
  void nextTick(() => editorTextareaRef.value?.focus())
}

async function submitCreateNote() {
  if (!draftNewMode.value || creatingBusy.value) return
  creatingBusy.value = true
  try {
    const fallbackTitle = NOTE_TEMPLATES[draftType.value].defaultTitle
    const created = await gamesApi.createNote(props.game.id, {
      note_type: draftType.value,
      title: draftTitle.value.trim() || fallbackTitle,
      content_md: draftContent.value,
    })
    notes.value = [created, ...notes.value].sort(
      (a, b) => Number(b.is_pinned) - Number(a.is_pinned),
    )
    store.setGameNotesCount(props.game.id, notes.value.length)
    if (activeTypeFilter.value !== 'all' && activeTypeFilter.value !== created.note_type) {
      activeTypeFilter.value = 'all'
    }
    draftNewMode.value = false
    activeNoteId.value = created.id
    bindDraftToNote(created)
    noteSaveState.value = 'saved'
    store.notify('手记已保存', 'success', 1800)
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '新建手记失败', 'error')
  } finally {
    creatingBusy.value = false
  }
}

async function togglePinActiveNote() {
  const current = activeNote.value
  if (!current) return
  await flushNoteSave()
  try {
    const updated = await gamesApi.updateNote(current.game_id, current.id, {
      is_pinned: !current.is_pinned,
    })
    notes.value = notes.value
      .map((n) => (n.id === updated.id ? updated : n))
      .sort((a, b) => Number(b.is_pinned) - Number(a.is_pinned))
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '更新置顶状态失败', 'error')
  }
}

async function deleteActiveNote() {
  const current = activeNote.value
  if (!current) return
  if (confirmDeleteNoteId.value !== current.id) {
    confirmDeleteNoteId.value = current.id
    return
  }
  if (noteSaveTimer !== null) {
    clearTimeout(noteSaveTimer)
    noteSaveTimer = null
  }
  try {
    await gamesApi.deleteNote(current.game_id, current.id)
    notes.value = notes.value.filter((n) => n.id !== current.id)
    store.setGameNotesCount(props.game.id, notes.value.length)
    confirmDeleteNoteId.value = null
    const next = filteredNotes.value[0] || notes.value[0] || null
    activeNoteId.value = next?.id ?? null
    bindDraftToNote(next)
    store.notify('已删除该篇手记', 'info')
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '删除手记失败', 'error')
  }
}

function insertMarkdownSnippet(kind: 'h2' | 'bold' | 'quote' | 'list' | 'spoiler') {
  const el = editorTextareaRef.value
  const src = draftContent.value
  const start = el ? (el.selectionStart ?? src.length) : src.length
  const end = el ? (el.selectionEnd ?? start) : start
  const selected = src.slice(start, end)
  const atLineStart = start === 0 || src[start - 1] === '\n'
  const linePrefix = atLineStart ? '' : '\n'

  let inserted = ''
  let selOffsetStart = 0
  let selOffsetEnd = 0

  if (kind === 'h2') {
    const body = selected || '小节标题'
    inserted = `${linePrefix}## ${body}`
    selOffsetStart = linePrefix.length + 3
    selOffsetEnd = selOffsetStart + body.length
  } else if (kind === 'bold') {
    const body = selected || '重点文本'
    inserted = `**${body}**`
    selOffsetStart = 2
    selOffsetEnd = 2 + body.length
  } else if (kind === 'quote') {
    const body = selected || '台词或引用内容'
    inserted = `${linePrefix}> ${body}`
    selOffsetStart = linePrefix.length + 2
    selOffsetEnd = selOffsetStart + body.length
  } else if (kind === 'list') {
    const body = selected || '要点记录'
    inserted = `${linePrefix}- ${body}`
    selOffsetStart = linePrefix.length + 2
    selOffsetEnd = selOffsetStart + body.length
  } else {
    const body = selected || '剧透内容'
    inserted = `>!${body}!<`
    selOffsetStart = 2
    selOffsetEnd = 2 + body.length
  }

  draftContent.value = src.slice(0, start) + inserted + src.slice(end)
  onNoteContentInput()
  void nextTick(() => {
    if (!el) return
    el.focus()
    el.setSelectionRange(start + selOffsetStart, start + selOffsetEnd)
  })
}

async function handleExportMarkdown() {
  if (exportingMd.value) return
  exportingMd.value = true
  try {
    if (ratingSaveTimer !== null) {
      await persistRating(props.game.id)
    }
    await flushNoteSave()
    const dl = await gamesApi.downloadNotesMarkdown(props.game.id, undefined, `${props.game.title}-手记`)
    store.notify(`已导出 Markdown：${dl.filename}`, 'success')
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '导出 Markdown 失败', 'error')
  } finally {
    exportingMd.value = false
  }
}

function handleKeydown(ev: KeyboardEvent) {
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 's') {
    ev.preventDefault()
    if (ratingSaveTimer !== null) {
      void persistRating(props.game.id)
    }
    if (draftNewMode.value) {
      void submitCreateNote()
    } else if (activeNote.value) {
      void flushNoteSave().then(() => {
        if (noteSaveState.value === 'saved') {
          store.notify('手记已保存', 'success', 1800)
        }
      })
    }
  }
}

watch(
  () => props.game.id,
  async (nextId, prevId) => {
    if (prevId != null && prevId !== nextId) {
      if (ratingSaveTimer !== null) {
        void persistRating(prevId)
      }
      await flushNoteSave()
    }
    syncRatingFromProps(props.game)
    activeNoteId.value = null
    void loadNotes(nextId)
  },
  { immediate: true },
)

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  if (ratingSaveTimer !== null) {
    void persistRating(props.game.id)
  }
  void flushNoteSave()
})
</script>

<template>
  <div class="review-workspace">
    <!-- 上半区：紧凑多维评分卡片 -->
    <section class="rating-card">
      <div class="rating-card-top">
        <!-- 左侧：综合总分 -->
        <div class="rating-overall-col">
          <div class="overall-label-row">
            <span class="overall-caption">综合评分</span>
            <span v-if="overallScore != null" class="overall-mode-tag">
              {{ overallManualOverride ? '手动微调' : '自动均分' }}
            </span>
          </div>

          <div class="overall-score-display tabular-nums">
            <span class="overall-star" :class="{ lit: overallScore != null }">★</span>
            <span class="overall-num" :class="{ muted: overallScore == null }">
              {{ formatScore(overallScore) }}
            </span>
            <span class="overall-max">/ 10</span>
          </div>

          <div class="overall-actions">
            <button
              type="button"
              class="step-btn"
              title="降低 0.5 分"
              @click="stepOverall(-0.5)"
            >
              −
            </button>
            <button
              type="button"
              class="step-btn"
              title="提高 0.5 分"
              @click="stepOverall(0.5)"
            >
              +
            </button>
            <button
              v-if="overallManualOverride && computedDimAverage != null"
              type="button"
              class="subtle-inline-btn"
              @click="resetOverallToAverage"
            >
              恢复均分
            </button>
            <button
              v-if="hasAnyRating"
              type="button"
              class="subtle-inline-btn danger"
              @click="clearRating"
            >
              清空
            </button>
          </div>
        </div>

        <!-- 右侧：4 行简洁可点击/拖拽维度评分条 -->
        <div class="rating-dims-col">
          <div v-for="dim in DIMENSIONS" :key="dim.key" class="dim-row">
            <span class="dim-label">{{ dim.label }}</span>
            <div class="dim-bar-wrap">
              <div class="dim-track">
                <div
                  class="dim-fill"
                  :style="{
                    width: dimScores[dim.key] != null ? `${(dimScores[dim.key]! / 10) * 100}%` : '0%',
                  }"
                />
              </div>
              <input
                type="range"
                class="dim-range-input"
                min="1"
                max="10"
                step="0.5"
                :value="dimScores[dim.key] ?? 0"
                :aria-label="`${dim.label}评分`"
                @input="onDimRangeInput(dim.key, $event)"
              />
            </div>
            <span
              class="dim-val tabular-nums"
              :class="{ empty: dimScores[dim.key] == null }"
            >
              {{ formatScore(dimScores[dim.key]) }}
            </span>
            <button
              type="button"
              class="dim-clear-btn"
              :class="{ hidden: dimScores[dim.key] == null }"
              title="清除此项评分"
              @click="setDimensionScore(dim.key, null)"
            >
              ×
            </button>
          </div>
        </div>
      </div>

      <!-- 底部一行：一句话短评 -->
      <div class="short-review-row">
        <input
          v-model="shortReview"
          class="short-review-input"
          maxlength="240"
          placeholder="写下一句话短评或通关印象…"
          @input="scheduleRatingSave(600)"
          @blur="ratingSaveTimer !== null && persistRating(game.id)"
          @keydown.enter="persistRating(game.id)"
        />
        <span v-if="ratingSaveState !== 'idle'" class="save-hint">
          {{ ratingSaveState === 'saving' ? '保存中…' : '已保存' }}
        </span>
      </div>
    </section>

    <!-- 下半区：左目录 + 右编辑/阅读 双栏手记工作台 -->
    <section class="notes-card">
      <div class="notes-workspace-grid">
        <!-- 左栏：手记目录 -->
        <aside class="notes-sidebar">
          <div class="notes-sidebar-head">
            <div class="sidebar-title-wrap">
              <span class="sidebar-title">手记目录</span>
              <span class="sidebar-count tabular-nums">{{ notes.length }}</span>
            </div>
            <button
              type="button"
              class="btn btn-sm sidebar-new-btn"
              :class="{ 'btn-primary': draftNewMode }"
              @click="openNewDraft()"
            >
              + 新建
            </button>
          </div>

          <div class="sidebar-filters" role="tablist" aria-label="按类型筛选手记">
            <button
              v-for="tab in filterTabs"
              :key="tab.key"
              type="button"
              role="tab"
              class="sidebar-filter-btn"
              :class="{ active: activeTypeFilter === tab.key }"
              :aria-selected="activeTypeFilter === tab.key"
              @click="activeTypeFilter = tab.key"
            >
              <span>{{ tab.label }}</span>
              <span v-if="tab.count > 0" class="filter-count tabular-nums">{{ tab.count }}</span>
            </button>
          </div>

          <div v-if="loadingNotes" class="sidebar-empty">
            <span>加载手记中…</span>
          </div>

          <div v-else-if="filteredNotes.length > 0" class="note-list">
            <button
              v-for="note in filteredNotes"
              :key="note.id"
              type="button"
              class="note-list-item"
              :class="{ active: !draftNewMode && activeNoteId === note.id }"
              @click="selectNote(note)"
            >
              <div class="note-item-top">
                <div class="note-item-badges">
                  <span class="note-pill-type" :class="`type-${note.note_type}`">
                    {{ noteTypeShortLabel(note.note_type) }}
                  </span>
                  <span v-if="note.is_pinned" class="note-pin-badge">置顶</span>
                </div>
                <span class="note-item-date tabular-nums">{{ formatNoteDate(note.updated_at) }}</span>
              </div>
              <div class="note-item-title">{{ note.title }}</div>
              <div class="note-item-excerpt" :class="{ empty: !extractNoteExcerpt(note.content_md) }">
                {{ extractNoteExcerpt(note.content_md) || '暂无正文内容' }}
              </div>
            </button>
          </div>

          <div v-else class="sidebar-empty">
            <span v-if="notes.length === 0">尚无手记篇目</span>
            <span v-else>当前分类下暂无手记</span>
            <button
              type="button"
              class="sidebar-empty-action"
              @click="openNewDraft(activeTypeFilter === 'all' ? 'work' : activeTypeFilter)"
            >
              + 撰写一篇
            </button>
          </div>

          <div class="notes-sidebar-foot">
            <span class="sidebar-stats tabular-nums">
              {{ notes.length }} 篇 · {{ totalWordsCount }} 字
            </span>
            <button
              type="button"
              class="export-md-btn"
              :disabled="exportingMd || (notes.length === 0 && !hasAnyRating)"
              title="导出评分、短评与全部手记为 Markdown (.md)"
              @click="handleExportMarkdown"
            >
              <svg viewBox="0 0 18 18" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.65">
                <path d="M9 3v8.5M5.8 8.5 9 11.7l3.2-3.2M3.5 14.2h11" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
              <span>{{ exportingMd ? '导出中…' : '导出 .md' }}</span>
            </button>
          </div>
        </aside>

        <!-- 右栏：统一创作 / 编辑 / 阅读画布 -->
        <div class="notes-main">
          <!-- 状态 A：新建手记画布 -->
          <template v-if="draftNewMode">
            <div class="canvas-topbar">
              <div class="create-type-seg" role="radiogroup" aria-label="选择手记类型">
                <button
                  v-for="opt in NOTE_TYPE_OPTIONS"
                  :key="opt.key"
                  type="button"
                  class="create-type-opt"
                  :class="{ active: draftType === opt.key }"
                  @click="selectDraftNewType(opt.key)"
                >
                  {{ opt.label }}
                </button>
              </div>

              <div class="canvas-top-actions">
                <button
                  v-if="draftContent.trim()"
                  type="button"
                  class="tool-micro-btn"
                  @click="clearNewDraftOutline"
                >
                  清空大纲
                </button>
                <button
                  type="button"
                  class="btn btn-sm btn-ghost"
                  :disabled="creatingBusy"
                  @click="cancelNewDraft"
                >
                  取消
                </button>
                <button
                  type="button"
                  class="btn btn-sm btn-primary"
                  :disabled="creatingBusy"
                  @click="submitCreateNote"
                >
                  {{ creatingBusy ? '保存中…' : '保存手记' }}
                </button>
              </div>
            </div>

            <div class="canvas-title-wrap">
              <input
                ref="noteTitleInputRef"
                v-model="draftTitle"
                class="note-hero-title-input"
                maxlength="120"
                :placeholder="draftTitlePlaceholder"
                @keydown.enter.prevent="focusEditorTextarea"
                @keydown.esc="cancelNewDraft"
              />
            </div>

            <div class="canvas-subtoolbar">
              <div class="md-format-bar" :class="{ muted: editorMode === 'preview' }">
                <button
                  type="button"
                  class="md-tool-btn"
                  :disabled="editorMode === 'preview'"
                  title="插入二级标题"
                  @click="insertMarkdownSnippet('h2')"
                >
                  H2
                </button>
                <button
                  type="button"
                  class="md-tool-btn"
                  :disabled="editorMode === 'preview'"
                  title="加粗"
                  @click="insertMarkdownSnippet('bold')"
                >
                  粗体
                </button>
                <button
                  type="button"
                  class="md-tool-btn"
                  :disabled="editorMode === 'preview'"
                  title="插入引用"
                  @click="insertMarkdownSnippet('quote')"
                >
                  引用
                </button>
                <button
                  type="button"
                  class="md-tool-btn"
                  :disabled="editorMode === 'preview'"
                  title="插入无序列表"
                  @click="insertMarkdownSnippet('list')"
                >
                  列表
                </button>
                <button
                  type="button"
                  class="md-tool-btn spoiler-btn"
                  :disabled="editorMode === 'preview'"
                  title="插入防剧透遮罩 >!内容!<"
                  @click="insertMarkdownSnippet('spoiler')"
                >
                  防剧透
                </button>
              </div>

              <div class="mode-seg" role="tablist" aria-label="视图模式切换">
                <button
                  type="button"
                  role="tab"
                  class="mode-opt"
                  :class="{ active: editorMode === 'edit' }"
                  :aria-selected="editorMode === 'edit'"
                  @click="editorMode = 'edit'"
                >
                  编辑
                </button>
                <button
                  type="button"
                  role="tab"
                  class="mode-opt mode-split-opt"
                  :class="{ active: editorMode === 'split' }"
                  :aria-selected="editorMode === 'split'"
                  @click="editorMode = 'split'"
                >
                  分屏
                </button>
                <button
                  type="button"
                  role="tab"
                  class="mode-opt"
                  :class="{ active: editorMode === 'preview' }"
                  :aria-selected="editorMode === 'preview'"
                  @click="editorMode = 'preview'"
                >
                  预览
                </button>
              </div>
            </div>

            <div class="canvas-body" :class="{ 'is-split': editorMode === 'split' }">
              <textarea
                v-if="editorMode === 'edit' || editorMode === 'split'"
                ref="editorTextareaRef"
                v-model="draftContent"
                class="note-textarea"
                placeholder="使用 Markdown 记录感想、剧情分析或角色弧光…&#10;&#10;防剧透示例：>!关键剧情转折!<"
              />
              <div
                v-if="editorMode === 'preview' || editorMode === 'split'"
                class="note-preview-prose"
                @click="toggleSpoilerFromEvent"
                @keydown="toggleSpoilerFromEvent"
                v-html="renderedPreviewHtml"
              />
            </div>

            <div class="canvas-footer">
              <span class="footer-stats tabular-nums">
                共 {{ currentCharCount }} 字
                <template v-if="currentReadMinutes > 0"> · 约 {{ currentReadMinutes }} 分钟阅读</template>
              </span>
              <span class="footer-save">新建草稿 · Ctrl+S 保存</span>
            </div>
          </template>

          <!-- 状态 B：已有手记编辑 / 阅读画布 -->
          <template v-else-if="activeNote">
            <div class="canvas-topbar">
              <select
                v-model="draftType"
                class="note-type-select"
                aria-label="手记类型"
                @change="scheduleNoteSave"
              >
                <option v-for="opt in NOTE_TYPE_OPTIONS" :key="opt.key" :value="opt.key">
                  {{ opt.label }}
                </option>
              </select>

              <div class="canvas-top-actions">
                <button
                  type="button"
                  class="tool-micro-btn"
                  :class="{ active: activeNote.is_pinned }"
                  :title="activeNote.is_pinned ? '取消置顶' : '置顶此篇'"
                  @click="togglePinActiveNote"
                >
                  {{ activeNote.is_pinned ? '已置顶' : '置顶' }}
                </button>
                <button
                  type="button"
                  class="tool-micro-btn danger"
                  @click="deleteActiveNote"
                >
                  {{ confirmDeleteNoteId === activeNote.id ? '确认删除' : '删除' }}
                </button>
              </div>
            </div>

            <div class="canvas-title-wrap">
              <input
                ref="noteTitleInputRef"
                v-model="draftTitle"
                class="note-hero-title-input"
                maxlength="120"
                :placeholder="draftTitlePlaceholder"
                @input="scheduleNoteSave"
                @blur="flushNoteSave"
              />
            </div>

            <div class="canvas-subtoolbar">
              <div class="md-format-bar" :class="{ muted: editorMode === 'preview' }">
                <button
                  type="button"
                  class="md-tool-btn"
                  :disabled="editorMode === 'preview'"
                  title="插入二级标题"
                  @click="insertMarkdownSnippet('h2')"
                >
                  H2
                </button>
                <button
                  type="button"
                  class="md-tool-btn"
                  :disabled="editorMode === 'preview'"
                  title="加粗"
                  @click="insertMarkdownSnippet('bold')"
                >
                  粗体
                </button>
                <button
                  type="button"
                  class="md-tool-btn"
                  :disabled="editorMode === 'preview'"
                  title="插入引用"
                  @click="insertMarkdownSnippet('quote')"
                >
                  引用
                </button>
                <button
                  type="button"
                  class="md-tool-btn"
                  :disabled="editorMode === 'preview'"
                  title="插入无序列表"
                  @click="insertMarkdownSnippet('list')"
                >
                  列表
                </button>
                <button
                  type="button"
                  class="md-tool-btn spoiler-btn"
                  :disabled="editorMode === 'preview'"
                  title="插入防剧透遮罩 >!内容!<"
                  @click="insertMarkdownSnippet('spoiler')"
                >
                  防剧透
                </button>
              </div>

              <div class="mode-seg" role="tablist" aria-label="编辑与预览切换">
                <button
                  type="button"
                  role="tab"
                  class="mode-opt"
                  :class="{ active: editorMode === 'edit' }"
                  :aria-selected="editorMode === 'edit'"
                  @click="editorMode = 'edit'"
                >
                  编辑
                </button>
                <button
                  type="button"
                  role="tab"
                  class="mode-opt mode-split-opt"
                  :class="{ active: editorMode === 'split' }"
                  :aria-selected="editorMode === 'split'"
                  @click="editorMode = 'split'"
                >
                  分屏
                </button>
                <button
                  type="button"
                  role="tab"
                  class="mode-opt"
                  :class="{ active: editorMode === 'preview' }"
                  :aria-selected="editorMode === 'preview'"
                  @click="editorMode = 'preview'"
                >
                  预览
                </button>
              </div>
            </div>

            <div class="canvas-body" :class="{ 'is-split': editorMode === 'split' }">
              <textarea
                v-if="editorMode === 'edit' || editorMode === 'split'"
                ref="editorTextareaRef"
                v-model="draftContent"
                class="note-textarea"
                placeholder="使用 Markdown 记录感想、剧情分析或角色弧光…&#10;&#10;防剧透示例：>!关键剧情转折!< 或 <details><summary>展开剧透</summary>详细内容</details>"
                @input="onNoteContentInput"
                @blur="onNoteContentBlur"
              />
              <div
                v-if="editorMode === 'preview' || editorMode === 'split'"
                class="note-preview-prose"
                @click="toggleSpoilerFromEvent"
                @keydown="toggleSpoilerFromEvent"
                v-html="renderedPreviewHtml"
              />
            </div>

            <div class="canvas-footer">
              <span class="footer-stats tabular-nums">
                共 {{ currentCharCount }} 字
                <template v-if="currentReadMinutes > 0"> · 约 {{ currentReadMinutes }} 分钟阅读</template>
                <template v-if="formatNoteDateTime(activeNote.updated_at)">
                  · 更新于 {{ formatNoteDateTime(activeNote.updated_at) }}
                </template>
              </span>
              <span class="footer-save">
                <template v-if="noteSaveState === 'saving'">保存中…</template>
                <template v-else-if="noteSaveState === 'dirty'">待保存…</template>
                <template v-else>已保存 · Ctrl+S</template>
              </span>
            </div>
          </template>

          <!-- 状态 C：充实起步空白态 -->
          <div v-else-if="loadingNotes" class="notes-empty-state">
            <span>正在加载手记…</span>
          </div>

          <div v-else class="notes-starter-view">
            <div class="starter-head">
              <h3 class="starter-title">记录本作的评价与手记</h3>
              <p class="starter-sub">选择类型以预填极简大纲，支持 Markdown、行内防剧透与导出 .md</p>
            </div>

            <div class="starter-grid">
              <button
                v-for="tpl in starterCards"
                :key="tpl.key"
                type="button"
                class="starter-card"
                @click="openNewDraft(tpl.key)"
              >
                <div class="starter-card-top">
                  <span class="note-pill-type" :class="`type-${tpl.key}`">{{ tpl.short }}</span>
                  <span class="starter-arrow">开始写作</span>
                </div>
                <div class="starter-card-title">{{ tpl.label }}</div>
                <p class="starter-card-desc">{{ tpl.subtitle }}</p>
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.review-workspace {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ──────────────────── 上半区：紧凑评分卡片 ──────────────────── */

.rating-card {
  border-radius: 14px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-surface-subtle);
  padding: 20px 24px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.rating-card-top {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 28px;
  align-items: center;
}

.rating-overall-col {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-right: 22px;
  border-right: 1px solid var(--divider-subtle);
}

.overall-label-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.overall-caption {
  font-size: 12px;
  color: var(--text-muted);
  letter-spacing: 0.04em;
}

.overall-mode-tag {
  font-size: 10.5px;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-secondary);
}

.overall-score-display {
  display: flex;
  align-items: baseline;
  gap: 6px;
  line-height: 1;
}

.overall-star {
  font-size: 20px;
  color: rgba(255, 255, 255, 0.2);
  transition: color 160ms ease;
}

.overall-star.lit {
  color: var(--amber-text);
}

.overall-num {
  font-family: var(--font-serif);
  font-size: 36px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.overall-num.muted {
  color: var(--text-muted);
}

.overall-max {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-muted);
}

.overall-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.step-btn {
  width: 26px;
  height: 24px;
  padding: 0;
  border: 1px solid rgba(255, 255, 255, 0.09);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.045);
  color: var(--text-primary);
  font-size: 13px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color 140ms ease;
}

.step-btn:hover {
  background: rgba(255, 255, 255, 0.14);
}

.subtle-inline-btn {
  padding: 3px 7px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  font-size: 11.5px;
  cursor: pointer;
  transition: color 140ms ease, background-color 140ms ease;
}

.subtle-inline-btn:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.06);
}

.subtle-inline-btn.danger:hover {
  color: var(--danger-text);
  background: var(--danger-bg);
}

/* 4 行维度条 */
.rating-dims-col {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.dim-row {
  display: grid;
  grid-template-columns: 82px 1fr 38px 20px;
  align-items: center;
  gap: 12px;
}

.dim-label {
  font-size: 12.5px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.dim-bar-wrap {
  position: relative;
  height: 20px;
  display: flex;
  align-items: center;
}

.dim-track {
  width: 100%;
  height: 5px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
  pointer-events: none;
}

.dim-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, rgba(244, 244, 245, 0.52), rgba(252, 211, 77, 0.88));
  transition: width 100ms ease-out;
}

.dim-range-input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  opacity: 0;
  cursor: pointer;
}

.dim-bar-wrap:hover .dim-track {
  background: rgba(255, 255, 255, 0.14);
}

.dim-val {
  font-family: var(--font-mono);
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-primary);
  text-align: right;
}

.dim-val.empty {
  color: var(--text-muted);
}

.dim-clear-btn {
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  opacity: 0.65;
  transition: opacity 140ms ease, color 140ms ease;
}

.dim-clear-btn:hover {
  opacity: 1;
  color: var(--danger-text);
}

.dim-clear-btn.hidden {
  visibility: hidden;
  pointer-events: none;
}

/* 底部一句话短评 */
.short-review-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--divider-subtle);
}

.short-review-input {
  flex: 1;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
  padding: 2px 0;
}

.short-review-input::placeholder {
  color: var(--text-muted);
}

.save-hint {
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
}

/* ──────────────────── 下半区：双栏手记工作台 ──────────────────── */

.notes-card {
  border-radius: 14px;
  border: 1px solid var(--border-subtle);
  background: var(--bg-surface-subtle);
  overflow: hidden;
}

.notes-workspace-grid {
  display: grid;
  grid-template-columns: 272px minmax(0, 1fr);
  min-height: 480px;
}

/* 左栏目录 */
.notes-sidebar {
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--divider-subtle);
  background: rgba(255, 255, 255, 0.015);
  min-width: 0;
}

.notes-sidebar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 14px 14px 10px;
}

.sidebar-title-wrap {
  display: flex;
  align-items: center;
  gap: 7px;
}

.sidebar-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: 0.02em;
}

.sidebar-count {
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.07);
  color: var(--text-secondary);
  font-size: 11px;
}

.sidebar-new-btn {
  padding: 4px 10px;
  font-size: 12px;
}

.sidebar-filters {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 12px 10px;
  border-bottom: 1px solid var(--divider-subtle);
  flex-wrap: wrap;
}

.sidebar-filter-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  font-size: 11.5px;
  cursor: pointer;
  transition: background-color 140ms ease, color 140ms ease;
}

.sidebar-filter-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-primary);
}

.sidebar-filter-btn.active {
  background: rgba(255, 255, 255, 0.12);
  color: var(--text-primary);
  font-weight: 500;
}

.filter-count {
  font-size: 10.5px;
  opacity: 0.72;
}

.note-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.note-list-item {
  width: 100%;
  text-align: left;
  padding: 10px 11px;
  border-radius: 9px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  display: flex;
  flex-direction: column;
  gap: 5px;
  cursor: pointer;
  transition: background-color 140ms ease, border-color 140ms ease, color 140ms ease;
}

.note-list-item:hover {
  background: rgba(255, 255, 255, 0.045);
  color: var(--text-primary);
}

.note-list-item.active {
  background: rgba(255, 255, 255, 0.085);
  border-color: rgba(255, 255, 255, 0.12);
  color: var(--text-primary);
}

.note-item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.note-item-badges {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.note-pill-type {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
  flex-shrink: 0;
}

.note-pill-type.type-character {
  background: rgba(245, 158, 11, 0.16);
  color: var(--amber-text);
}

.note-pill-type.type-work {
  background: rgba(16, 185, 129, 0.16);
  color: var(--emerald-text);
}

.note-pin-badge {
  font-size: 10px;
  padding: 0 5px;
  border-radius: 4px;
  background: var(--amber-bg);
  color: var(--amber-text);
}

.note-item-date {
  font-size: 10.5px;
  color: var(--text-muted);
}

.note-item-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.note-list-item.active .note-item-title {
  font-weight: 600;
}

.note-item-excerpt {
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--text-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.note-item-excerpt.empty {
  opacity: 0.6;
}

.sidebar-empty {
  flex: 1;
  min-height: 160px;
  padding: 24px 14px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
}

.sidebar-empty-action {
  padding: 4px 10px;
  border-radius: 7px;
  border: 1px dashed rgba(255, 255, 255, 0.18);
  background: transparent;
  color: var(--text-secondary);
  font-size: 11.5px;
  cursor: pointer;
}

.sidebar-empty-action:hover {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-primary);
}

.notes-sidebar-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px;
  border-top: 1px solid var(--divider-subtle);
}

.sidebar-stats {
  font-size: 11px;
  color: var(--text-muted);
}

.export-md-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.045);
  color: var(--text-primary);
  font-size: 11.5px;
  cursor: pointer;
  transition: background-color 140ms ease, border-color 140ms ease;
}

.export-md-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.12);
  border-color: rgba(255, 255, 255, 0.18);
}

.export-md-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 右栏画布 */
.notes-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 480px;
}

.canvas-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 20px 8px;
  flex-wrap: wrap;
}

.canvas-top-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.create-type-seg {
  display: inline-flex;
  padding: 2px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.05);
  gap: 2px;
}

.create-type-opt {
  padding: 4px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
}

.create-type-opt.active {
  background: #f5f5f7;
  color: #0a0a0c;
  font-weight: 600;
}

.note-type-select {
  padding: 4px 9px;
  border-radius: 7px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.045);
  color: var(--text-secondary);
  font-size: 12px;
  outline: none;
}

.note-type-select option {
  background: #141418;
  color: var(--text-primary);
}

.canvas-title-wrap {
  padding: 2px 20px 10px;
}

.note-hero-title-input {
  width: 100%;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-family: var(--font-serif);
  font-size: 20px;
  font-weight: 600;
  line-height: 1.35;
  outline: none;
}

.note-hero-title-input::placeholder {
  color: var(--text-muted);
  font-weight: 500;
}

.canvas-subtoolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 20px;
  border-top: 1px solid var(--divider-subtle);
  border-bottom: 1px solid var(--divider-subtle);
  background: rgba(255, 255, 255, 0.015);
  flex-wrap: wrap;
}

.md-format-bar {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.md-format-bar.muted {
  opacity: 0.4;
}

.md-tool-btn {
  padding: 3px 8px;
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.035);
  color: var(--text-secondary);
  font-size: 11.5px;
  cursor: pointer;
  transition: background-color 140ms ease, color 140ms ease;
}

.md-tool-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-primary);
}

.md-tool-btn:disabled {
  cursor: default;
}

.md-tool-btn.spoiler-btn {
  color: var(--amber-text);
  border-color: rgba(252, 211, 77, 0.16);
}

.mode-seg {
  display: inline-flex;
  padding: 2px;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.055);
  gap: 2px;
}

.mode-opt {
  padding: 3px 10px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11.5px;
  cursor: pointer;
}

.mode-opt.active {
  background: rgba(255, 255, 255, 0.16);
  color: #ffffff;
  font-weight: 500;
}

.tool-micro-btn {
  padding: 4px 9px;
  border: none;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.045);
  color: var(--text-secondary);
  font-size: 11.5px;
  cursor: pointer;
  transition: background-color 140ms ease, color 140ms ease;
}

.tool-micro-btn:hover {
  background: rgba(255, 255, 255, 0.11);
  color: var(--text-primary);
}

.tool-micro-btn.active {
  background: var(--amber-bg);
  color: var(--amber-text);
}

.tool-micro-btn.danger:hover {
  background: var(--danger-bg);
  color: var(--danger-text);
}

.canvas-body {
  flex: 1;
  min-height: 340px;
  display: flex;
  flex-direction: column;
}

.canvas-body.is-split {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}

.canvas-body.is-split .note-textarea {
  border-right: 1px solid var(--divider-subtle);
  resize: none;
}

.note-textarea {
  width: 100%;
  flex: 1;
  min-height: 340px;
  padding: 18px 22px;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.8;
  resize: vertical;
  outline: none;
}

.note-textarea::placeholder {
  color: var(--text-muted);
}

.note-preview-prose {
  flex: 1;
  padding: 20px 24px 28px;
  min-height: 340px;
  overflow-y: auto;
  color: rgba(244, 244, 245, 0.9);
  font-size: 14.5px;
  line-height: 1.82;
}

.canvas-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 20px;
  border-top: 1px solid var(--divider-subtle);
  font-size: 11px;
  color: var(--text-muted);
  flex-wrap: wrap;
}

.footer-stats,
.footer-save {
  color: var(--text-muted);
}

/* 充实起步空白态 */
.notes-empty-state {
  flex: 1;
  min-height: 360px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--text-muted);
}

.notes-starter-view {
  flex: 1;
  padding: 40px 32px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 24px;
}

.starter-head {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.starter-title {
  margin: 0;
  font-family: var(--font-serif);
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}

.starter-sub {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
}

.starter-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.starter-card {
  text-align: left;
  padding: 18px 18px 16px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.025);
  display: flex;
  flex-direction: column;
  gap: 10px;
  cursor: pointer;
  transition:
    transform 160ms ease,
    border-color 160ms ease,
    background-color 160ms ease;
}

.starter-card:hover {
  transform: translateY(-2px);
  border-color: rgba(255, 255, 255, 0.18);
  background: rgba(255, 255, 255, 0.055);
}

.starter-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.starter-arrow {
  font-size: 11px;
  color: var(--text-muted);
  opacity: 0.75;
  transition: opacity 160ms ease, color 160ms ease;
}

.starter-card:hover .starter-arrow {
  opacity: 1;
  color: var(--text-primary);
}

.starter-card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.starter-card-desc {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--text-secondary);
}

/* Markdown 预览正文与暗色防剧透遮罩 */
.note-preview-prose :deep(.md-h) {
  margin: 18px 0 8px;
  font-family: var(--font-serif);
  font-weight: 600;
  color: var(--text-primary);
}

.note-preview-prose :deep(.md-h:first-child) {
  margin-top: 0;
}

.note-preview-prose :deep(.md-h1) {
  font-size: 20px;
}

.note-preview-prose :deep(.md-h2) {
  font-size: 17px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--divider-subtle);
}

.note-preview-prose :deep(.md-h3) {
  font-size: 15px;
}

.note-preview-prose :deep(.md-p) {
  margin: 0 0 12px;
}

.note-preview-prose :deep(.md-empty) {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
}

.note-preview-prose :deep(.md-quote) {
  margin: 12px 0;
  padding: 8px 14px;
  border-left: 2px solid rgba(255, 255, 255, 0.28);
  background: rgba(255, 255, 255, 0.03);
  border-radius: 0 8px 8px 0;
  color: var(--text-secondary);
}

.note-preview-prose :deep(.md-list) {
  margin: 8px 0 12px;
  padding-left: 22px;
}

.note-preview-prose :deep(.md-list li) {
  margin-bottom: 4px;
}

.note-preview-prose :deep(.md-inline-code) {
  font-family: var(--font-mono);
  font-size: 12.5px;
  padding: 1px 5px;
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.08);
}

.note-preview-prose :deep(.md-code-block) {
  margin: 12px 0;
  padding: 12px 14px;
  border-radius: 9px;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid var(--divider-subtle);
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.6;
}

.note-preview-prose :deep(.md-hr) {
  border: none;
  border-top: 1px solid var(--divider-subtle);
  margin: 16px 0;
}

.note-preview-prose :deep(.md-link) {
  color: #f4f4f5;
  text-decoration: underline;
  text-underline-offset: 3px;
}

/* 行内暗色防剧透遮罩 */
.note-preview-prose :deep(.md-spoiler) {
  display: inline;
  padding: 1px 6px;
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.14);
  color: transparent;
  text-shadow: 0 0 8px rgba(244, 244, 245, 0.45);
  cursor: pointer;
  user-select: none;
  transition:
    background-color 180ms ease,
    color 180ms ease,
    text-shadow 180ms ease;
}

.note-preview-prose :deep(.md-spoiler:hover) {
  background: rgba(255, 255, 255, 0.2);
}

.note-preview-prose :deep(.md-spoiler.revealed) {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
  text-shadow: none;
  user-select: text;
}

/* <details> 暗色剧透折叠块 */
.note-preview-prose :deep(.md-details) {
  margin: 12px 0;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.09);
  background: rgba(255, 255, 255, 0.03);
  overflow: hidden;
}

.note-preview-prose :deep(.md-summary) {
  padding: 9px 14px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
  list-style: none;
}

.note-preview-prose :deep(.md-summary::before) {
  content: '▸ ';
  opacity: 0.7;
}

.note-preview-prose :deep(.md-details[open] .md-summary::before) {
  content: '▾ ';
}

.note-preview-prose :deep(.md-summary:hover) {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.04);
}

.note-preview-prose :deep(.md-details-body) {
  padding: 4px 14px 12px;
  border-top: 1px solid var(--divider-subtle);
}

@media (max-width: 1080px) {
  .mode-split-opt {
    display: none;
  }
  .canvas-body.is-split {
    grid-template-columns: 1fr;
  }
  .canvas-body.is-split .note-textarea {
    border-right: none;
    border-bottom: 1px solid var(--divider-subtle);
  }
  .starter-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .notes-workspace-grid {
    grid-template-columns: 1fr;
    min-height: 0;
  }

  .notes-sidebar {
    border-right: none;
    border-bottom: 1px solid var(--divider-subtle);
    max-height: 260px;
  }

  .notes-main {
    min-height: 380px;
  }
}

@media (max-width: 780px) {
  .rating-card-top {
    grid-template-columns: 1fr;
    gap: 18px;
  }

  .rating-overall-col {
    padding-right: 0;
    padding-bottom: 14px;
    border-right: none;
    border-bottom: 1px solid var(--divider-subtle);
  }

  .notes-starter-view {
    padding: 24px 18px;
  }
}
</style>
