export type BentoSpan = 1 | 2 | 3

export interface BentoLayoutOptions {
  targetRatio: number
  cellAspect?: number
}

export interface BentoTile<T> {
  col: number
  row: number
  span: BentoSpan
  item: T
}

export interface BentoEmptyRect {
  col: number
  row: number
  colSpan: number
  rowSpan: number
}

export interface BentoLayoutResult<T> {
  cols: number
  rows: number
  cellAspect: number
  tiles: BentoTile<T>[]
  emptySlots: BentoEmptyRect[]
  emptyCells: number
}

interface PackAttempt<T> {
  cols: number
  rows: number
  tiles: BentoTile<T>[]
  emptySlots: BentoEmptyRect[]
  emptyCells: number
  distortion: number
}

function clamp(val: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, val))
}

function computeMedian(values: number[]): number {
  if (!values.length) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 1
    ? sorted[mid]
    : (sorted[mid - 1] + sorted[mid]) / 2
}

/**
 * 按游玩时长将作品分级为等比整数块（1×1 / 2×2 / 3×3），
 * 确保所有格子在网格坐标中都是正方形，从而映射到像素后保持完全一致的竖版封面比例。
 */
function assignSpans<T extends { id: number; play_seconds: number }>(
  sortedItems: T[],
): BentoSpan[] {
  const n = sortedItems.length
  if (n === 0) return []
  if (n === 1) return [1]

  const playedIndices: number[] = []
  const playedSeconds: number[] = []
  for (let i = 0; i < n; i++) {
    const sec = Math.max(0, sortedItems[i].play_seconds)
    if (sec > 0) {
      playedIndices.push(i)
      playedSeconds.push(sec)
    }
  }

  const playedCount = playedIndices.length
  if (playedCount === 0) {
    return new Array<BentoSpan>(n).fill(1)
  }

  const spans = new Array<BentoSpan>(n).fill(1)
  const medianPlayed = computeMedian(playedSeconds)

  // 1) 3×3（9 倍面积）：仅在总数 >= 14 且榜首 1~2 部作品时长显著领先（>= 3x 有游玩中位数）时启用
  let count3 = 0
  if (n >= 14 && playedCount >= 2 && medianPlayed > 0) {
    for (let i = 0; i < Math.min(2, playedCount); i++) {
      const idx = playedIndices[i]
      if (sortedItems[idx].play_seconds >= medianPlayed * 3) {
        spans[idx] = 3
        count3++
      }
    }
  }

  // 2) 2×2（4 倍面积）
  if (playedCount < n) {
    // 存在未游玩作品：优先突出有游玩记录的前排作品
    // 当有游玩记录数占比较克制（如 8 部里玩过 2 部、6 部未玩）时，全部已玩作品升级为 2×2
    const promoteAllThreshold = Math.max(3, Math.floor(n * 0.45))
    if (playedCount <= promoteAllThreshold) {
      for (const idx of playedIndices) {
        if (spans[idx] === 1) {
          spans[idx] = 2
        }
      }
    } else {
      const target2Count = Math.max(2, Math.min(6, Math.round(n * 0.28) - count3))
      let assigned2 = 0
      for (const idx of playedIndices) {
        if (spans[idx] !== 1) continue
        if (assigned2 >= target2Count) break
        if (sortedItems[idx].play_seconds >= medianPlayed * 0.9 || assigned2 < 2) {
          spans[idx] = 2
          assigned2++
        }
      }
    }
  } else {
    // 全员均有游玩记录：按时长自然分段，取前约 20%～30% 且时长明显高于后段的作品为 2×2
    if (n === 2) {
      // 两部作品全部 1×1 并排最稳妥，避免 2×2 + 1×1 必然出现 1 格空洞
      return spans
    }
    if (n === 3) {
      if (sortedItems[0].play_seconds >= sortedItems[1].play_seconds * 1.45) {
        spans[0] = 2
      }
      return spans
    }

    const max2Count = Math.max(1, Math.min(6, Math.round(n * 0.25) - count3))
    let assigned2 = 0
    for (let i = 0; i < n && assigned2 < max2Count; i++) {
      if (spans[i] !== 1) continue
      const sec = sortedItems[i].play_seconds
      // 明显高于中位数（>= 1.25x），或榜首显著高于末位（>= 1.45x）
      if (
        sec >= medianPlayed * 1.25 ||
        (assigned2 === 0 && sec >= sortedItems[n - 1].play_seconds * 1.45)
      ) {
        spans[i] = 2
        assigned2++
      }
    }
  }

  return spans
}

/**
 * 将布尔占位矩阵中的剩余空位合并为尽量规整的无重叠矩形块（便于画布层渲染策展徽标块）
 */
function extractEmptyRects(grid: boolean[][], cols: number, rows: number): BentoEmptyRect[] {
  const visited = Array.from({ length: rows }, () => new Array<boolean>(cols).fill(false))
  const rects: BentoEmptyRect[] = []

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (grid[r][c] || visited[r][c]) continue

      // 先横向扩展最大连续空列
      let colSpan = 1
      while (c + colSpan < cols && !grid[r][c + colSpan] && !visited[r][c + colSpan]) {
        colSpan++
      }

      // 再向下扩展保持同宽的连续空行
      let rowSpan = 1
      outer: while (r + rowSpan < rows) {
        for (let dc = 0; dc < colSpan; dc++) {
          if (grid[r + rowSpan][c + dc] || visited[r + rowSpan][c + dc]) {
            break outer
          }
        }
        rowSpan++
      }

      for (let dr = 0; dr < rowSpan; dr++) {
        for (let dc = 0; dc < colSpan; dc++) {
          visited[r + dr][c + dc] = true
        }
      }

      rects.push({ col: c, row: r, colSpan, rowSpan })
    }
  }

  return rects
}

/**
 * 确定性左上优先（top-left first）2D 布尔矩阵紧密装箱
 */
function packIntoColumns<T>(
  entries: { item: T; span: BentoSpan }[],
  cols: number,
  cellAspect: number,
  targetRatio: number,
): PackAttempt<T> {
  const grid: boolean[][] = []
  const tiles: BentoTile<T>[] = []
  let maxRowUsed = 0

  const ensureRows = (neededRows: number) => {
    while (grid.length < neededRows) {
      grid.push(new Array<boolean>(cols).fill(false))
    }
  }

  const canPlace = (col: number, row: number, span: number): boolean => {
    if (col + span > cols) return false
    ensureRows(row + span)
    for (let dr = 0; dr < span; dr++) {
      for (let dc = 0; dc < span; dc++) {
        if (grid[row + dr][col + dc]) return false
      }
    }
    return true
  }

  const place = (col: number, row: number, span: number) => {
    ensureRows(row + span)
    for (let dr = 0; dr < span; dr++) {
      for (let dc = 0; dc < span; dc++) {
        grid[row + dr][col + dc] = true
      }
    }
    if (row + span > maxRowUsed) {
      maxRowUsed = row + span
    }
  }

  for (const entry of entries) {
    const span = entry.span
    let placed = false
    let row = 0
    while (!placed) {
      ensureRows(row + span)
      for (let col = 0; col <= cols - span; col++) {
        if (canPlace(col, row, span)) {
          place(col, row, span)
          tiles.push({ col, row, span, item: entry.item })
          placed = true
          break
        }
      }
      if (!placed) row++
    }
  }

  const rows = Math.max(1, maxRowUsed)
  const usedCells = entries.reduce((acc, e) => acc + e.span * e.span, 0)
  const emptyCells = Math.max(0, cols * rows - usedCells)
  const emptySlots = emptyCells > 0 ? extractEmptyRects(grid, cols, rows) : []

  const gridRatio = (cols * cellAspect) / rows
  const distortion = Math.abs(Math.log(gridRatio / targetRatio))

  return {
    cols,
    rows,
    tiles,
    emptySlots,
    emptyCells,
    distortion,
  }
}

/**
 * 在所有候选列数中寻找最优解：
 * 1) 过滤掉极端细长条（例如 13×1 的单行条，除非没有更合理方案）；
 * 2) 第一优先级：最小化 emptyCells（优先实现 emptyCells === 0 严丝合缝无黑洞）；
 * 3) 第二优先级：网格真实宽高比 (cols * cellAspect) / rows 最贴近 targetRatio。
 */
function findBestPack<T>(
  entries: { item: T; span: BentoSpan }[],
  cellAspect: number,
  targetRatio: number,
): PackAttempt<T> {
  const maxSpan = entries.reduce((m, e) => Math.max(m, e.span), 1)
  const totalCells = entries.reduce((acc, e) => acc + e.span * e.span, 0)

  const minCols = maxSpan
  const maxCols = Math.max(
    minCols,
    Math.min(
      totalCells,
      Math.max(maxSpan * 2, Math.ceil(totalCells / maxSpan) + 2),
    ),
  )

  const attempts: PackAttempt<T>[] = []
  for (let cols = minCols; cols <= maxCols; cols++) {
    attempts.push(packIntoColumns(entries, cols, cellAspect, targetRatio))
  }

  // 将畸变超过 ~3.8 倍（|ln(ratio/target)| > 1.35）的极端长条归入兜底档，避免素数作品数退化为 1×11 细条
  const reasonable = attempts.filter((a) => a.distortion <= 1.35)
  const pool = reasonable.length > 0 ? reasonable : attempts

  pool.sort((a, b) => {
    if (a.emptyCells !== b.emptyCells) return a.emptyCells - b.emptyCells
    if (Math.abs(a.distortion - b.distortion) > 1e-4) {
      return a.distortion - b.distortion
    }
    return a.rows - b.rows
  })

  return pool[0]
}

/**
 * 等比模块化 Bento 封面网格拼图布局（1×1 / 2×2 / 3×3）
 * 确保每一张封面都严格保持相同的竖版封面宽高比 cellAspect，零畸变、不切图。
 */
export function computeBentoCoverLayout<T extends { id: number; play_seconds: number }>(
  items: T[],
  options: BentoLayoutOptions,
): BentoLayoutResult<T> {
  const cellAspect = clamp(options.cellAspect ?? 0.71, 0.68, 0.76)
  const targetRatio =
    Number.isFinite(options.targetRatio) && options.targetRatio > 0
      ? options.targetRatio
      : 1.78

  if (!items.length) {
    return {
      cols: 0,
      rows: 0,
      cellAspect,
      tiles: [],
      emptySlots: [],
      emptyCells: 0,
    }
  }

  // 按游玩时长降序排列（同长保持输入顺序）
  const sorted = [...items].sort((a, b) => b.play_seconds - a.play_seconds)
  const baseSpans = assignSpans(sorted)

  const buildEntries = (spans: BentoSpan[]) =>
    sorted
      .map((item, idx) => ({ item, span: spans[idx], idx }))
      .sort((a, b) => b.span - a.span || a.idx - b.idx)
      .map(({ item, span }) => ({ item, span }))

  let best = findBestPack(buildEntries(baseSpans), cellAspect, targetRatio)

  // 若仍有 1~3 个空位，或在较大库下虽然零空洞但比例与目标画幅偏差过大（如竖版海报落入横条），
  // 尝试微调边界上 1 个候选项的 span（升/降 1 级，总格数 ±3 或 ±5）以获得更优零空洞解
  const shouldTryNudge =
    (best.emptyCells >= 1 && best.emptyCells <= 3 && sorted.length >= 4) ||
    (best.emptyCells === 0 && best.distortion > 0.95 && sorted.length >= 10)

  if (shouldTryNudge) {
    const nudgeCandidates: BentoSpan[][] = []

    // 候选 1：将排在最前的已游玩 1×1 作品升为 2×2（+3 格）
    const firstPlayed1Idx = sorted.findIndex(
      (item, idx) => baseSpans[idx] === 1 && item.play_seconds > 0,
    )
    if (firstPlayed1Idx >= 0) {
      const next = [...baseSpans]
      next[firstPlayed1Idx] = 2
      nudgeCandidates.push(next)
    }

    // 候选 2：若有 >= 2 个 2×2，将最末一个 2×2 降为 1×1（-3 格）
    const last2Idx = baseSpans.lastIndexOf(2)
    const count2 = baseSpans.filter((s) => s === 2).length
    if (last2Idx >= 0 && count2 >= 2) {
      const next = [...baseSpans]
      next[last2Idx] = 1
      nudgeCandidates.push(next)
    }

    // 候选 3：若有 3×3，将最末一个 3×3 降为 2×2（-5 格）
    const last3Idx = baseSpans.lastIndexOf(3)
    if (last3Idx >= 0) {
      const next = [...baseSpans]
      next[last3Idx] = 2
      nudgeCandidates.push(next)
    }

    for (const candidateSpans of nudgeCandidates) {
      const attempt = findBestPack(buildEntries(candidateSpans), cellAspect, targetRatio)
      if (attempt.emptyCells === 0 && attempt.distortion <= 1.25) {
        if (best.emptyCells > 0 || attempt.distortion < best.distortion * 0.65) {
          best = attempt
        }
      }
    }
  }

  return {
    cols: best.cols,
    rows: best.rows,
    cellAspect,
    tiles: best.tiles,
    emptySlots: best.emptySlots,
    emptyCells: best.emptyCells,
  }
}
