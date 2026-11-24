import type { CollectionItem, Game, LibrarySortBy, LibrarySortOrder } from '@/types'

export interface SortModeOption {
  key: LibrarySortBy
  label: string
  shortLabel: string
  defaultOrder: LibrarySortOrder
}

export const SORT_OPTIONS: SortModeOption[] = [
  { key: 'series_name', label: '系列与名称', shortLabel: '名称', defaultOrder: 'asc' },
  { key: 'recent_played', label: '最近游玩', shortLabel: '最近游玩', defaultOrder: 'desc' },
  { key: 'release_date', label: '发售日期', shortLabel: '发售日', defaultOrder: 'desc' },
  { key: 'play_time', label: '游玩时长', shortLabel: '时长', defaultOrder: 'desc' },
  { key: 'created_at', label: '入库顺序', shortLabel: '入库', defaultOrder: 'desc' },
]

export const VALID_SORT_KEYS = new Set<LibrarySortBy>(SORT_OPTIONS.map((o) => o.key))

const zhCollator = new Intl.Collator('zh-CN', {
  numeric: true,
  sensitivity: 'base',
})

const SUBTITLE_SPLIT_RE = /[-—：:~～·]/

export function normalizeSortBy(raw?: string | null): LibrarySortBy {
  const val = (raw || '').trim() as LibrarySortBy
  return VALID_SORT_KEYS.has(val) ? val : 'series_name'
}

export function normalizeSortOrder(raw?: string | null): LibrarySortOrder {
  return raw === 'desc' ? 'desc' : 'asc'
}

export function getSortOption(key: LibrarySortBy): SortModeOption {
  return SORT_OPTIONS.find((o) => o.key === key) || SORT_OPTIONS[0]
}

/**
 * 提取作品的系列归组键：
 * 1. 优先使用用户手动填写的 game.series；
 * 2. 否则按常见副标题分隔符切分，第一段长度 >= 2 时取第一段；
 * 3. 无分隔符时返回去除首尾空白的完整 title（配合 numeric 拼音对比保证续作紧邻）。
 */
export function getSeriesKey(game: Pick<Game, 'title' | 'series'>): string {
  const explicit = (game.series || '').trim()
  if (explicit) return explicit

  const title = (game.title || '').trim()
  if (!title) return ''

  const parts = title.split(SUBTITLE_SPLIT_RE)
  if (parts.length > 1) {
    const first = parts[0].trim()
    if (first.length >= 2) {
      return first
    }
  }
  return title
}

/**
 * 解析常见发售日期格式（YYYY-MM-DD / YYYY-MM / YYYY / YYYY年M月D日 / YYYY/M/D）为可比较的 YYYYMMDD 整数；
 * 无法解析或缺失时返回 null。
 */
function parseReleaseDateScore(raw?: string | null): number | null {
  const text = (raw || '').trim()
  if (!text) return null

  const fullMatch = text.match(/(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})/)
  if (fullMatch) {
    const y = Number(fullMatch[1])
    const m = Math.min(12, Math.max(1, Number(fullMatch[2])))
    const d = Math.min(31, Math.max(1, Number(fullMatch[3])))
    return y * 10000 + m * 100 + d
  }

  const ymMatch = text.match(/(\d{4})[-/.年](\d{1,2})/)
  if (ymMatch) {
    const y = Number(ymMatch[1])
    const m = Math.min(12, Math.max(1, Number(ymMatch[2])))
    return y * 10000 + m * 100 + 1
  }

  const yMatch = text.match(/\b(\d{4})\b/)
  if (yMatch) {
    return Number(yMatch[1]) * 10000 + 101
  }

  return null
}

function parseIsoTimestamp(raw?: string | null): number | null {
  if (!raw) return null
  const ms = Date.parse(raw)
  return Number.isFinite(ms) ? ms : null
}

function compareByName(a: Game, b: Game): number {
  return zhCollator.compare((a.title || '').trim(), (b.title || '').trim())
}

interface CollectionClusterInfo {
  collectionId: number
  name: string
  position: number
}

function buildGameCollectionMap(
  collections: CollectionItem[] = [],
): Map<number, CollectionClusterInfo> {
  const map = new Map<number, CollectionClusterInfo>()
  if (!collections || collections.length === 0) return map

  const orderedCols = [...collections].sort((a, b) => {
    const aSeries = a.collection_type !== 'custom' ? 0 : 1
    const bSeries = b.collection_type !== 'custom' ? 0 : 1
    if (aSeries !== bSeries) return aSeries - bSeries
    if ((a.sort_order ?? 0) !== (b.sort_order ?? 0)) {
      return (a.sort_order ?? 0) - (b.sort_order ?? 0)
    }
    return a.id - b.id
  })

  for (const col of orderedCols) {
    const entries =
      col.items && col.items.length > 0
        ? [...col.items].sort((x, y) => (x.position ?? 0) - (y.position ?? 0))
        : (col.game_ids || []).map((gid, idx) => ({ game_id: gid, position: idx }))

    for (let i = 0; i < entries.length; i++) {
      const gid = entries[i].game_id
      if (!map.has(gid)) {
        map.set(gid, {
          collectionId: col.id,
          name: (col.name || '').trim(),
          position: entries[i].position ?? i,
        })
      }
    }
  }
  return map
}

/**
 * 统一游戏库排序引擎（回廊与侧边栏共享同一份排序结果）：
 * - 在 `series_name` 模式下，优先将同一合集/系列的作品按合集名穿插聚拢，合集内严格按 position 排列
 */
export function sortGames(
  games: Game[],
  sortBy: LibrarySortBy = 'series_name',
  order: LibrarySortOrder = 'asc',
  collections: CollectionItem[] = [],
): Game[] {
  const dir = order === 'desc' ? -1 : 1
  const list = [...games]
  const gameCollectionMap =
    sortBy === 'series_name' ? buildGameCollectionMap(collections) : new Map<number, CollectionClusterInfo>()

  list.sort((a, b) => {
    if (sortBy === 'series_name') {
      const colA = gameCollectionMap.get(a.id)
      const colB = gameCollectionMap.get(b.id)

      if (colA && colB && colA.collectionId === colB.collectionId) {
        if (colA.position !== colB.position) {
          return colA.position - colB.position
        }
        return compareByName(a, b)
      }

      const keyA = colA ? colA.name : getSeriesKey(a)
      const keyB = colB ? colB.name : getSeriesKey(b)
      const keyCmp = zhCollator.compare(keyA, keyB)
      if (keyCmp !== 0) {
        return keyCmp * dir
      }

      if (colA && !colB) return -1
      if (!colA && colB) return 1
      if (colA && colB && colA.collectionId !== colB.collectionId) {
        return colA.collectionId - colB.collectionId
      }

      // 同一系列内部：始终按发售日从早到晚升序（缺失日期排在有日期之后）
      const dateA = parseReleaseDateScore(a.release_date)
      const dateB = parseReleaseDateScore(b.release_date)
      if (dateA !== null && dateB !== null && dateA !== dateB) {
        return dateA - dateB
      }
      if (dateA !== null && dateB === null) return -1
      if (dateA === null && dateB !== null) return 1

      return compareByName(a, b)
    }

    if (sortBy === 'recent_played') {
      const tA = parseIsoTimestamp(a.play_record?.last_played_at)
      const tB = parseIsoTimestamp(b.play_record?.last_played_at)
      // 从未游玩的始终排在已游玩作品之后，内部按名称排
      if (tA !== null && tB === null) return -1
      if (tA === null && tB !== null) return 1
      if (tA !== null && tB !== null && tA !== tB) {
        return (tA - tB) * dir
      }
      return compareByName(a, b)
    }

    if (sortBy === 'release_date') {
      const dA = parseReleaseDateScore(a.release_date)
      const dB = parseReleaseDateScore(b.release_date)
      // 缺失日期始终排在后面
      if (dA !== null && dB === null) return -1
      if (dA === null && dB !== null) return 1
      if (dA !== null && dB !== null && dA !== dB) {
        return (dA - dB) * dir
      }
      return compareByName(a, b)
    }

    if (sortBy === 'play_time') {
      const sA = a.play_record?.total_seconds || 0
      const sB = b.play_record?.total_seconds || 0
      if (sA !== sB) {
        return (sA - sB) * dir
      }
      return compareByName(a, b)
    }

    // created_at（入库顺序）
    const cA = parseIsoTimestamp(a.created_at) ?? a.id
    const cB = parseIsoTimestamp(b.created_at) ?? b.id
    if (cA !== cB) {
      return (cA - cB) * dir
    }
    return (a.id - b.id) * dir
  })

  return list
}
