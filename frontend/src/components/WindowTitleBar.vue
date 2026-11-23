<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useLibraryStore } from '@/stores/library'

const store = useLibraryStore()

const isDesktop = ref(false)
const isMaximized = ref(false)
const isFullscreen = ref(false)

function getDesktopApi() {
  return window.pywebview?.api
}

function syncSafeTopOffset() {
  const safeTop = isDesktop.value && !isFullscreen.value ? '32px' : '0px'
  document.documentElement.style.setProperty('--titlebar-safe-top', safeTop)
}

async function syncDesktopState() {
  const api = getDesktopApi()
  if (!api) {
    isDesktop.value = false
    syncSafeTopOffset()
    return
  }
  isDesktop.value = true
  try {
    const state = await api.get_window_state?.()
    if (state) {
      isDesktop.value = Boolean(state.is_desktop)
      isMaximized.value = Boolean(state.is_maximized)
      isFullscreen.value = Boolean(state.is_fullscreen)
    }
  } catch {
    // ignore transient bridge error
  }
  syncSafeTopOffset()
}

async function handleMinimize() {
  try {
    await getDesktopApi()?.minimize?.()
  } catch {
    // ignore
  }
}

async function handleToggleMaximize() {
  try {
    const next = await getDesktopApi()?.toggle_maximize?.()
    if (typeof next === 'boolean') {
      isMaximized.value = next
    } else {
      isMaximized.value = !isMaximized.value
    }
    await syncDesktopState()
  } catch {
    // ignore
  }
}

async function handleToggleFullscreen() {
  const api = getDesktopApi()
  if (isDesktop.value && api?.toggle_fullscreen) {
    try {
      const next = await api.toggle_fullscreen()
      isFullscreen.value = typeof next === 'boolean' ? next : !isFullscreen.value
      await syncDesktopState()
    } catch {
      // ignore
    }
    syncSafeTopOffset()
    return
  }

  // 浏览器环境回退原生 Fullscreen API
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen()
      isFullscreen.value = false
    } else {
      await document.documentElement.requestFullscreen()
      isFullscreen.value = true
    }
  } catch {
    // ignore browser fullscreen restriction
  }
  syncSafeTopOffset()
}

async function handleExitFullscreen() {
  if (!isFullscreen.value) return
  const api = getDesktopApi()
  if (isDesktop.value && api?.exit_fullscreen) {
    try {
      await api.exit_fullscreen()
      isFullscreen.value = false
      await syncDesktopState()
    } catch {
      // ignore
    }
    syncSafeTopOffset()
    return
  }
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen()
    }
    isFullscreen.value = false
  } catch {
    // ignore
  }
  syncSafeTopOffset()
}

function onDragStripMouseDown(e: MouseEvent) {
  if (e.button !== 0 || !isDesktop.value || !isMaximized.value || isFullscreen.value) return
  const startX = e.screenX
  const startY = e.screenY
  const ratioX = Math.max(0.15, Math.min(0.85, e.clientX / Math.max(window.innerWidth, 1)))
  let restored = false

  const cleanup = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', cleanup)
  }

  const onMove = (ev: MouseEvent) => {
    if (restored) return
    if (Math.hypot(ev.screenX - startX, ev.screenY - startY) > 4) {
      restored = true
      cleanup()
      isMaximized.value = false
      void getDesktopApi()?.restore_for_drag?.(ratioX)
    }
  }

  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', cleanup)
}

async function handleClose() {
  try {
    const api = getDesktopApi()
    if (api?.close) {
      await api.close()
    } else if (api?.quit_app) {
      await api.quit_app()
    }
  } catch {
    // ignore
  }
}

function hasAnyModalOpen(): boolean {
  if (
    store.showQuickSearch ||
    store.showCollectionModal ||
    store.showTimeLedger ||
    store.showEditModal ||
    store.showImportModal ||
    store.showSettingsModal
  ) {
    return true
  }
  return Boolean(document.querySelector('.picker-backdrop, .lightbox-backdrop, .modal-backdrop'))
}

function onBrowserFullscreenChange() {
  if (!isDesktop.value) {
    isFullscreen.value = Boolean(document.fullscreenElement)
    syncSafeTopOffset()
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'F11') {
    e.preventDefault()
    void handleToggleFullscreen()
    return
  }

  if (e.key === 'Escape' && isFullscreen.value && !hasAnyModalOpen()) {
    e.preventDefault()
    void handleExitFullscreen()
  }
}

function onPywebviewReady() {
  void syncDesktopState()
}

function onNativeWindowState(e: Event) {
  const detail = (e as CustomEvent<{ is_desktop?: boolean; is_maximized?: boolean; is_fullscreen?: boolean }>).detail
  if (!detail) return
  if (typeof detail.is_desktop === 'boolean') isDesktop.value = detail.is_desktop
  if (typeof detail.is_maximized === 'boolean') isMaximized.value = detail.is_maximized
  if (typeof detail.is_fullscreen === 'boolean') isFullscreen.value = detail.is_fullscreen
  syncSafeTopOffset()
}

watch([isDesktop, isFullscreen], () => {
  syncSafeTopOffset()
})

onMounted(() => {
  void syncDesktopState()
  if (!isDesktop.value) {
    isFullscreen.value = Boolean(document.fullscreenElement)
  }
  syncSafeTopOffset()
  window.addEventListener('pywebviewready', onPywebviewReady)
  window.addEventListener('tsumugi-window-state', onNativeWindowState)
  window.addEventListener('keydown', onKeydown)
  document.addEventListener('fullscreenchange', onBrowserFullscreenChange)
})

onBeforeUnmount(() => {
  window.removeEventListener('pywebviewready', onPywebviewReady)
  window.removeEventListener('tsumugi-window-state', onNativeWindowState)
  window.removeEventListener('keydown', onKeydown)
  document.removeEventListener('fullscreenchange', onBrowserFullscreenChange)
  document.documentElement.style.setProperty('--titlebar-safe-top', '0px')
})
</script>

<template>
  <!-- 桌面端无边框沉浸式顶部拖拽栏与右上角极简窗口控件 -->
  <div v-if="isDesktop && !isFullscreen" class="window-titlebar">
    <div
      class="drag-strip pywebview-drag-region"
      @mousedown="onDragStripMouseDown"
      @dblclick="handleToggleMaximize"
    />

    <div class="win-controls" role="group" aria-label="窗口控制">
      <button
        type="button"
        class="win-btn"
        title="全屏 (F11)"
        aria-label="全屏"
        @click="handleToggleFullscreen"
      >
        <svg viewBox="0 0 16 16" width="12.5" height="12.5" fill="none" stroke="currentColor" stroke-width="1.45">
          <path d="M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>

      <button
        type="button"
        class="win-btn"
        title="最小化"
        aria-label="最小化"
        @click="handleMinimize"
      >
        <svg viewBox="0 0 16 16" width="12.5" height="12.5" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M3 8.5h10" stroke-linecap="round" />
        </svg>
      </button>

      <button
        type="button"
        class="win-btn"
        :title="isMaximized ? '还原' : '最大化'"
        :aria-label="isMaximized ? '还原' : '最大化'"
        @click="handleToggleMaximize"
      >
        <svg
          v-if="isMaximized"
          viewBox="0 0 16 16"
          width="12.5"
          height="12.5"
          fill="none"
          stroke="currentColor"
          stroke-width="1.4"
        >
          <rect x="3" y="5" width="8" height="8" rx="1.2" />
          <path d="M5.5 5V3.7c0-.4.3-.7.7-.7h6.1c.4 0 .7.3.7.7v6.1c0 .4-.3.7-.7.7H11" stroke-linecap="round" />
        </svg>
        <svg
          v-else
          viewBox="0 0 16 16"
          width="12.5"
          height="12.5"
          fill="none"
          stroke="currentColor"
          stroke-width="1.4"
        >
          <rect x="3" y="3" width="10" height="10" rx="1.4" />
        </svg>
      </button>

      <button
        type="button"
        class="win-btn win-btn-close"
        title="关闭"
        aria-label="关闭"
        @click="handleClose"
      >
        <svg viewBox="0 0 16 16" width="12.5" height="12.5" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M4 4l8 8M12 4l-8 8" stroke-linecap="round" />
        </svg>
      </button>
    </div>
  </div>

  <!-- 全屏态（桌面端 + 浏览器通用）：仅鼠标移至右上角时轻柔浮现「退出全屏」 -->
  <div v-else-if="isFullscreen" class="fs-corner-zone">
    <button
      type="button"
      class="fs-exit-pill"
      title="退出全屏 (F11 / Esc)"
      @click="handleExitFullscreen"
    >
      <svg viewBox="0 0 16 16" width="12.5" height="12.5" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M6 2.5V6H2.5M13.5 6H10V2.5M10 13.5V10h3.5M2.5 10H6v3.5" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      <span>退出全屏</span>
    </button>
  </div>
</template>

<style scoped>
.window-titlebar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 36px;
  z-index: 9999;
  display: flex;
  align-items: center;
  pointer-events: none;
  user-select: none;
}

.drag-strip {
  flex: 1;
  height: 100%;
  pointer-events: auto;
  -webkit-app-region: drag;
}

.win-controls {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin-right: 8px;
  padding: 2px;
  border-radius: 9px;
  pointer-events: auto;
  -webkit-app-region: no-drag;
  opacity: 0.56;
  background: rgba(10, 10, 12, 0.28);
  border: 1px solid rgba(255, 255, 255, 0.06);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  transition:
    opacity 180ms ease,
    background-color 180ms ease,
    border-color 180ms ease;
}

.win-controls:hover {
  opacity: 1;
  background: rgba(16, 16, 20, 0.78);
  border-color: rgba(255, 255, 255, 0.12);
}

.win-btn {
  width: 30px;
  height: 24px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: rgba(244, 244, 245, 0.88);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition:
    background-color 140ms ease,
    color 140ms ease;
}

.win-btn:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.win-btn-close:hover {
  background: rgba(220, 38, 38, 0.78);
  color: #ffffff;
}

/* 全屏模式右上角热区与轻柔浮现的退出全屏按钮 */
.fs-corner-zone {
  position: fixed;
  top: 0;
  right: 0;
  width: 156px;
  height: 54px;
  z-index: 9999;
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  padding: 10px 14px 0 0;
}

.fs-exit-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 11px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(14, 14, 18, 0.78);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  color: #f4f4f5;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  opacity: 0;
  transform: translateY(-4px);
  pointer-events: none;
  transition:
    opacity 180ms ease,
    transform 180ms ease,
    background-color 150ms ease;
}

.fs-corner-zone:hover .fs-exit-pill,
.fs-exit-pill:focus-visible {
  opacity: 1;
  transform: translateY(0);
  pointer-events: auto;
}

.fs-exit-pill:hover {
  background: rgba(28, 28, 34, 0.92);
}
</style>
