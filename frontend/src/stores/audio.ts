import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { audioUrl, musicPreviewUrl } from '@/api/client'
import type { Game } from '@/types'

const VOLUME_STORAGE_KEY = 'tsumugi:phonograph:volume'
const MUTE_STORAGE_KEY = 'tsumugi:phonograph:muted'
const FADE_DURATION_MS = 500
const DEFAULT_PAUSE_FADE_MS = 250
const FADE_TICK_MS = 16
const DIRECT_AUDIO_URL_RE = /\.(?:m4a|mp3|ogg|wav|flac|webm|opus)(?:[?#].*)?$/i

export const PAUSE_MEDIA_EVENT = 'tsumugi:pause-media'

export interface PauseAllMediaOptions {
  fadeOutMs?: number
}

function isHttpUrl(raw?: string | null): boolean {
  return /^https?:\/\//i.test((raw || '').trim())
}

/**
 * 统一主题曲 OP 播放优先级：
 * 1. 存在本地缓存文件（非 http/https 路径）→ 始终优先本地播放
 * 2. 无本地文件、但存在在线链接 → 直链直接播放，Bilibili/YouTube 网页链接走后端试听流代理
 */
export function resolveGameBgmPlayback(
  game: Game | null | undefined,
  cacheBust?: number,
): { key: string; url: string; isRemote: boolean } | null {
  const m = game?.media
  if (!m) return null
  const rawPath = (m.bgm_path || '').trim()
  const rawRemote = (m.bgm_remote_url || '').trim()

  if (rawPath && !isHttpUrl(rawPath)) {
    return {
      key: `local:${rawPath}`,
      url: audioUrl(rawPath, cacheBust),
      isRemote: false,
    }
  }

  const remoteUrl = isHttpUrl(rawPath) ? rawPath : isHttpUrl(rawRemote) ? rawRemote : ''
  if (!remoteUrl) return null

  const playUrl = DIRECT_AUDIO_URL_RE.test(remoteUrl) ? remoteUrl : musicPreviewUrl(remoteUrl)
  return {
    key: `remote:${remoteUrl}`,
    url: playUrl,
    isRemote: true,
  }
}

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
  const autoplaySuppressed = ref(false)
  const currentTime = ref(0)
  const duration = ref(0)
  const volume = ref(loadStoredVolume())
  const muted = ref(loadStoredMuted())
  const loop = ref(true)

  let audioEl: HTMLAudioElement | null = null
  let fadeTimer: number | null = null
  let fadeResolver: (() => void) | null = null
  let fadeOutSnapshotVolume: number | null = null
  let isFadingOut = false
  let playbackIntent: 'play' | 'pause' = 'pause'
  let transitionToken = 0

  const progress = computed(() => {
    if (!duration.value || duration.value <= 0) return 0
    return Math.min(1, Math.max(0, currentTime.value / duration.value))
  })

  function setAutoplaySuppressed(suppressed: boolean) {
    autoplaySuppressed.value = Boolean(suppressed)
  }

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
        if (playbackIntent === 'play' && !isFadingOut) {
          isPlaying.value = true
          autoplayBlocked.value = false
        }
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
    if (fadeTimer !== null) {
      clearInterval(fadeTimer)
      fadeTimer = null
    }
    if (fadeResolver) {
      const resolve = fadeResolver
      fadeResolver = null
      resolve()
    }
  }

  function animateVolume(
    from: number,
    to: number,
    ms: number,
    easing: 'linear' | 'ease-out',
    expectedToken: number,
  ): Promise<void> {
    cancelFade()
    const el = ensureAudioElement()
    const startVal = Math.min(1, Math.max(0, from))
    const endVal = Math.min(1, Math.max(0, to))
    if (ms <= 0 || Math.abs(endVal - startVal) < 0.005) {
      if (expectedToken === transitionToken) {
        el.volume = endVal
      }
      return Promise.resolve()
    }

    // 使用 setInterval + performance.now 而非 rAF，避免游戏全屏抢焦导致淡出回调被节流挂起
    return new Promise((resolve) => {
      fadeResolver = resolve
      const started = performance.now()
      fadeTimer = window.setInterval(() => {
        if (expectedToken !== transitionToken) {
          cancelFade()
          return
        }
        const t = Math.min(1, (performance.now() - started) / ms)
        const factor = easing === 'linear' ? t : 1 - Math.pow(1 - t, 3)
        el.volume = Math.min(1, Math.max(0, startVal + (endVal - startVal) * factor))
        if (t >= 1) {
          el.volume = endVal
          cancelFade()
        }
      }, FADE_TICK_MS)
    })
  }

  function effectiveTargetVolume(): number {
    return muted.value ? 0 : volume.value
  }

  function getPlaybackIntent(): 'play' | 'pause' {
    return playbackIntent
  }

  /**
   * 防竞态平滑淡出暂停全局 BGM / OP：
   * - 记录暂停前的目标音量 prevVolume，在 fadeOutMs 内线性降到 0 后 pause()；
   * - 暂停完成后立即将 audio.volume 还原为 prevVolume，避免下次手动播放无声；
   * - 若淡出中途被手动播放打断，transitionToken / playbackIntent 会立即中止旧回调。
   */
  async function pauseBgmSmooth(fadeOutMs = DEFAULT_PAUSE_FADE_MS): Promise<void> {
    const token = ++transitionToken
    playbackIntent = 'pause'
    cancelFade()

    if (!audioEl) {
      isFadingOut = false
      fadeOutSnapshotVolume = null
      isPlaying.value = false
      return
    }

    const el = audioEl
    const prevVolume =
      fadeOutSnapshotVolume !== null ? fadeOutSnapshotVolume : effectiveTargetVolume()

    if (el.paused) {
      isFadingOut = false
      fadeOutSnapshotVolume = null
      el.volume = prevVolume
      isPlaying.value = false
      return
    }

    fadeOutSnapshotVolume = prevVolume
    isFadingOut = true
    isPlaying.value = false

    const ms = Math.max(0, Number.isFinite(fadeOutMs) ? fadeOutMs : DEFAULT_PAUSE_FADE_MS)
    if (ms > 0 && el.volume > 0.005) {
      await animateVolume(el.volume, 0, ms, 'linear', token)
    }

    // 若淡出期间用户已手动点击播放，绝不强行暂停或改写音量
    if (token !== transitionToken || getPlaybackIntent() !== 'pause') {
      return
    }

    const restoreVolume = fadeOutSnapshotVolume ?? prevVolume
    el.pause()
    el.volume = Math.min(1, Math.max(0, restoreVolume))
    isFadingOut = false
    fadeOutSnapshotVolume = null
    isPlaying.value = false
  }

  /**
   * 全局统一暂停所有媒体（启动游戏时零延迟调用）：
   * 1. 同步派发全局事件 tsumugi:pause-media，立即暂停所有独立 <video> / PV / 试听音频 / 内嵌播放器；
   * 2. 对全局 BGM / OP 执行线性淡出暂停并自动还原目标音量。
   */
  async function pauseAllMedia(options: PauseAllMediaOptions = {}): Promise<void> {
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent(PAUSE_MEDIA_EVENT))
    }
    const fadeOutMs = options.fadeOutMs ?? DEFAULT_PAUSE_FADE_MS
    await pauseBgmSmooth(fadeOutMs)
  }

  /**
   * 绑定当前焦点游戏原声（不强制自动播放时仅就绪待播；autoPlay=true 时执行平滑切换）。
   * 游戏运行期间（autoplaySuppressed=true）自动抑制非手动触发的自动播放，但不拦截用户手动点击播放。
   */
  async function syncGameBgm(
    game: Game | null,
    options: { autoPlay?: boolean; manual?: boolean; cacheBust?: number } = {},
  ) {
    const resolved = resolveGameBgmPlayback(game, options.cacheBust)
    const shouldAutoPlay =
      Boolean(options.autoPlay) && (Boolean(options.manual) || !autoplaySuppressed.value)

    // 同曲目且不需要自动播放时直接返回，避免打断正在进行的淡出/暂停流程
    if (game && resolved) {
      const isSameTrack = currentGameId.value === game.id && currentBgmPath.value === resolved.key
      if (isSameTrack) {
        const el = ensureAudioElement()
        if (shouldAutoPlay && (el.paused || isFadingOut)) {
          await playWithFade()
        }
        return
      }
    }

    const token = ++transitionToken
    cancelFade()

    // 若游戏无原声：若正在播放旧曲，则平滑淡出并停止
    if (!game || !resolved) {
      playbackIntent = 'pause'
      if (audioEl && !audioEl.paused) {
        const prevVolume =
          fadeOutSnapshotVolume !== null ? fadeOutSnapshotVolume : effectiveTargetVolume()
        fadeOutSnapshotVolume = prevVolume
        isFadingOut = true
        isPlaying.value = false
        await animateVolume(audioEl.volume, 0, FADE_DURATION_MS, 'ease-out', token)
        if (token !== transitionToken || getPlaybackIntent() !== 'pause') return
        const restoreVolume = fadeOutSnapshotVolume ?? prevVolume
        audioEl.pause()
        audioEl.volume = Math.min(1, Math.max(0, restoreVolume))
        isFadingOut = false
        fadeOutSnapshotVolume = null
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

    const el = ensureAudioElement()

    // 切换不同游戏：先平滑淡出旧原声
    if (!el.paused) {
      playbackIntent = 'pause'
      isFadingOut = true
      isPlaying.value = false
      const fadeMs = fadeOutSnapshotVolume !== null ? 180 : FADE_DURATION_MS
      await animateVolume(el.volume, 0, fadeMs, 'ease-out', token)
      if (token !== transitionToken) return
      el.pause()
      isFadingOut = false
      fadeOutSnapshotVolume = null
    }

    currentGameId.value = game.id
    currentTitle.value = game.title
    currentBgmPath.value = resolved.key
    currentTime.value = 0
    duration.value = 0
    autoplayBlocked.value = false

    el.loop = loop.value
    el.src = resolved.url
    el.currentTime = 0

    if (shouldAutoPlay) {
      await playWithFade(token)
    } else {
      playbackIntent = 'pause'
      el.volume = effectiveTargetVolume()
    }
  }

  async function playWithFade(token?: number) {
    const myToken = token ?? ++transitionToken
    const el = ensureAudioElement()
    if (!currentBgmPath.value) return

    const wasFadingOut = isFadingOut
    playbackIntent = 'play'
    cancelFade()
    isFadingOut = false
    fadeOutSnapshotVolume = null

    const target = effectiveTargetVolume()
    const startVol = !el.paused && wasFadingOut ? Math.min(target, Math.max(0, el.volume)) : 0
    el.volume = startVol
    try {
      await el.play()
      if (myToken !== transitionToken || getPlaybackIntent() !== 'play') {
        if (getPlaybackIntent() === 'pause' && !isFadingOut) {
          el.pause()
          el.volume = effectiveTargetVolume()
        }
        return
      }
      isPlaying.value = true
      autoplayBlocked.value = false
      await animateVolume(startVol, target, FADE_DURATION_MS, 'ease-out', myToken)
    } catch {
      // 浏览器拦截自动播放时静默回退为待点击状态，不抛出报错
      if (myToken !== transitionToken) return
      playbackIntent = 'pause'
      el.volume = target
      isPlaying.value = false
      autoplayBlocked.value = true
    }
  }

  async function togglePlayForGame(game: Game, cacheBust?: number) {
    const resolved = resolveGameBgmPlayback(game, cacheBust)
    if (!resolved) return

    const isSameTrack = currentGameId.value === game.id && currentBgmPath.value === resolved.key
    if (!isSameTrack) {
      await syncGameBgm(game, { autoPlay: true, manual: true, cacheBust })
      return
    }

    const el = ensureAudioElement()
    if (el.paused || isFadingOut) {
      await playWithFade()
    } else {
      await pauseBgmSmooth(260)
    }
  }

  async function stopSmooth(fadeOutMs = FADE_DURATION_MS) {
    await pauseBgmSmooth(fadeOutMs)
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
    if (isFadingOut) {
      // 淡出暂停进行中时仅更新待还原目标音量，不打断淡出
      fadeOutSnapshotVolume = effectiveTargetVolume()
      return
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
    if (isFadingOut) {
      fadeOutSnapshotVolume = effectiveTargetVolume()
      return
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
    autoplaySuppressed,
    currentTime,
    duration,
    progress,
    volume,
    muted,
    loop,
    setAutoplaySuppressed,
    pauseAllMedia,
    syncGameBgm,
    togglePlayForGame,
    stopSmooth,
    seekToRatio,
    setVolume,
    toggleMute,
  }
})
