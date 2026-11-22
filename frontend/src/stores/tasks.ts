import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { scraperApi, tasksApi } from '@/api/client'
import { useLibraryStore } from '@/stores/library'
import type { DownloadTaskItem } from '@/types'

interface PvRetryPayload {
  url: string
  source?: string
  mime_hint?: string
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

  function canRetryPv(gameId: number | null | undefined): boolean {
    if (gameId == null) return false
    return Boolean(retryPvMap.value[gameId]?.url)
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

      const newlyCompletedGameIds = new Set<number>()
      for (const item of incoming) {
        const key = taskKey(item.game_id, item.asset_type)
        const prev = prevStatusMap.get(key)
        if (item.status === 'done' && prev && prev !== 'done') {
          newlyCompletedGameIds.add(item.game_id)
          const label = item.asset_type === 'pv' ? '宣传片已缓存至本地' : '主题曲已下载绑定'
          libraryStore.notify(label, 'success')
        }
        prevStatusMap.set(key, item.status)
      }

      tasks.value = incoming

      if (newlyCompletedGameIds.size > 0) {
        await Promise.all(
          Array.from(newlyCompletedGameIds).map((gid) => libraryStore.refreshGame(gid)),
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

  async function retryPvDownload(gameId: number) {
    const meta = retryPvMap.value[gameId]
    if (!meta?.url) return
    const libraryStore = useLibraryStore()
    try {
      const res = await scraperApi.applyAsset(gameId, {
        asset_type: 'pv',
        url: meta.url,
        source: meta.source || '',
        mime_hint: meta.mime_hint || '',
        async_mode: true,
      })
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
    } catch (err) {
      libraryStore.notify(err instanceof Error ? err.message : '重试下载失败', 'error')
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
    canRetryPv,
    trackTask,
    pollNow,
    stopPolling,
    retryPvDownload,
    dismissTask,
  }
})
