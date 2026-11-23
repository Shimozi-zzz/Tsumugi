<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import CollectionManagerModal from '@/components/CollectionManagerModal.vue'
import EmptyLibraryView from '@/components/EmptyLibraryView.vue'
import ExternalImportModal from '@/components/ExternalImportModal.vue'
import GameEditModal from '@/components/GameEditModal.vue'
import HoverSidebar from '@/components/HoverSidebar.vue'
import ImportModal from '@/components/ImportModal.vue'
import QuickSearchModal from '@/components/QuickSearchModal.vue'
import SettingsModal from '@/components/SettingsModal.vue'
import TimeLedgerModal from '@/components/TimeLedgerModal.vue'
import WindowTitleBar from '@/components/WindowTitleBar.vue'
import { useLibraryStore } from '@/stores/library'
import { useTaskStore } from '@/stores/tasks'
import type { DroppedFileInfo } from '@/types'
import DiscShelfView from '@/views/DiscShelfView.vue'
import GameDetailView from '@/views/GameDetailView.vue'

const MIN_BOOT_CURTAIN_MS = 280

const store = useLibraryStore()
const taskStore = useTaskStore()

const bootVisible = ref(true)
const workspaceReady = ref(false)
const entranceAnimating = ref(false)

let bootHoldTimer: number | null = null
let entranceClearTimer: number | null = null

function handleGlobalKeydown(e: KeyboardEvent) {
  // Ctrl + K / Cmd + K 呼出快速搜索弹窗
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    if (!store.isInitialized) return
    store.showQuickSearch = !store.showQuickSearch
    return
  }

  if (e.key === 'Escape') {
    if (store.showQuickSearch) store.showQuickSearch = false
    else if (store.showCollectionModal) store.showCollectionModal = false
    else if (store.showTimeLedger) store.showTimeLedger = false
    else if (store.showEditModal) store.showEditModal = false
    else if (store.showExternalImportModal) store.showExternalImportModal = false
    else if (store.showImportModal) store.showImportModal = false
    else if (store.showSettingsModal) store.showSettingsModal = false
  }
}

function handleDesktopFileDrop(ev: Event) {
  const customEv = ev as CustomEvent<DroppedFileInfo>
  if (!customEv.detail) return
  store.notify(`已识别拖入路径：${customEv.detail.suggested_title}`, 'info')
  store.openImport('local', customEv.detail.kind === 'folder' ? 'batch' : 'single', customEv.detail)
}

function triggerToastAction(toastId: number, fn?: () => void) {
  store.dismissToast(toastId)
  fn?.()
}

async function bootApplication() {
  const bootStartedAt = performance.now()
  await store.initialize()

  const elapsed = performance.now() - bootStartedAt
  const remaining = Math.max(0, MIN_BOOT_CURTAIN_MS - elapsed)
  if (remaining > 0) {
    await new Promise<void>((resolve) => {
      bootHoldTimer = window.setTimeout(() => {
        bootHoldTimer = null
        resolve()
      }, remaining)
    })
  }

  bootVisible.value = false
  workspaceReady.value = true
  entranceAnimating.value = true

  // 动画结束后清除 transform，避免干扰内部 fixed 与 backdrop-filter 定位
  entranceClearTimer = window.setTimeout(() => {
    entranceAnimating.value = false
    entranceClearTimer = null
  }, 400)
}

onMounted(() => {
  void bootApplication()
  void taskStore.pollNow()
  window.addEventListener('keydown', handleGlobalKeydown)
  window.addEventListener('tsumugi:file-drop', handleDesktopFileDrop)
})

onBeforeUnmount(() => {
  if (bootHoldTimer !== null) clearTimeout(bootHoldTimer)
  if (entranceClearTimer !== null) clearTimeout(entranceClearTimer)
  taskStore.stopPolling()
  window.removeEventListener('keydown', handleGlobalKeydown)
  window.removeEventListener('tsumugi:file-drop', handleDesktopFileDrop)
})
</script>

<template>
  <div class="app-shell">
    <WindowTitleBar />

    <!-- 仅在初始化完成后挂载侧栏与主工作区，彻底杜绝空库页闪现 -->
    <template v-if="store.isInitialized">
      <HoverSidebar />

      <div
        class="workspace-stage"
        :class="{
          'workspace-hidden': !workspaceReady,
          'workspace-entering': entranceAnimating,
        }"
      >
        <Transition name="view-switch" mode="out-in">
          <EmptyLibraryView v-if="store.games.length === 0" key="empty" />
          <GameDetailView v-else-if="store.viewMode === 'detail'" key="detail" />
          <DiscShelfView v-else key="shelf" />
        </Transition>
      </div>
    </template>

    <!-- 极简启动幕布（#0a0a0c 炭黑底 + 低饱和 TSUMUGI 衬线字标） -->
    <Transition name="boot-curtain">
      <div v-if="bootVisible" class="boot-curtain" aria-hidden="true">
        <span class="boot-wordmark">TSUMUGI</span>
      </div>
    </Transition>

    <!-- 全局弹窗（统一缩放淡入与亚克力遮罩过渡） -->
    <Transition name="modal-pop">
      <ImportModal v-if="store.showImportModal" />
    </Transition>
    <Transition name="modal-pop">
      <ExternalImportModal v-if="store.showExternalImportModal" />
    </Transition>
    <Transition name="modal-pop">
      <QuickSearchModal v-if="store.showQuickSearch" />
    </Transition>
    <Transition name="modal-pop">
      <SettingsModal v-if="store.showSettingsModal" />
    </Transition>
    <Transition name="modal-pop">
      <GameEditModal v-if="store.showEditModal" />
    </Transition>
    <Transition name="modal-pop">
      <TimeLedgerModal v-if="store.showTimeLedger" />
    </Transition>
    <Transition name="modal-pop">
      <CollectionManagerModal v-if="store.showCollectionModal" />
    </Transition>

    <!-- 轻量悬浮通知胶囊堆栈 -->
    <div class="toast-stack">
      <TransitionGroup name="toast-slide">
        <div
          v-for="t in store.toasts"
          :key="t.id"
          class="toast-item"
          :class="`toast-${t.type}`"
        >
          <span class="toast-dot" />
          <span class="toast-msg">{{ t.message }}</span>
          <button
            v-if="t.actionLabel && t.onAction"
            type="button"
            class="toast-action"
            @click="triggerToastAction(t.id, t.onAction)"
          >
            {{ t.actionLabel }}
          </button>
        </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  position: relative;
  min-height: 100vh;
  width: 100%;
  background: var(--bg-canvas);
}

/* 主工作区平滑入场动效（仅 GPU 合成属性，结束后清除 transform） */
.workspace-stage {
  min-height: 100vh;
  width: 100%;
}

.workspace-stage.workspace-hidden {
  opacity: 0;
  pointer-events: none;
}

.workspace-stage.workspace-entering {
  will-change: opacity, transform;
  animation: workspace-boot-enter 380ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
}

@keyframes workspace-boot-enter {
  from {
    opacity: 0;
    transform: scale(0.988) translateY(6px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

/* 极简启动幕布 */
.boot-curtain {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: #0a0a0c;
  display: flex;
  align-items: center;
  justify-content: center;
  user-select: none;
}

.boot-wordmark {
  font-family: var(--font-serif);
  font-size: clamp(20px, 2.2vw, 26px);
  font-weight: 500;
  letter-spacing: 0.28em;
  text-indent: 0.28em;
  background: linear-gradient(
    110deg,
    rgba(244, 244, 245, 0.42) 0%,
    rgba(255, 255, 255, 0.92) 48%,
    rgba(244, 244, 245, 0.46) 100%
  );
  background-size: 220% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: wordmark-sheen 1.8s cubic-bezier(0.16, 1, 0.3, 1) infinite;
}

@keyframes wordmark-sheen {
  0% {
    background-position: 120% 0;
  }
  100% {
    background-position: -120% 0;
  }
}

.boot-curtain-leave-active {
  transition: opacity 320ms cubic-bezier(0.16, 1, 0.3, 1);
}

.boot-curtain-leave-to {
  opacity: 0;
}

.toast-stack {
  position: fixed;
  top: 22px;
  right: 26px;
  z-index: 160;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  pointer-events: none;
}

.toast-item {
  pointer-events: auto;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  max-width: 400px;
  padding: 10px 16px;
  border-radius: 999px;
  font-size: 12.5px;
  line-height: 1.4;
  color: var(--text-primary);
  background: rgba(18, 18, 22, 0.86);
  backdrop-filter: blur(28px) saturate(140%);
  -webkit-backdrop-filter: blur(28px) saturate(140%);
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 14px 36px rgba(0, 0, 0, 0.56);
}

.toast-msg {
  min-width: 0;
}

.toast-action {
  border: none;
  border-radius: 999px;
  padding: 3px 10px;
  background: rgba(255, 255, 255, 0.12);
  color: #f5f5f7;
  font-size: 11.5px;
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background-color var(--duration-fast) var(--ease-out-expo);
}

.toast-action:hover {
  background: #f5f5f7;
  color: #0a0a0c;
}

.toast-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  background: rgba(244, 244, 245, 0.72);
}

.toast-success .toast-dot {
  background: var(--emerald);
}

.toast-warning .toast-dot {
  background: var(--amber);
}

.toast-error .toast-dot {
  background: var(--danger);
}
</style>
