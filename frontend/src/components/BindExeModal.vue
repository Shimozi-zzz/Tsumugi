<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { isDesktopBridgeAvailable, libraryApi, pickNativeFile } from '@/api/client'
import { useLibraryStore } from '@/stores/library'
import type { Game, LaunchMode, PathBrowseEntry } from '@/types'

const props = defineProps<{
  game: Game
}>()

const emit = defineEmits<{
  close: []
}>()

const store = useLibraryStore()
const hasBridge = isDesktopBridgeAvailable()

const exePath = ref(props.game.media?.exe_path || '')
const launchMode = ref<LaunchMode>(
  props.game.media?.launch_mode === 'le' || props.game.media?.launch_mode === 'cli'
    ? props.game.media.launch_mode
    : 'direct',
)
const launchArgs = ref(props.game.media?.launch_args || '')
const submitting = ref(false)
const isDragging = ref(false)

// 纯 Web 模式内嵌路径浏览器状态
const browserOpen = ref(false)
const browserLoading = ref(false)
const browserDir = ref('')
const browserParent = ref<string | null>(null)
const browserEntries = ref<PathBrowseEntry[]>([])
const showAllFiles = ref(false)

const EXECUTABLE_EXTS = ['.exe', '.lnk', '.bat', '.cmd', '.sh', '.appimage']

const canSubmit = computed(() => {
  if (submitting.value) return false
  if (exePath.value.trim()) return true
  return launchMode.value === 'cli' && Boolean(launchArgs.value.trim())
})

const modeOptions: { value: LaunchMode; label: string; hint: string }[] = [
  { value: 'direct', label: '直接运行', hint: '.exe / .lnk' },
  { value: 'le', label: 'Locale Emulator', hint: '日区转区启动' },
  { value: 'cli', label: '自定义参数', hint: 'CLI / Steam URI' },
]

async function loadDirectory(targetPath = '') {
  browserLoading.value = true
  try {
    const res = await libraryApi.browsePath(
      targetPath,
      showAllFiles.value ? [] : EXECUTABLE_EXTS,
    )
    browserDir.value = res.current_dir
    browserParent.value = res.parent_dir
    browserEntries.value = res.entries
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '读取目录失败', 'warning')
  } finally {
    browserLoading.value = false
  }
}

async function handlePickFile() {
  if (hasBridge) {
    const picked = await pickNativeFile('选择游戏主程序 (.exe / .lnk)', [
      'Executable (*.exe;*.lnk;*.bat)',
      'All files (*.*)',
    ])
    if (picked) {
      exePath.value = picked
    }
    return
  }

  browserOpen.value = !browserOpen.value
  if (browserOpen.value) {
    await loadDirectory(exePath.value.trim())
  }
}

function handleEntryClick(entry: PathBrowseEntry) {
  if (entry.is_dir) {
    void loadDirectory(entry.path)
  } else {
    exePath.value = entry.path
    browserOpen.value = false
  }
}

function toggleShowAllFiles() {
  showAllFiles.value = !showAllFiles.value
  void loadDirectory(browserDir.value)
}

function handleDrop(ev: DragEvent) {
  ev.preventDefault()
  isDragging.value = false
  const dt = ev.dataTransfer
  if (!dt) return

  const textPath = dt.getData('text/plain')?.trim()
  if (textPath) {
    exePath.value = textPath.replace(/^["']|["']$/g, '')
    return
  }

  const file = dt.files?.[0] as (File & { path?: string }) | undefined
  if (file?.path) {
    exePath.value = file.path
  } else if (file?.name) {
    store.notify(`浏览器出于安全限制无法读取完整路径，请粘贴「${file.name}」的绝对路径或使用文件浏览`, 'info')
  }
}

async function saveAndLaunch() {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    const trimmedPath = exePath.value.trim()
    const trimmedArgs = launchArgs.value.trim()

    await store.updateGamePatch(props.game.id, {
      media: {
        exe_path: trimmedPath,
        launch_mode: launchMode.value,
        launch_args: trimmedArgs,
      },
    })

    await store.launchGame(props.game.id)
    emit('close')
  } catch (err) {
    store.notify(err instanceof Error ? err.message : '保存启动配置失败', 'error')
  } finally {
    submitting.value = false
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    emit('close')
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <div
      class="modal-card bind-card"
      :class="{ dragging: isDragging }"
      @dragover.prevent="isDragging = true"
      @dragleave.self="isDragging = false"
      @drop="handleDrop"
    >
      <div class="modal-head">
        <div>
          <h2>绑定启动程序</h2>
          <p class="modal-desc">尚未设置《{{ game.title }}》的启动路径</p>
        </div>
        <button class="close-icon-btn" aria-label="关闭" @click="emit('close')">
          <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M5 5l10 10M15 5L5 15" stroke-linecap="round" />
          </svg>
        </button>
      </div>

      <div class="modal-body">
        <!-- 路径输入 + 选择文件 -->
        <div class="field">
          <label>可执行文件路径或协议 URI</label>
          <div class="path-row">
            <input
              v-model="exePath"
              class="input"
              placeholder="例如 D:\Games\Game.exe 或 steam://rungameid/..."
              autofocus
              @keydown.enter="saveAndLaunch"
            />
            <button type="button" class="btn btn-sm pick-btn" @click="handlePickFile">
              <svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7">
                <path d="M3 5.5A1.5 1.5 0 0 1 4.5 4h3.2l1.6 1.8h6.2A1.5 1.5 0 0 1 17 7.3v7.2a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 14.5v-9z" />
              </svg>
              <span>{{ browserOpen ? '收起浏览' : '选择文件' }}</span>
            </button>
          </div>
          <span class="field-hint">支持直接粘贴绝对路径、拖拽路径文本，或点击右侧浏览本地文件</span>
        </div>

        <!-- 纯 Web 模式轻量内嵌目录浏览器 -->
        <div v-if="browserOpen" class="inline-browser">
          <div class="browser-bar">
            <button
              type="button"
              class="browser-nav-btn"
              :disabled="browserParent === null || browserLoading"
              title="返回上级目录"
              @click="browserParent !== null && loadDirectory(browserParent)"
            >
              ↑ 上级
            </button>
            <span class="browser-cwd" :title="browserDir || '根目录'">
              {{ browserDir || '磁盘驱动器' }}
            </span>
            <button type="button" class="browser-filter-btn" @click="toggleShowAllFiles">
              {{ showAllFiles ? '仅可执行文件' : '显示全部文件' }}
            </button>
          </div>

          <div class="browser-list">
            <div v-if="browserLoading" class="browser-state">正在读取目录…</div>
            <div v-else-if="browserEntries.length === 0" class="browser-state">
              当前目录下无匹配文件
            </div>
            <button
              v-for="entry in browserEntries"
              v-else
              :key="entry.path"
              type="button"
              class="browser-item"
              :class="{ 'is-file': !entry.is_dir }"
              @click="handleEntryClick(entry)"
            >
              <svg
                v-if="entry.is_dir"
                viewBox="0 0 20 20"
                width="14"
                height="14"
                fill="none"
                stroke="currentColor"
                stroke-width="1.6"
              >
                <path d="M3 5.5A1.5 1.5 0 0 1 4.5 4h3.2l1.6 1.8h6.2A1.5 1.5 0 0 1 17 7.3v7.2a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 3 14.5v-9z" />
              </svg>
              <svg
                v-else
                viewBox="0 0 20 20"
                width="14"
                height="14"
                fill="none"
                stroke="currentColor"
                stroke-width="1.6"
              >
                <path d="M6 3.5h5.5L15 7v9.5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-12a1 1 0 0 1 1-1z" />
                <path d="M11 3.5V7h4" />
              </svg>
              <span class="browser-item-name">{{ entry.name }}</span>
            </button>
          </div>
        </div>

        <!-- 快捷启动模式单选 -->
        <div class="field">
          <label>启动方式</label>
          <div class="mode-grid">
            <button
              v-for="opt in modeOptions"
              :key="opt.value"
              type="button"
              class="mode-option"
              :class="{ active: launchMode === opt.value }"
              @click="launchMode = opt.value"
            >
              <span class="mode-name">{{ opt.label }}</span>
              <span class="mode-hint">{{ opt.hint }}</span>
            </button>
          </div>
        </div>

        <!-- 自定义参数模式附加输入 -->
        <div v-if="launchMode === 'cli'" class="field">
          <label>附加命令行参数（可选）</label>
          <input
            v-model="launchArgs"
            class="input"
            placeholder="例如 -windowed --lang=zh"
          />
        </div>
      </div>

      <div class="modal-foot">
        <button type="button" class="btn btn-ghost" @click="emit('close')">取消</button>
        <button
          type="button"
          class="btn btn-primary"
          :disabled="!canSubmit"
          @click="saveAndLaunch"
        >
          <svg v-if="!submitting" viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
            <path d="M7.5 5.25v13.5l11-6.75-11-6.75z" />
          </svg>
          <span>{{ submitting ? '正在启动…' : '保存并立即启动' }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bind-card {
  max-width: 540px;
  transition: border-color var(--duration-fast) var(--ease-out-expo);
}

.bind-card.dragging {
  border-color: rgba(255, 255, 255, 0.34);
}

.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--divider-subtle);
}

.modal-head h2 {
  margin: 0;
  font-size: 16.5px;
  font-weight: 600;
  color: var(--text-primary);
}

.modal-desc {
  margin: 5px 0 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--text-secondary);
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
  flex-shrink: 0;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.close-icon-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.modal-body {
  padding: 20px 24px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.field label {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-secondary);
}

.path-row {
  display: flex;
  gap: 8px;
}

.path-row .input {
  flex: 1;
}

.pick-btn {
  flex-shrink: 0;
  padding: 0 13px;
}

.field-hint {
  font-size: 11.5px;
  color: var(--text-muted);
}

/* Inline Web File Browser */
.inline-browser {
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.03);
  overflow: hidden;
  box-shadow: inset 0 1px 0 var(--divider-subtle);
}

.browser-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--divider-subtle);
  background: rgba(255, 255, 255, 0.02);
}

.browser-nav-btn,
.browser-filter-btn {
  border: none;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-secondary);
  font-size: 11.5px;
  padding: 4px 8px;
  flex-shrink: 0;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.browser-nav-btn:hover:not(:disabled),
.browser-filter-btn:hover {
  background: var(--surface-active);
  color: var(--text-primary);
}

.browser-nav-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.browser-cwd {
  flex: 1;
  min-width: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.browser-list {
  max-height: 176px;
  overflow-y: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.browser-state {
  padding: 20px 12px;
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
}

.browser-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 9px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12.5px;
  text-align: left;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.browser-item:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.browser-item.is-file {
  color: var(--text-primary);
}

.browser-item-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Mode Selector */
.mode-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.mode-option {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  padding: 10px 12px;
  border: none;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.035);
  text-align: left;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    box-shadow var(--duration-fast) var(--ease-out-expo);
}

.mode-option:hover {
  background: var(--surface-hover);
}

.mode-option.active {
  background: var(--surface-active);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.16);
}

.mode-name {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-primary);
}

.mode-hint {
  font-size: 11px;
  color: var(--text-muted);
}

.modal-foot {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  padding: 14px 24px;
  border-top: 1px solid var(--divider-subtle);
}
</style>
