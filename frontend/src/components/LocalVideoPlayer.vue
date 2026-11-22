<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Hls from 'hls.js'
import { videoUrl } from '@/api/client'
import { useAudioStore } from '@/stores/audio'

const props = defineProps<{
  src: string
  poster?: string
  blurred?: boolean
  cacheBust?: number
}>()

const audioStore = useAudioStore()

const stageRef = ref<HTMLElement | null>(null)
const videoRef = ref<HTMLVideoElement | null>(null)
const progressTrackRef = ref<HTMLElement | null>(null)

const isPlaying = ref(false)
const isLoading = ref(false)
const hasStarted = ref(false)
const errorMsg = ref('')
const currentTime = ref(0)
const duration = ref(0)
const bufferedRatio = ref(0)
const volume = ref(0.82)
const muted = ref(false)
const isFullscreen = ref(false)
const controlsVisible = ref(true)
const isScrubbing = ref(false)

let hlsInstance: Hls | null = null
let hideTimer: number | null = null

const isExternal = computed(() => /^https?:\/\//i.test((props.src || '').trim()))
const resolvedSrc = computed(() => {
  const raw = (props.src || '').trim()
  if (!raw) return ''
  return isExternal.value ? raw : videoUrl(raw, props.cacheBust)
})
const isHlsStream = computed(() => resolvedSrc.value.toLowerCase().includes('.m3u8'))

const progressRatio = computed(() => {
  if (!duration.value || duration.value <= 0) return 0
  return Math.min(1, Math.max(0, currentTime.value / duration.value))
})

function formatTime(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return '00:00'
  const total = Math.floor(sec)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function clearHideTimer() {
  if (hideTimer !== null) {
    clearTimeout(hideTimer)
    hideTimer = null
  }
}

function scheduleHideControls() {
  clearHideTimer()
  if (!isPlaying.value || isScrubbing.value) {
    controlsVisible.value = true
    return
  }
  hideTimer = window.setTimeout(() => {
    if (isPlaying.value && !isScrubbing.value) {
      controlsVisible.value = false
    }
  }, 2000)
}

function revealControls() {
  controlsVisible.value = true
  scheduleHideControls()
}

function handleMouseLeave() {
  if (isPlaying.value && !isScrubbing.value) {
    clearHideTimer()
    controlsVisible.value = false
  }
}

function cleanupHls() {
  if (hlsInstance) {
    hlsInstance.destroy()
    hlsInstance = null
  }
}

function setupVideo() {
  cleanupHls()
  clearHideTimer()
  errorMsg.value = ''
  isPlaying.value = false
  hasStarted.value = false
  currentTime.value = 0
  duration.value = 0
  bufferedRatio.value = 0
  controlsVisible.value = true

  const video = videoRef.value
  const url = resolvedSrc.value
  if (!video || !url) return

  video.volume = volume.value
  video.muted = muted.value

  if (isHlsStream.value) {
    isLoading.value = true
    if (Hls.isSupported()) {
      const hls = new Hls({ enableWorker: true, lowLatencyMode: false })
      hlsInstance = hls
      hls.loadSource(url)
      hls.attachMedia(video)
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        isLoading.value = false
      })
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (data.fatal) {
          isLoading.value = false
          errorMsg.value = '宣传片流加载失败'
          cleanupHls()
        }
      })
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = url
      isLoading.value = false
    } else {
      isLoading.value = false
      errorMsg.value = '当前浏览器不支持 HLS 流播放'
    }
  } else {
    video.src = url
    isLoading.value = false
  }
}

function togglePlay() {
  const video = videoRef.value
  if (!video || errorMsg.value) return
  if (video.paused || video.ended) {
    void video.play().catch(() => {
      // ignore autoplay rejection
    })
  } else {
    video.pause()
  }
}

function onPlay() {
  isPlaying.value = true
  hasStarted.value = true
  // 播放宣传片时自动平滑暂停全局留声机 BGM
  void audioStore.stopSmooth()
  scheduleHideControls()
}

function onPause() {
  isPlaying.value = false
  clearHideTimer()
  controlsVisible.value = true
}

function onEnded() {
  isPlaying.value = false
  clearHideTimer()
  controlsVisible.value = true
}

function onTimeUpdate() {
  const video = videoRef.value
  if (!video || isScrubbing.value) return
  currentTime.value = video.currentTime || 0
  updateBuffered()
}

function onLoadedMetadata() {
  const video = videoRef.value
  if (!video) return
  if (Number.isFinite(video.duration)) {
    duration.value = video.duration
  }
  updateBuffered()
}

function updateBuffered() {
  const video = videoRef.value
  if (!video || !duration.value || video.buffered.length === 0) return
  try {
    const end = video.buffered.end(video.buffered.length - 1)
    bufferedRatio.value = Math.min(1, Math.max(0, end / duration.value))
  } catch {
    // ignore
  }
}

function onWaiting() {
  if (hasStarted.value) isLoading.value = true
}

function onCanPlay() {
  isLoading.value = false
}

function onError() {
  isLoading.value = false
  if (!errorMsg.value) {
    errorMsg.value = '视频资源暂时无法加载'
  }
}

function seekByClientX(clientX: number) {
  const track = progressTrackRef.value
  const video = videoRef.value
  if (!track || !video || !duration.value) return
  const rect = track.getBoundingClientRect()
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / Math.max(rect.width, 1)))
  const target = ratio * duration.value
  currentTime.value = target
  video.currentTime = target
}

function onScrubPointerDown(ev: PointerEvent) {
  isScrubbing.value = true
  clearHideTimer()
  seekByClientX(ev.clientX)
  window.addEventListener('pointermove', onScrubPointerMove)
  window.addEventListener('pointerup', onScrubPointerUp)
}

function onScrubPointerMove(ev: PointerEvent) {
  if (!isScrubbing.value) return
  seekByClientX(ev.clientX)
}

function onScrubPointerUp(ev: PointerEvent) {
  if (!isScrubbing.value) return
  seekByClientX(ev.clientX)
  isScrubbing.value = false
  window.removeEventListener('pointermove', onScrubPointerMove)
  window.removeEventListener('pointerup', onScrubPointerUp)
  scheduleHideControls()
}

function toggleMute() {
  const video = videoRef.value
  muted.value = !muted.value
  if (video) {
    video.muted = muted.value
    if (!muted.value && volume.value === 0) {
      volume.value = 0.6
      video.volume = 0.6
    }
  }
}

function onVolumeInput(ev: Event) {
  const val = Number((ev.target as HTMLInputElement).value)
  volume.value = val
  muted.value = val === 0
  if (videoRef.value) {
    videoRef.value.volume = val
    videoRef.value.muted = muted.value
  }
}

async function toggleFullscreen() {
  const el = stageRef.value
  if (!el) return
  try {
    if (!document.fullscreenElement) {
      await el.requestFullscreen()
    } else {
      await document.exitFullscreen()
    }
  } catch {
    // ignore fullscreen error
  }
}

function syncFullscreenState() {
  isFullscreen.value = document.fullscreenElement === stageRef.value
}

onMounted(() => {
  setupVideo()
  document.addEventListener('fullscreenchange', syncFullscreenState)
})

watch([() => props.src, () => props.cacheBust], setupVideo)

onBeforeUnmount(() => {
  cleanupHls()
  clearHideTimer()
  window.removeEventListener('pointermove', onScrubPointerMove)
  window.removeEventListener('pointerup', onScrubPointerUp)
  document.removeEventListener('fullscreenchange', syncFullscreenState)
})
</script>

<template>
  <div class="local-player-shell">
    <div
      ref="stageRef"
      class="video-stage"
      :class="{ 'controls-hidden': isPlaying && !controlsVisible }"
      @mousemove="revealControls"
      @mouseleave="handleMouseLeave"
    >
      <video
        ref="videoRef"
        class="video-el"
        :class="{ 'privacy-blur-img': blurred }"
        :poster="poster || undefined"
        playsinline
        preload="metadata"
        @click="togglePlay"
        @dblclick="toggleFullscreen"
        @play="onPlay"
        @pause="onPause"
        @ended="onEnded"
        @timeupdate="onTimeUpdate"
        @loadedmetadata="onLoadedMetadata"
        @progress="updateBuffered"
        @waiting="onWaiting"
        @canplay="onCanPlay"
        @error="onError"
      />

      <!-- 暂停/初始状态居中毛玻璃播放按钮 -->
      <Transition name="fade">
        <button
          v-if="!isPlaying && !errorMsg"
          type="button"
          class="center-play-btn"
          aria-label="播放宣传片"
          @click="togglePlay"
        >
          <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
            <path d="M8 5.2v13.6L19 12 8 5.2z" />
          </svg>
        </button>
      </Transition>

      <!-- 缓冲态 -->
      <div v-if="isLoading && !errorMsg" class="video-overlay">
        <div class="spinner" />
      </div>

      <!-- 错误态 -->
      <div v-if="errorMsg" class="video-overlay error">
        <span>{{ errorMsg }}</span>
      </div>

      <!-- 底部极简亚克力控制条 -->
      <div
        v-if="!errorMsg"
        class="control-dock"
        :class="{ visible: controlsVisible || !isPlaying }"
        @click.stop
      >
        <!-- 细进度条（点击 + 拖拽） -->
        <div
          ref="progressTrackRef"
          class="scrub-hit"
          @pointerdown="onScrubPointerDown"
        >
          <div class="scrub-track">
            <div class="scrub-buffer" :style="{ width: `${bufferedRatio * 100}%` }" />
            <div class="scrub-fill" :style="{ width: `${progressRatio * 100}%` }" />
            <div class="scrub-thumb" :style="{ left: `${progressRatio * 100}%` }" />
          </div>
        </div>

        <div class="control-row">
          <div class="ctrl-left">
            <button
              type="button"
              class="ctrl-icon-btn"
              :aria-label="isPlaying ? '暂停' : '播放'"
              @click="togglePlay"
            >
              <svg v-if="isPlaying" viewBox="0 0 20 20" width="15" height="15" fill="currentColor">
                <rect x="4.5" y="3.5" width="3.5" height="13" rx="1" />
                <rect x="12" y="3.5" width="3.5" height="13" rx="1" />
              </svg>
              <svg v-else viewBox="0 0 20 20" width="15" height="15" fill="currentColor">
                <path d="M6 4.2v11.6L16 10 6 4.2z" />
              </svg>
            </button>

            <span class="time-readout tabular-nums">
              {{ formatTime(currentTime) }} / {{ formatTime(duration) }}
            </span>
          </div>

          <div class="ctrl-right">
            <div class="volume-group">
              <button
                type="button"
                class="ctrl-icon-btn"
                :aria-label="muted ? '取消静音' : '静音'"
                @click="toggleMute"
              >
                <svg v-if="muted || volume === 0" viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6">
                  <path d="M9.5 5L5.5 8H3v4h2.5l4 3V5z" stroke-linejoin="round" />
                  <path d="M13 7.5l4 5M17 7.5l-4 5" stroke-linecap="round" />
                </svg>
                <svg v-else viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6">
                  <path d="M9.5 5L5.5 8H3v4h2.5l4 3V5z" stroke-linejoin="round" />
                  <path d="M13 7.3a4 4 0 0 1 0 5.4M15.2 5.2a7 7 0 0 1 0 9.6" stroke-linecap="round" />
                </svg>
              </button>
              <input
                type="range"
                min="0"
                max="1"
                step="0.02"
                :value="muted ? 0 : volume"
                class="vol-slider"
                aria-label="音量"
                @input="onVolumeInput"
              />
            </div>

            <button
              type="button"
              class="ctrl-icon-btn"
              :aria-label="isFullscreen ? '退出全屏' : '全屏'"
              @click="toggleFullscreen"
            >
              <svg v-if="isFullscreen" viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6">
                <path d="M7.5 3.5v4h-4M12.5 3.5v4h4M7.5 16.5v-4h-4M12.5 16.5v-4h4" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
              <svg v-else viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6">
                <path d="M3.5 7.5v-4h4M16.5 7.5v-4h-4M3.5 12.5v4h4M16.5 12.5v4h-4" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.local-player-shell {
  border-radius: var(--radius-lg);
  overflow: hidden;
  background: #060608;
  box-shadow: inset 0 1px 0 var(--divider-subtle);
}

.video-stage {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #060608;
  overflow: hidden;
  user-select: none;
}

.video-stage.controls-hidden {
  cursor: none;
}

.video-el {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
  cursor: pointer;
}

.video-stage.controls-hidden .video-el {
  cursor: none;
}

.center-play-btn {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 62px;
  height: 62px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: rgba(16, 16, 20, 0.56);
  backdrop-filter: blur(18px) saturate(140%);
  -webkit-backdrop-filter: blur(18px) saturate(140%);
  color: #f5f5f7;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding-left: 3px;
  box-shadow: 0 14px 36px rgba(0, 0, 0, 0.52);
  transition:
    transform 200ms var(--ease-out-expo),
    background-color 200ms var(--ease-out-expo);
}

.center-play-btn:hover {
  transform: translate(-50%, -50%) scale(1.06);
  background: rgba(245, 245, 247, 0.92);
  color: #0a0a0c;
}

.video-overlay {
  position: absolute;
  inset: 0;
  background: rgba(8, 8, 10, 0.54);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--text-secondary);
  pointer-events: none;
}

.video-overlay.error {
  color: var(--danger-text);
  padding: 20px;
}

.spinner {
  width: 24px;
  height: 24px;
  border: 2px solid rgba(255, 255, 255, 0.14);
  border-top-color: #f5f5f7;
  border-radius: 50%;
  animation: lvp-spin 0.8s linear infinite;
}

@keyframes lvp-spin {
  to {
    transform: rotate(360deg);
  }
}

/* 底部极简亚克力控制条 */
.control-dock {
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: 12px;
  padding: 8px 12px 9px;
  border-radius: 12px;
  background: rgba(12, 12, 16, 0.72);
  backdrop-filter: blur(22px) saturate(140%);
  -webkit-backdrop-filter: blur(22px) saturate(140%);
  border: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  flex-direction: column;
  gap: 6px;
  opacity: 0;
  transform: translateY(6px);
  pointer-events: none;
  transition:
    opacity 200ms ease-out,
    transform 200ms var(--ease-out-expo);
}

.control-dock.visible {
  opacity: 1;
  transform: translateY(0);
  pointer-events: auto;
}

.scrub-hit {
  padding: 5px 0;
  cursor: pointer;
}

.scrub-track {
  position: relative;
  height: 3px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  transition: height 140ms ease;
}

.scrub-hit:hover .scrub-track {
  height: 5px;
}

.scrub-buffer {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.24);
}

.scrub-fill {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: 999px;
  background: #f5f5f7;
}

.scrub-thumb {
  position: absolute;
  top: 50%;
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: #f5f5f7;
  transform: translate(-50%, -50%) scale(0);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.5);
  transition: transform 140ms var(--ease-out-expo);
}

.scrub-hit:hover .scrub-thumb {
  transform: translate(-50%, -50%) scale(1);
}

.control-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.ctrl-left,
.ctrl-right {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.ctrl-icon-btn {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: rgba(245, 245, 247, 0.88);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition:
    background-color 150ms ease,
    color 150ms ease;
}

.ctrl-icon-btn:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

.time-readout {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: rgba(245, 245, 247, 0.78);
}

.volume-group {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.vol-slider {
  appearance: none;
  -webkit-appearance: none;
  width: 68px;
  height: 3px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.2);
  outline: none;
  cursor: pointer;
}

.vol-slider::-webkit-slider-thumb {
  appearance: none;
  -webkit-appearance: none;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #f5f5f7;
}
</style>
