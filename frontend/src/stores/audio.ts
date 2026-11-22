import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { audioUrl } from '@/api/client'
import type { Game } from '@/types'

const VOLUME_STORAGE_KEY = 'tsumugi:phonograph:volume'
const MUTE_STORAGE_KEY = 'tsumugi:phonograph:muted'
const FADE_DURATION_MS = 500

function loadStoredVolume(): number {
  try {
    const raw = window.localStorage.getItem(VOLUME_STORAGE_KEY)
    if (raw !== null) {
      const parsed = Number(raw)
      if (!Number.isNaN(parsed)) return Math.min(1, Math.max(0, parsed))
    }
  } catch {
    // ignore storage errors
  }
  return 0.62
}

function loadStoredMuted(): boolean {
  try {
    return window.localStorage.getItem(MUTE_STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

export const useAudioStore = defineStore('audio', () => {
  const currentGameId = ref<number | null>(null)
  const currentTitle = ref('')
  const currentBgmPath = ref('')
  const isPlaying = ref(false)
  const autoplayBlocked = ref(false)
  const currentTime = ref(0)
  const duration = ref(0)
  const volume = ref(loadStoredVolume())
  const muted = ref(loadStoredMuted())
  const loop = ref(true)

  let audioEl: HTMLAudioElement | null = null
  let fadeRaf: number | null = null
  let transitionToken = 0

  const progress = computed(() => {
    if (!duration.value || duration.value <= 0) return 0
    return Math.min(1, Math.max(0, currentTime.value / duration.value))
  })

  function ensureAudioElement(): HTMLAudioElement {
    if (!audioEl) {
      audioEl = new Audio()
      audioEl.loop = loop.value
      audioEl.preload = 'metadata'
      audioEl.volume = muted.value ? 0 : volume.value

      audioEl.addEventListener('timeupdate', () => {
        if (audioEl) currentTime.value = audioEl.currentTime || 0
      })
      audioEl.addEventListener('loadedmetadata', () => {
        if (audioEl && Number.isFinite(audioEl.duration)) {
          duration.value = audioEl.duration
        }
      })
      audioEl.addEventListener('durationchange', () => {
        if (audioEl && Number.isFinite(audioEl.duration)) {
          duration.value = audioEl.duration
        }
      })
      audioEl.addEventListener('play', () => {
        isPlaying.value = true
        autoplayBlocked.value = false
      })
      audioEl.addEventListener('pause', () => {
        isPlaying.value = false
      })
      audioEl.addEventListener('ended', () => {
        if (!loop.value) isPlaying.value = false
      })
      audioEl.addEventListener('error', () => {
        isPlaying.value = false
      })
    }
    return audioEl
  }

  function cancelFade() {
    if (fadeRaf !== null) {
      cancelAnimationFrame(fadeRaf)
      fadeRaf = null
    }
  }

  function animateVolume(from: number, to: number, ms: number): Promise<void> {
    cancelFade()
    const el = ensureAudioElement()
    const startVal = Math.min(1, Math.max(0, from))
    const endVal = Math.min(1, Math.max(0, to))
    if (ms <= 0 || Math.abs(endVal - startVal) < 0.005) {
      el.volume = endVal
      return Promise.resolve()
    }

    return new Promise((resolve) => {
      const started = performance.now()
      const step = (now: number) => {
        const t = Math.min(1, (now - started) / ms)
        // cubic-bezier ease-out 近似曲线，保证听觉衰减自然
        const eased = 1 - Math.pow(1 - t, 3)
        el.volume = Math.min(1, Math.max(0, startVal + (endVal - startVal) * eased))
        if (t < 1) {
          fadeRaf = requestAnimationFrame(step)
        } else {
          fadeRaf = null
          resolve()
        }
      }
      fadeRaf = requestAnimationFrame(step)
    })
  }

  function effectiveTargetVolume(): number {
    return muted.value ? 0 : volume.value
  }

  /**
   * 绑定当前焦点游戏原声（不强制自动播放时仅就绪待播；autoPlay=true 时执行 0.5s 淡出/淡入切换）
   */
  async function syncGameBgm(
    game: Game | null,
    options: { autoPlay?: boolean; cacheBust?: number } = {},
  ) {
    const token = ++transitionToken
    const bgmPath = (game?.media?.bgm_path || '').trim()

    // 若游戏无原声：若正在播放旧曲，则平滑淡出并停止
    if (!game || !bgmPath) {
      if (audioEl && !audioEl.paused) {
        await animateVolume(audioEl.volume, 0, FADE_DURATION_MS)
        if (token !== transitionToken) return
        audioEl.pause()
      }
      currentGameId.value = game?.id ?? null
      currentTitle.value = game?.title ?? ''
      currentBgmPath.value = ''
      currentTime.value = 0
      duration.value = 0
      isPlaying.value = false
      autoplayBlocked.value = false
      return
    }

    const isSameTrack = currentGameId.value === game.id && currentBgmPath.value === bgmPath
    const el = ensureAudioElement()

    if (isSameTrack) {
      if (options.autoPlay && el.paused) {
        await playWithFade(token)
      }
      return
    }

    // 切换不同游戏：先 0.5s 平滑淡出旧原声
    if (!el.paused) {
      await animateVolume(el.volume, 0, FADE_DURATION_MS)
      if (token !== transitionToken) return
      el.pause()
    }

    currentGameId.value = game.id
    currentTitle.value = game.title
    currentBgmPath.value = bgmPath
    currentTime.value = 0
    duration.value = 0
    autoplayBlocked.value = false

    el.loop = loop.value
    el.src = audioUrl(bgmPath, options.cacheBust)
    el.currentTime = 0

    if (options.autoPlay) {
      await playWithFade(token)
    } else {
      el.volume = effectiveTargetVolume()
    }
  }

  async function playWithFade(token?: number) {
    const myToken = token ?? ++transitionToken
    const el = ensureAudioElement()
    if (!currentBgmPath.value) return

    const target = effectiveTargetVolume()
    el.volume = 0
    try {
      await el.play()
      if (myToken !== transitionToken) return
      autoplayBlocked.value = false
      await animateVolume(0, target, FADE_DURATION_MS)
    } catch {
      // 浏览器拦截自动播放时静默回退为待点击状态，不抛出报错
      if (myToken !== transitionToken) return
      el.volume = target
      isPlaying.value = false
      autoplayBlocked.value = true
    }
  }

  async function togglePlayForGame(game: Game, cacheBust?: number) {
    const bgmPath = (game.media?.bgm_path || '').trim()
    if (!bgmPath) return

    const isSameTrack = currentGameId.value === game.id && currentBgmPath.value === bgmPath
    if (!isSameTrack) {
      await syncGameBgm(game, { autoPlay: true, cacheBust })
      return
    }

    const el = ensureAudioElement()
    if (el.paused) {
      await playWithFade()
    } else {
      const token = ++transitionToken
      await animateVolume(el.volume, 0, 260)
      if (token !== transitionToken) return
      el.pause()
      el.volume = effectiveTargetVolume()
    }
  }

  async function stopSmooth() {
    const token = ++transitionToken
    if (!audioEl || audioEl.paused) return
    await animateVolume(audioEl.volume, 0, FADE_DURATION_MS)
    if (token !== transitionToken) return
    audioEl.pause()
    audioEl.volume = effectiveTargetVolume()
  }

  function seekToRatio(ratio: number) {
    if (!audioEl || !duration.value) return
    const clamped = Math.min(1, Math.max(0, ratio))
    audioEl.currentTime = clamped * duration.value
    currentTime.value = audioEl.currentTime
  }

  function setVolume(next: number) {
    const clamped = Math.min(1, Math.max(0, next))
    volume.value = clamped
    if (clamped > 0 && muted.value) {
      muted.value = false
    }
    try {
      window.localStorage.setItem(VOLUME_STORAGE_KEY, String(clamped))
      window.localStorage.setItem(MUTE_STORAGE_KEY, muted.value ? '1' : '0')
    } catch {
      // ignore
    }
    if (audioEl) {
      cancelFade()
      audioEl.volume = effectiveTargetVolume()
    }
  }

  function toggleMute() {
    muted.value = !muted.value
    try {
      window.localStorage.setItem(MUTE_STORAGE_KEY, muted.value ? '1' : '0')
    } catch {
      // ignore
    }
    if (audioEl) {
      cancelFade()
      audioEl.volume = effectiveTargetVolume()
    }
  }

  return {
    currentGameId,
    currentTitle,
    currentBgmPath,
    isPlaying,
    autoplayBlocked,
    currentTime,
    duration,
    progress,
    volume,
    muted,
    loop,
    syncGameBgm,
    togglePlayForGame,
    stopSmooth,
    seekToRatio,
    setVolume,
    toggleMute,
  }
})
