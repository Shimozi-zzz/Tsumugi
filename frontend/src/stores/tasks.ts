import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { mediaApi, scraperApi, tasksApi } from '@/api/client'
import { useLibraryStore } from '@/stores/library'
import type { DownloadTaskItem } from '@/types'

interface PvRetryPayload {
  url: string
  source?: string
  mime_hint?: string
  fallback_urls?: string[]
}

const POLL_INTERVAL_MS = 1500

export const useTaskStore = defineStore('tasks', () => {
  const tasks = ref<DownloadTaskItem[]>([])
  const retryPvMap = ref<Record<number, PvRetryPayload>>({})

  let pollTimer: number | null = null
  let pollingInFlight = false
  const prevStatusMap = new Map<string, string>()

  function taskKey(gameId: number, assetType: string): string {
    return `${gameId}:${assetType}`
  }

  const hasActiveTasks = computed(() =>
    tasks.value.some((t) => t.status === 'queued' || t.status === 'downloading'),
  )

  function getTask(gameId: number | null | undefined, assetType: 'pv' | 'bgm'): DownloadTaskItem | null {
    if (gameId == null) return null
    return tasks.value.find((t) => t.game_id === gameId && t.asset_type === assetType) || null
  }

  function getPvRetryUrl(gameId: number | null | undefined): string {
    if (gameId == null) return ''
    return (retryPvMap.value[gameId]?.url || '').trim()
  }

  function canRetryPv(gameId: number | null | undefined, fallbackRemoteUrl?: string): boolean {
    if (gameId == null) return false
    return Boolean(retryPvMap.value[gameId]?.url || (fallbackRemoteUrl || '').trim())
  }

  function stopPolling() {
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  function ensurePolling() {
    if (pollTimer !== null) return
    pollTimer = window.setInterval(() => {
      void pollNow()
    }, POLL_INTERVAL_MS)
  }

  function upsertLocalTask(item: DownloadTaskItem) {
    const idx = tasks.value.findIndex(
      (t) => t.game_id === item.game_id && t.asset_type === item.asset_type,
    )
    if (idx >= 0) {
      tasks.value[idx] = item
    } else {
      tasks.value.unshift(item)
    }
    prevStatusMap.set(taskKey(item.game_id, item.asset_type), item.status)
  }

  function trackTask(
    initial?: Partial<DownloadTaskItem> & { game_id: number; asset_type: string },
    pvRetry?: PvRetryPayload,
  ) {
    if (pvRetry?.url && initial?.game_id != null) {
      retryPvMap.value = { ...retryPvMap.value, [initial.game_id]: pvRetry }
    }
    if (initial) {
      upsertLocalTask({
        game_id: initial.game_id,
        asset_type: initial.asset_type,
        status: initial.status || 'queued',
        progress: initial.progress ?? 0,
        message: initial.message || '等待下载…',
        updated_at: initial.updated_at || new Date().toISOString(),
      })
    }
    ensurePolling()
    void pollNow()
  }

  async function pollNow() {
    if (pollingInFlight) return
    pollingInFlight = true
    try {
      const res = await tasksApi.downloads()
      const incoming = res.items || []
      const libraryStore = useLibraryStore()

      const needRefreshGameIds = new Set<number>()
      for (const item of incoming) {
        const key = taskKey(item.game_id, item.asset_type)
        const prev = prevStatusMap.get(key)
        if (item.status === 'done' && prev && prev !== 'done') {
          needRefreshGameIds.add(item.game_id)
          const label = item.asset_type === 'pv' ? '宣传片已缓存至本地' : '主题曲已下载绑定'
          libraryStore.notify(label, 'success')
        } else if (item.status === 'error' && prev && prev !== 'error') {
          // 后台下载失败时自动同步最新游戏媒体字段，确保远程链接播放器零刷新立即呈现
          needRefreshGameIds.add(item.game_id)
        }
        prevStatusMap.set(key, item.status)
      }

      tasks.value = incoming

      if (needRefreshGameIds.size > 0) {
        await Promise.all(
          Array.from(needRefreshGameIds).map((gid) => libraryStore.refreshGame(gid)),
        )
      }

      const stillActive = incoming.some(
        (t) => t.status === 'queued' || t.status === 'downloading',
      )
      if (stillActive) {
        ensurePolling()
      } else {
        stopPolling()
      }
    } catch {
      // ignore transient polling failure
    } finally {
      pollingInFlight = false
    }
  }

  async function retryPvDownload(gameId: number, fallbackRemoteUrl?: string) {
    const meta = retryPvMap.value[gameId]
    const targetUrl = (meta?.url || fallbackRemoteUrl || '').trim()
    const libraryStore = useLibraryStore()
    try {
      if (meta?.url) {
        const res = await scraperApi.applyAsset(gameId, {
          asset_type: 'pv',
          url: meta.url,
          source: meta.source || '',
          mime_hint: meta.mime_hint || '',
          fallback_urls: meta.fallback_urls || [],
          mode: 'download',
          async_mode: true,
        })
        libraryStore.syncGameFromServer(res)
        trackTask(
          res.download_task || {
            game_id: gameId,
            asset_type: 'pv',
            status: 'queued',
            progress: 0,
            message: '正在重试下载…',
          },
          meta,
        )
      } else if (targetUrl) {
        const res = await mediaApi.cacheRemote(gameId, 'pv')
        libraryStore.syncGameFromServer(res)
        trackTask(
          res.download_task || {
            game_id: gameId,
            asset_type: 'pv',
            status: 'queued',
            progress: 0,
            message: '正在重试下载…',
          },
          { url: targetUrl },
        )
      }
    } catch (err) {
      libraryStore.notify(err instanceof Error ? err.message : '重试下载失败', 'error')
    }
  }

  async function retryBgmDownload(gameId: number) {
    const libraryStore = useLibraryStore()
    try {
      const res = await mediaApi.cacheRemote(gameId, 'bgm')
      libraryStore.syncGameFromServer(res)
      trackTask(
        res.download_task || {
          game_id: gameId,
          asset_type: 'bgm',
          status: 'queued',
          progress: 0,
          message: '正在重试下载主题曲…',
        },
      )
    } catch (err) {
      libraryStore.notify(err instanceof Error ? err.message : '重试下载主题曲失败', 'error')
    }
  }

  async function keepLinkOnlyAndDismiss(gameId: number, assetType: 'pv' | 'bgm', remoteUrl?: string) {
    const libraryStore = useLibraryStore()
    const cleanUrl = (remoteUrl || (assetType === 'pv' ? getPvRetryUrl(gameId) : '')).trim()
    dismissTask(gameId, assetType)
    if (!cleanUrl) return
    try {
      if (assetType === 'pv') {
        await libraryStore.updateGamePatch(gameId, {
          media: {
            pv_mode: 'link_only',
            pv_remote_url: cleanUrl,
            pv_url_or_path: cleanUrl,
          },
        })
        libraryStore.notify('已保留宣传片在线链接', 'info')
      } else {
        await libraryStore.updateGamePatch(gameId, {
          media: {
            bgm_mode: 'link_only',
            bgm_remote_url: cleanUrl,
            bgm_path: cleanUrl,
          },
        })
        libraryStore.notify('已保留主题曲在线链接', 'info')
      }
    } catch {
      // ignore patch error on dismiss
    }
  }

  function dismissTask(gameId: number, assetType: 'pv' | 'bgm') {
    tasks.value = tasks.value.filter(
      (t) => !(t.game_id === gameId && t.asset_type === assetType),
    )
    prevStatusMap.delete(taskKey(gameId, assetType))
  }

  return {
    tasks,
    hasActiveTasks,
    getTask,
    getPvRetryUrl,
    canRetryPv,
    trackTask,
    pollNow,
    stopPolling,
    retryPvDownload,
    retryBgmDownload,
    keepLinkOnlyAndDismiss,
    dismissTask,
  }
})
