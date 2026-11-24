<script setup lang="ts">
type ResizeEdge =
  | 'left'
  | 'right'
  | 'top'
  | 'bottom'
  | 'top-left'
  | 'top-right'
  | 'bottom-left'
  | 'bottom-right'

interface ResizeHandleDef {
  edge: ResizeEdge
  className: string
}

defineProps<{
  visible: boolean
}>()

const RESIZE_HANDLES: ResizeHandleDef[] = [
  { edge: 'top', className: 'edge-top' },
  { edge: 'bottom', className: 'edge-bottom' },
  { edge: 'left', className: 'edge-left' },
  { edge: 'right', className: 'edge-right' },
  { edge: 'top-left', className: 'corner-top-left' },
  { edge: 'top-right', className: 'corner-top-right' },
  { edge: 'bottom-left', className: 'corner-bottom-left' },
  { edge: 'bottom-right', className: 'corner-bottom-right' },
]

function onHandleMouseDown(edge: ResizeEdge, e: MouseEvent) {
  if (e.button !== 0) return
  try {
    void window.pywebview?.api?.start_resize?.(edge)
  } catch {
    // ignore transient bridge error
  }
}
</script>

<template>
  <!-- 仅在桌面端且 normal 常规态挂载 8 方向隐形边缘拉伸热区 -->
  <template v-if="visible">
    <div
      v-for="handle in RESIZE_HANDLES"
      :key="handle.edge"
      class="win-resize-handle"
      :class="handle.className"
      data-no-drag
      aria-hidden="true"
      @mousedown.prevent.stop="onHandleMouseDown(handle.edge, $event)"
    />
  </template>
</template>

<style scoped>
.win-resize-handle {
  position: fixed;
  z-index: 10000;
  background: transparent;
  user-select: none;
  -webkit-user-select: none;
  pointer-events: auto;
}

/* 四条边（5px 厚度；顶部 0~4px 不干扰 4~36px 拖拽条并避开右上角窗口按钮） */
.edge-top {
  top: 0;
  left: 10px;
  right: 152px;
  height: 4px;
  cursor: ns-resize;
}

.edge-bottom {
  bottom: 0;
  left: 10px;
  right: 10px;
  height: 5px;
  cursor: ns-resize;
}

.edge-left {
  top: 10px;
  bottom: 10px;
  left: 0;
  width: 5px;
  cursor: ew-resize;
}

.edge-right {
  top: 10px;
  bottom: 10px;
  right: 0;
  width: 5px;
  cursor: ew-resize;
}

/* 四个角（10px × 10px，z-index: 10001 优先于四条边） */
.corner-top-left,
.corner-top-right,
.corner-bottom-left,
.corner-bottom-right {
  z-index: 10001;
  width: 10px;
  height: 10px;
}

.corner-top-left {
  top: 0;
  left: 0;
  cursor: nwse-resize;
}

.corner-top-right {
  top: 0;
  right: 0;
  cursor: nesw-resize;
}

.corner-bottom-left {
  bottom: 0;
  left: 0;
  cursor: nesw-resize;
}

.corner-bottom-right {
  bottom: 0;
  right: 0;
  cursor: nwse-resize;
}
</style>
