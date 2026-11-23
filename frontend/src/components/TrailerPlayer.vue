<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Hls from 'hls.js'
import { assetUrl } from '@/api/client'
import { PAUSE_MEDIA_EVENT, useAudioStore } from '@/stores/audio'

const props = defineProps<{
  src: string
  poster?: string
  blurred?: boolean
}>()

const audioStore = useAudioStore()
const videoRef = ref<HTMLVideoElement | null>(null)
const errorMsg = ref('')
const isLoading = ref(false)
let hlsInstance: Hls | null = null

const resolvedSrc = computed(() => assetUrl(props.src))
const isHlsStream = computed(() => resolvedSrc.value.toLowerCase().includes('.m3u8'))

function cleanupHls() {
  if (hlsInstance) {
    hlsInstance.destroy()
    hlsInstance = null
  }
}

function setupVideo() {
  cleanupHls()
  errorMsg.value = ''
  const video = videoRef.value
  const url = resolvedSrc.value
  if (!video || !url) return

  isLoading.value = true

  if (isHlsStream.value) {
    if (Hls.isSupported()) {
      const hls = new Hls({
        enableWorker: true,
        lowLatencyMode: false,
      })
      hlsInstance = hls
      hls.loadSource(url)
      hls.attachMedia(video)
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        isLoading.value = false
      })
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (data.fatal) {
          isLoading.value = false
          errorMsg.value = 'HLS 宣传片流加载失败（可能需要配置代理或链接已过期）'
          cleanupHls()
        }
      })
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = url
      isLoading.value = false
    } else {
      isLoading.value = false
      errorMsg.value = '当前浏览器内核不支持 HLS (.m3u8) 流播放'
    }
  } else {
    video.src = url
    isLoading.value = false
  }
}

function handleNativeError() {
  isLoading.value = false
  if (!errorMsg.value) {
    errorMsg.value = '视频资源暂时无法加载，请检查本地文件或网络连接'
  }
}

function handleGlobalPauseMedia() {
  const video = videoRef.value
  if (video && !video.paused) {
    video.pause()
  }
}

function handlePlay() {
  void audioStore.stopSmooth()
}

onMounted(() => {
  setupVideo()
  window.addEventListener(PAUSE_MEDIA_EVENT, handleGlobalPauseMedia)
})
watch(() => props.src, setupVideo)
onBeforeUnmount(() => {
  window.removeEventListener(PAUSE_MEDIA_EVENT, handleGlobalPauseMedia)
  cleanupHls()
})
</script>

<template>
  <div class="trailer-shell">
    <div class="trailer-header">
      <div class="trailer-badge">
        <span class="badge-dot" />
        <span>{{ isHlsStream ? 'OFFICIAL TRAILER · HLS' : 'OFFICIAL TRAILER' }}</span>
      </div>
      <a
        v-if="resolvedSrc.startsWith('http')"
        :href="resolvedSrc"
        target="_blank"
        rel="noopener"
        class="ext-link"
      >
        源链接 ↗
      </a>
    </div>

    <div class="video-stage">
      <video
        ref="videoRef"
        class="video-el"
        :class="{ 'privacy-blur-img': blurred }"
        :poster="poster || undefined"
        controls
        playsinline
        preload="metadata"
        @play="handlePlay"
        @error="handleNativeError"
      />
      <div v-if="isLoading" class="video-overlay">
        <div class="spinner" />
        <span>正在缓冲宣传片…</span>
      </div>
      <div v-if="errorMsg" class="video-overlay error">
        <span>{{ errorMsg }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.trailer-shell {
  border-radius: var(--radius-lg);
  overflow: hidden;
  background: var(--bg-surface-subtle);
  box-shadow: inset 0 1px 0 var(--divider-subtle);
}

.trailer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px;
  border-bottom: 1px solid var(--divider-subtle);
  font-size: 11px;
  letter-spacing: 0.08em;
  color: var(--text-muted);
}

.trailer-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-mono);
}

.badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgba(244, 244, 245, 0.72);
}

.ext-link {
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 11.5px;
  transition: color var(--duration-fast) var(--ease-out-expo);
}

.ext-link:hover {
  color: var(--text-primary);
}

.video-stage {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #060608;
  overflow: hidden;
}

.video-el {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.video-overlay {
  position: absolute;
  inset: 0;
  background: rgba(10, 10, 12, 0.76);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: 13px;
  color: var(--text-secondary);
  pointer-events: none;
}

.video-overlay.error {
  color: var(--danger-text);
  padding: 20px;
  text-align: center;
}

.spinner {
  width: 22px;
  height: 22px;
  border: 2px solid rgba(255, 255, 255, 0.14);
  border-top-color: var(--text-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
