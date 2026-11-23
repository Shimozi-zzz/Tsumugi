<script setup lang="ts">
import { computed } from 'vue'
import { resolveGameBgmPlayback, useAudioStore } from '@/stores/audio'
import { useLibraryStore } from '@/stores/library'
import type { Game } from '@/types'

const props = defineProps<{
  game: Game
}>()

const audio = useAudioStore()
const store = useLibraryStore()

const resolvedBgm = computed(() => resolveGameBgmPlayback(props.game, store.assetVersion))
const hasBgm = computed(() => Boolean(resolvedBgm.value))
const isRemoteBgm = computed(() => Boolean(resolvedBgm.value?.isRemote))
const isThisTrack = computed(() => audio.currentGameId === props.game.id && Boolean(audio.currentBgmPath))
const isPlayingThis = computed(() => isThisTrack.value && audio.isPlaying)
const displayProgress = computed(() => (isThisTrack.value ? audio.progress : 0))
const displayCurrent = computed(() => (isThisTrack.value ? audio.currentTime : 0))
const displayDuration = computed(() => (isThisTrack.value ? audio.duration : 0))

function formatTime(sec: number): string {
  if (!Number.isFinite(sec) || sec <= 0) return '00:00'
  const total = Math.floor(sec)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function handleToggle() {
  void audio.togglePlayForGame(props.game, store.assetVersion)
}

function handleSeek(ev: MouseEvent) {
  if (!isThisTrack.value || !audio.duration) {
    void audio.togglePlayForGame(props.game, store.assetVersion)
    return
  }
  const el = ev.currentTarget as HTMLElement
  const rect = el.getBoundingClientRect()
  const ratio = (ev.clientX - rect.left) / Math.max(rect.width, 1)
  audio.seekToRatio(ratio)
}

function handleVolumeInput(ev: Event) {
  const val = Number((ev.target as HTMLInputElement).value)
  audio.setVolume(val)
}
</script>

<template>
  <div v-if="hasBgm" class="phonograph-pill" :class="{ playing: isPlayingThis }">
    <!-- 微缩旋转唱片 -->
    <button
      type="button"
      class="vinyl-btn"
      :title="isPlayingThis ? '暂停原声' : '播放原声'"
      @click="handleToggle"
    >
      <span class="vinyl-disc" :class="{ spinning: isPlayingThis }">
        <span class="vinyl-groove" />
        <span class="vinyl-center" />
      </span>
      <span class="vinyl-overlay-icon">
        <svg v-if="isPlayingThis" viewBox="0 0 16 16" width="11" height="11" fill="currentColor">
          <rect x="3.5" y="3" width="3" height="10" rx="0.8" />
          <rect x="9.5" y="3" width="3" height="10" rx="0.8" />
        </svg>
        <svg v-else viewBox="0 0 16 16" width="11" height="11" fill="currentColor">
          <path d="M4.8 3.2v9.6L12.6 8 4.8 3.2z" />
        </svg>
      </span>
    </button>

    <!-- 轨道信息与可拖动细进度条 -->
    <div class="phono-center">
      <div class="phono-head">
        <span class="phono-label">
          {{
            isPlayingThis
              ? isRemoteBgm
                ? 'OST 在线播放'
                : 'OST 播放中'
              : audio.autoplayBlocked && isThisTrack
                ? '点击播放原声'
                : isRemoteBgm
                  ? '主题原声 · 在线'
                  : '主题原声'
          }}
        </span>
        <span class="phono-time tabular-nums">
          {{ formatTime(displayCurrent) }}
          <template v-if="displayDuration > 0"> / {{ formatTime(displayDuration) }}</template>
        </span>
      </div>
      <div class="phono-track" role="slider" aria-label="音频进度" @click="handleSeek">
        <div class="phono-track-fill" :style="{ width: `${(displayProgress * 100).toFixed(2)}%` }" />
      </div>
    </div>

    <!-- 静音与音量微调 -->
    <div class="phono-vol">
      <button
        type="button"
        class="vol-icon-btn"
        :title="audio.muted || audio.volume === 0 ? '取消静音' : '静音'"
        @click="audio.toggleMute()"
      >
        <svg
          v-if="audio.muted || audio.volume === 0"
          viewBox="0 0 20 20"
          width="14"
          height="14"
          fill="none"
          stroke="currentColor"
          stroke-width="1.65"
        >
          <path d="M3.5 8h3l4-3.5v11L6.5 12h-3V8z" />
          <path d="M13.5 7.5l3.5 5M17 7.5l-3.5 5" stroke-linecap="round" />
        </svg>
        <svg
          v-else
          viewBox="0 0 20 20"
          width="14"
          height="14"
          fill="none"
          stroke="currentColor"
          stroke-width="1.65"
        >
          <path d="M3.5 8h3l4-3.5v11L6.5 12h-3V8z" />
          <path d="M13.2 7.2a4.2 4.2 0 0 1 0 5.6M15.4 5.2a7 7 0 0 1 0 9.6" stroke-linecap="round" />
        </svg>
      </button>

      <input
        type="range"
        class="vol-slider"
        min="0"
        max="1"
        step="0.02"
        :value="audio.muted ? 0 : audio.volume"
        aria-label="原声音量"
        @input="handleVolumeInput"
      />
    </div>
  </div>
</template>

<style scoped>
.phonograph-pill {
  display: inline-flex;
  align-items: center;
  gap: 11px;
  padding: 7px 14px 7px 8px;
  border-radius: 999px;
  background: var(--bg-acrylic);
  backdrop-filter: var(--backdrop-acrylic);
  -webkit-backdrop-filter: var(--backdrop-acrylic);
  box-shadow:
    inset 0 1px 0 var(--highlight-top),
    0 16px 40px rgba(0, 0, 0, 0.56);
  max-width: 320px;
  transition: background-color var(--duration-base) var(--ease-out-expo);
}

.phonograph-pill:hover {
  background: rgba(20, 20, 24, 0.86);
}

.vinyl-btn {
  position: relative;
  width: 32px;
  height: 32px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.vinyl-disc {
  position: relative;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: conic-gradient(
    from 0deg,
    #1c1c20,
    #323238,
    #16161a,
    #2e2e34,
    #1c1c20
  );
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.22);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: vinyl-spin 5.5s linear infinite;
  animation-play-state: paused;
}

.vinyl-disc.spinning {
  animation-play-state: running;
}

.vinyl-groove {
  position: absolute;
  inset: 5px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.14);
}

.vinyl-center {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #f5f5f7;
  box-shadow: 0 0 0 2px #0a0a0c;
}

.vinyl-overlay-icon {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: rgba(10, 10, 12, 0.58);
  color: #f5f5f7;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity var(--duration-fast) var(--ease-out-expo);
}

.vinyl-btn:hover .vinyl-overlay-icon,
.phonograph-pill:not(.playing) .vinyl-overlay-icon {
  opacity: 1;
}

.phono-center {
  flex: 1;
  min-width: 112px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.phono-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.phono-label {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
}

.phono-time {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
  white-space: nowrap;
}

.phono-track {
  position: relative;
  height: 3px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.12);
  cursor: pointer;
  overflow: hidden;
}

.phono-track-fill {
  height: 100%;
  border-radius: 999px;
  background: #f5f5f7;
  transition: width 0.16s linear;
}

.phono-vol {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.vol-icon-btn {
  width: 24px;
  height: 24px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: color var(--duration-fast) var(--ease-out-expo);
}

.vol-icon-btn:hover {
  color: var(--text-primary);
}

.vol-slider {
  width: 50px;
  height: 3px;
  appearance: none;
  -webkit-appearance: none;
  background: rgba(255, 255, 255, 0.14);
  border-radius: 999px;
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
  cursor: pointer;
}

@keyframes vinyl-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
