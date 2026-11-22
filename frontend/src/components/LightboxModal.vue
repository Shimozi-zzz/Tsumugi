<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { rawImageUrl } from '@/api/client'
import type { ScreenshotItem } from '@/types'

const props = defineProps<{
  items: ScreenshotItem[]
  initialIndex: number
}>()

const emit = defineEmits<{
  close: []
}>()

const currentIndex = ref(props.initialIndex)
const zoomed = ref(false)

const currentItem = computed(() => props.items[currentIndex.value] || null)

function prev() {
  if (props.items.length === 0) return
  currentIndex.value = (currentIndex.value - 1 + props.items.length) % props.items.length
  zoomed.value = false
}

function next() {
  if (props.items.length === 0) return
  currentIndex.value = (currentIndex.value + 1) % props.items.length
  zoomed.value = false
}

function onKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
  else if (e.key === 'ArrowLeft') prev()
  else if (e.key === 'ArrowRight') next()
}

onMounted(() => window.addEventListener('keydown', onKeyDown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeyDown))
</script>

<template>
  <div class="lightbox-backdrop" @click.self="emit('close')">
    <div class="lightbox-topbar">
      <div class="lb-meta">
        <span class="lb-counter tabular-nums">{{ currentIndex + 1 }} / {{ items.length }}</span>
        <span class="lb-name">{{ currentItem?.name }}</span>
      </div>
      <div class="lb-actions">
        <button class="btn btn-sm" @click="zoomed = !zoomed">
          {{ zoomed ? '适应窗口' : '放大原图' }}
        </button>
        <button class="btn btn-sm" @click="emit('close')">关闭</button>
      </div>
    </div>

    <button v-if="items.length > 1" class="lb-nav lb-prev" aria-label="上一张" @click="prev">
      <svg viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6">
        <path d="M12.5 15L7.5 10l5-5" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>
    <button v-if="items.length > 1" class="lb-nav lb-next" aria-label="下一张" @click="next">
      <svg viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6">
        <path d="M7.5 5l5 5-5 5" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>

    <div class="lb-stage" :class="{ zoomed }" @click="zoomed = !zoomed">
      <img
        v-if="currentItem"
        :src="rawImageUrl(currentItem.path)"
        :alt="currentItem.name"
        class="lb-img"
      />
    </div>
  </div>
</template>

<style scoped>
.lightbox-backdrop {
  position: fixed;
  inset: 0;
  z-index: 120;
  background: rgba(6, 6, 8, 0.94);
  backdrop-filter: blur(22px);
  -webkit-backdrop-filter: blur(22px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.lightbox-topbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  padding: 18px 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: linear-gradient(180deg, rgba(10, 10, 12, 0.8), transparent);
  z-index: 5;
}

.lb-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}

.lb-counter {
  font-family: var(--font-mono);
  padding: 3px 9px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.09);
  color: var(--text-primary);
}

.lb-name {
  color: var(--text-secondary);
}

.lb-actions {
  display: flex;
  gap: 8px;
}

.lb-stage {
  max-width: 90vw;
  max-height: 84vh;
  overflow: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: zoom-in;
}

.lb-stage.zoomed {
  max-width: 98vw;
  max-height: 92vh;
  cursor: zoom-out;
}

.lb-img {
  max-width: 100%;
  max-height: 84vh;
  border-radius: 10px;
  box-shadow: 0 28px 80px rgba(0, 0, 0, 0.78);
  transition: transform 0.28s var(--ease-out-expo);
}

.lb-stage.zoomed .lb-img {
  max-width: none;
  max-height: none;
}

.lb-nav {
  position: fixed;
  top: 50%;
  transform: translateY(-50%);
  width: 44px;
  height: 68px;
  border-radius: 12px;
  border: none;
  background: rgba(255, 255, 255, 0.06);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 5;
  transition:
    background-color var(--duration-fast) var(--ease-out-expo),
    color var(--duration-fast) var(--ease-out-expo);
}

.lb-nav:hover {
  background: rgba(255, 255, 255, 0.16);
  color: #ffffff;
}

.lb-prev {
  left: 24px;
}

.lb-next {
  right: 24px;
}
</style>
