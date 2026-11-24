<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { assetUrl, statsApi } from '@/api/client'
import { useLibraryStore } from '@/stores/library'
import type { CollageGameItem, JourneyCollageResponse } from '@/types'
import { computeBentoCoverLayout } from '@/utils/bentoLayout'

type RatioKey = 'adaptive' | '16x9' | '3x4' | '1x1'
type CollageMode = 'poster' | 'pure'

interface RatioPreset {
  key: RatioKey
  label: string
  dimLabel: string
  width: number
  height: number | null
  targetRatio: number
}

const RATIO_PRESETS: RatioPreset[] = [
  {
    key: 'adaptive',
    label: '自适应海报',
    dimLabel: '1920 宽自适应',
    width: 1920,
    height: null,
    targetRatio: 1.78,
  },
  {
    key: '16x9',
    label: '横版壁纸',
    dimLabel: '1920×1080',
    width: 1920,
    height: 1080,
    targetRatio: 16 / 9,
  },
  {
    key: '3x4',
    label: '竖版海报',
    dimLabel: '1200×1600',
    width: 1200,
    height: 1600,
    targetRatio: 3 / 4,
  },
  {
    key: '1x1',
    label: '方形图鉴',
    dimLabel: '1600×1600',
    width: 1600,
    height: 1600,
    targetRatio: 1,
  },
]

const BG_COLOR = '#0a0a0c'
const FOOTER_HEIGHT = 92
const TILE_RADIUS = 8

const store = useLibraryStore()

const loading = ref(true)
const rendering = ref(false)
const exporting = ref(false)
const errorMsg = ref('')
const collageData = ref<JourneyCollageResponse | null>(null)

const selectedYear = ref<string>('all')
const selectedCollectionId = ref<number | null>(null)
const selectedRatio = ref<RatioKey>('adaptive')
const layoutMode = ref<CollageMode>('poster')
const showLabels = ref(true)
const includeUnplayed = ref(false)
const userTouchedUnplayed = ref(false)
const hideNsfw = ref<boolean>(store.privacyBlurMode)

const resolvedWidth = ref<number>(1920)
const resolvedHeight = ref<number>(1080)
const resolvedGridText = ref<string>('')

const canvasRef = ref<HTMLCanvasElement | null>(null)

// 内存级图片缓存：切换画幅、文案或海报模式时零网络重下、瞬间重绘
const imageCache = new Map<string, HTMLImageElement | null>()
const pendingLoads = new Map<string, Promise<HTMLImageElement | null>>()
let renderSeq = 0

const currentPreset = computed<RatioPreset>(
  () => RATIO_PRESETS.find((p) => p.key === selectedRatio.value) || RATIO_PRESETS[0],
)

const availableYears = computed<string[]>(() => collageData.value?.available_years || [])

const selectedCollectionName = computed<string>(() => {
  if (selectedCollectionId.value == null) return ''
  const col = store.collections.find((c) => c.id === selectedCollectionId.value)
  return col?.name || ''
})

const filteredPool = computed<CollageGameItem[]>(() => {
  const list = collageData.value?.items || []
  if (!hideNsfw.value) return list
  return list.filter((item) => !item.is_nsfw)
})

const displayedItems = computed<CollageGameItem[]>(() => {
  if (includeUnplayed.value) return filteredPool.value
  return filteredPool.value.filter((item) => item.play_seconds > 0)
})

const displayedTotalSeconds = computed<number>(() =>
  displayedItems.value.reduce((acc, item) => acc + Math.max(0, item.play_seconds), 0),
)

const hiddenUnplayedAvailable = computed<boolean>(() => {
  if (includeUnplayed.value) return false
  return filteredPool.value.some((item) => item.play_seconds <= 0)
})

const canExport = computed<boolean>(
  () => !loading.value && !errorMsg.value && displayedItems.value.length > 0 && !exporting.value,
)

function clamp(val: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, val))
}

function formatHoursCompact(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  if (s <= 0) return ''
  if (s < 60) return '<1m'
  if (s < 3600) return `${Math.round(s / 60)}m`
  return `${(s / 3600).toFixed(1)}h`
}

function formatTotalStat(count: number, totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds))
  if (s <= 0) {
    return `${count} 部藏品`
  }
  if (s < 60) {
    return `${count} 部作品 · 累计 ${s} 秒`
  }
  if (s < 3600) {
    return `${count} 部作品 · 累计 ${Math.round(s / 60)} 分钟`
  }
  const hours = (s / 3600).toFixed(1)
  return `${count} 部作品 · 累计 ${hours} 小时`
}

function formatTodayDot(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}.${m}.${day}`
}

function loadImage(url: string): Promise<HTMLImageElement | null> {
  if (!url) return Promise.resolve(null)
  if (imageCache.has(url)) {
    return Promise.resolve(imageCache.get(url) ?? null)
  }
  const inflight = pendingLoads.get(url)
  if (inflight) return inflight

  const task = new Promise<HTMLImageElement | null>((resolve) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.decoding = 'async'
    img.onload = () => {
      if (img.naturalWidth > 0 && img.naturalHeight > 0) {
        imageCache.set(url, img)
        resolve(img)
      } else {
        imageCache.set(url, null)
        resolve(null)
      }
      pendingLoads.delete(url)
    }
    img.onerror = () => {
      imageCache.set(url, null)
      pendingLoads.delete(url)
      resolve(null)
    }
    img.src = url
  })

  pendingLoads.set(url, task)
  return task
}

async function resolveCoverImage(item: CollageGameItem): Promise<HTMLImageElement | null> {
  // 全格子统一优先使用封面图，缺失时依次回退封面缩略图与 Hero 背景
  const candidates = [item.cover_path, item.cover_thumb_path, item.hero_bg_path]

  const seen = new Set<string>()
  for (const rel of candidates) {
    if (!rel || seen.has(rel)) continue
    seen.add(rel)
    const url = assetUrl(rel, store.assetVersion)
    if (!url) continue
    const img = await loadImage(url)
    if (img) return img
  }
  return null
}

function computeMedianCoverAspect(images: (HTMLImageElement | null)[]): number {
  const ratios: number[] = []
  for (const img of images) {
    if (img && img.naturalWidth > 0 && img.naturalHeight > 0) {
      ratios.push(img.naturalWidth / img.naturalHeight)
    }
  }
  if (!ratios.length) return 0.71
  ratios.sort((a, b) => a - b)
  const mid = Math.floor(ratios.length / 2)
  const median =
    ratios.length % 2 === 1 ? ratios[mid] : (ratios[mid - 1] + ratios[mid]) / 2
  return clamp(median, 0.68, 0.76)
}

function traceRoundedRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  radius: number,
) {
  const r = Math.max(0, Math.min(radius, w / 2, h / 2))
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.lineTo(x + w - r, y)
  ctx.quadraticCurveTo(x + w, y, x + w, y + r)
  ctx.lineTo(x + w, y + h - r)
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
  ctx.lineTo(x + r, y + h)
  ctx.quadraticCurveTo(x, y + h, x, y + h - r)
  ctx.lineTo(x, y + r)
  ctx.quadraticCurveTo(x, y, x + r, y)
  ctx.closePath()
}

function drawCoverImage(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  dx: number,
  dy: number,
  dw: number,
  dh: number,
  anchorX = 0.5,
  anchorY = 0.28,
) {
  const iw = img.naturalWidth
  const ih = img.naturalHeight
  if (iw <= 0 || ih <= 0 || dw <= 0 || dh <= 0) return

  const imgRatio = iw / ih
  const boxRatio = dw / dh

  let sx = 0
  let sy = 0
  let sw = iw
  let sh = ih

  if (imgRatio > boxRatio) {
    sw = ih * boxRatio
    sx = (iw - sw) * anchorX
  } else {
    sh = iw / boxRatio
    sy = (ih - sh) * anchorY
  }

  ctx.drawImage(img, sx, sy, sw, sh, dx, dy, dw, dh)
}

function truncateText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (maxWidth <= 0) return ''
  if (ctx.measureText(text).width <= maxWidth) return text
  const ellipsis = '…'
  const ellipsisW = ctx.measureText(ellipsis).width
  if (ellipsisW >= maxWidth) return ''

  let lo = 0
  let hi = text.length
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2)
    if (ctx.measureText(text.slice(0, mid)).width + ellipsisW <= maxWidth) {
      lo = mid
    } else {
      hi = mid - 1
    }
  }
  return lo > 0 ? text.slice(0, lo) + ellipsis : ''
}

function measureTrackedWidth(ctx: CanvasRenderingContext2D, text: string, tracking: number): number {
  let width = 0
  for (let i = 0; i < text.length; i++) {
    width += ctx.measureText(text[i]).width + (i < text.length - 1 ? tracking : 0)
  }
  return width
}

function drawTrackedText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  tracking: number,
): number {
  let cursorX = x
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    ctx.fillText(ch, cursorX, y)
    cursorX += ctx.measureText(ch).width + (i < text.length - 1 ? tracking : 0)
  }
  return cursorX - x
}

async function renderCanvas() {
  if (!canvasRef.value) {
    await nextTick()
  }
  const canvas = canvasRef.value
  if (!canvas) return

  const seq = ++renderSeq
  const items = displayedItems.value
  const preset = currentPreset.value

  if (!items.length) {
    rendering.value = false
    resolvedGridText.value = ''
    return
  }

  rendering.value = true

  // 1) 并发加载全部封面（命中内存缓存时零延迟），据此计算真实封面中位数比例
  const resolvedList = await Promise.all(items.map((item) => resolveCoverImage(item)))
  if (seq !== renderSeq) return

  const imageByGameId = new Map<number, HTMLImageElement | null>()
  for (let i = 0; i < items.length; i++) {
    imageByGameId.set(items[i].id, resolvedList[i])
  }

  const cellAspect = computeMedianCoverAspect(resolvedList)
  const hasFooter = layoutMode.value === 'poster'
  const footerH = hasFooter ? FOOTER_HEIGHT : 0

  // 2) 计算目标网格参考比例并执行模块化 Bento 装箱
  const targetRatio =
    preset.height != null
      ? preset.width / Math.max(200, preset.height - footerH)
      : preset.targetRatio

  const layout = computeBentoCoverLayout(items, {
    targetRatio,
    cellAspect,
  })

  if (!layout.tiles.length) {
    rendering.value = false
    return
  }

  // 3) 计算严格锁定 cellAspect 的像素网格几何
  const gap = layout.cols >= 12 ? 6 : 8
  let W = preset.width
  let H = preset.height ?? 1080
  let unitW = 0
  let unitH = 0
  let originX = 0
  let originY = 0

  if (preset.height == null) {
    // 自适应海报：1920 宽固定，高度按行数与封面比例精确算出，100% 满版零留白
    const outerPad = 14
    unitW = (W - outerPad * 2 - (layout.cols - 1) * gap) / layout.cols
    unitH = unitW / layout.cellAspect
    const gridH = layout.rows * unitH + (layout.rows - 1) * gap
    H = Math.round(outerPad * 2 + gridH + footerH)
    originX = outerPad
    originY = outerPad
  } else {
    // 固定画幅（16:9 / 3:4 / 1:1）：严格锁定 cellW / cellH = cellAspect，等比居中装裱
    const matPadX = 36
    const matPadTop = 36
    const matPadBottom = hasFooter ? 28 : 36
    const availW = W - matPadX * 2
    const availH = H - footerH - matPadTop - matPadBottom

    const maxUnitWByW = (availW - (layout.cols - 1) * gap) / layout.cols
    const maxUnitWByH = ((availH - (layout.rows - 1) * gap) / layout.rows) * layout.cellAspect
    unitW = Math.max(24, Math.min(maxUnitWByW, maxUnitWByH))
    unitH = unitW / layout.cellAspect

    const actualGridW = layout.cols * unitW + (layout.cols - 1) * gap
    const actualGridH = layout.rows * unitH + (layout.rows - 1) * gap
    originX = (W - actualGridW) / 2
    originY = matPadTop + (availH - actualGridH) / 2
  }

  resolvedWidth.value = W
  resolvedHeight.value = H
  resolvedGridText.value = `${layout.cols}×${layout.rows}`

  if (canvas.width !== W || canvas.height !== H) {
    canvas.width = W
    canvas.height = H
  }

  const ctx = canvas.getContext('2d')
  if (!ctx) {
    rendering.value = false
    return
  }

  ctx.save()
  ctx.fillStyle = BG_COLOR
  ctx.fillRect(0, 0, W, H)
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'

  const sansFamily =
    '"Noto Sans SC", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif'
  const serifFamily =
    '"Cormorant Garamond", "Noto Serif SC", "Songti SC", Georgia, serif'
  const monoFamily =
    '"JetBrains Mono", "SFMono-Regular", ui-monospace, Menlo, monospace'

  // 4) 绘制全部等比封面格子
  for (const tile of layout.tiles) {
    const img = imageByGameId.get(tile.item.id) ?? null
    const tx = Math.round(originX + tile.col * (unitW + gap))
    const ty = Math.round(originY + tile.row * (unitH + gap))
    const tx2 = Math.round(
      originX + (tile.col + tile.span) * unitW + (tile.col + tile.span - 1) * gap,
    )
    const ty2 = Math.round(
      originY + (tile.row + tile.span) * unitH + (tile.row + tile.span - 1) * gap,
    )
    const tw = Math.max(1, tx2 - tx)
    const th = Math.max(1, ty2 - ty)

    ctx.save()
    traceRoundedRect(ctx, tx, ty, tw, th, TILE_RADIUS)
    ctx.clip()

    if (img) {
      drawCoverImage(ctx, img, tx, ty, tw, th, 0.5, 0.28)
    } else {
      const fallbackGrad = ctx.createLinearGradient(tx, ty, tx + tw, ty + th)
      fallbackGrad.addColorStop(0, '#18181d')
      fallbackGrad.addColorStop(1, '#101014')
      ctx.fillStyle = fallbackGrad
      ctx.fillRect(tx, ty, tw, th)

      if (tw >= 80 && th >= 80) {
        const fs = Math.round(clamp(tw * 0.085, 13, 24))
        ctx.font = `600 ${fs}px ${sansFamily}`
        ctx.fillStyle = 'rgba(245, 245, 247, 0.68)'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        const label = truncateText(ctx, tile.item.title, tw - 24)
        if (label) {
          ctx.fillText(label, tx + tw / 2, ty + th / 2)
        }
      }
    }

    // 底部自适应文字叠层（大格舒展、小格紧凑克制）
    if (showLabels.value && tw >= 115 && th >= 110) {
      const gradH = Math.min(th, Math.max(Math.round(th * 0.34), 60))
      const grad = ctx.createLinearGradient(tx, ty + th - gradH, tx, ty + th)
      grad.addColorStop(0, 'rgba(10, 10, 12, 0)')
      grad.addColorStop(0.45, 'rgba(10, 10, 12, 0.42)')
      grad.addColorStop(0.78, 'rgba(10, 10, 12, 0.75)')
      grad.addColorStop(1, 'rgba(10, 10, 12, 0.88)')
      ctx.fillStyle = grad
      ctx.fillRect(tx, ty + th - gradH, tw, gradH)

      const isLarge = tile.span >= 2
      const padX = Math.round(isLarge ? clamp(tw * 0.045, 16, 26) : clamp(tw * 0.058, 10, 15))
      const padBottom = Math.round(
        isLarge ? clamp(th * 0.036, 15, 24) : clamp(th * 0.045, 10, 15),
      )
      const titleFs = Math.round(
        isLarge ? clamp(tw * 0.052, 18, 30) : clamp(tw * 0.068, 12, 17),
      )
      const timeStr = formatHoursCompact(tile.item.play_seconds)
      const timeFs = Math.round(
        isLarge ? clamp(titleFs * 0.64, 13, 18) : clamp(titleFs * 0.78, 11, 13),
      )
      const maxTextW = tw - padX * 2

      ctx.textAlign = 'left'
      ctx.textBaseline = 'alphabetic'

      if (timeStr) {
        const timeY = ty + th - padBottom
        const titleY = timeY - timeFs - (isLarge ? 7 : 5)

        ctx.font = `600 ${titleFs}px ${sansFamily}`
        ctx.fillStyle = '#f5f5f7'
        ctx.shadowColor = 'rgba(0, 0, 0, 0.74)'
        ctx.shadowOffsetY = 1
        ctx.shadowBlur = 10
        const titleText = truncateText(ctx, tile.item.title, maxTextW)
        if (titleText) {
          ctx.fillText(titleText, tx + padX, titleY)
        }

        ctx.shadowColor = 'rgba(0, 0, 0, 0.65)'
        ctx.shadowOffsetY = 1
        ctx.shadowBlur = 6
        ctx.font = `500 ${timeFs}px ${monoFamily}`
        ctx.fillStyle = 'rgba(245, 245, 247, 0.86)'
        ctx.fillText(timeStr, tx + padX, timeY)
      } else {
        const titleY = ty + th - padBottom
        ctx.font = `600 ${titleFs}px ${sansFamily}`
        ctx.fillStyle = 'rgba(245, 245, 247, 0.94)'
        ctx.shadowColor = 'rgba(0, 0, 0, 0.74)'
        ctx.shadowOffsetY = 1
        ctx.shadowBlur = 10
        const titleText = truncateText(ctx, tile.item.title, maxTextW)
        if (titleText) {
          ctx.fillText(titleText, tx + padX, titleY)
        }
      }

      ctx.shadowColor = 'transparent'
      ctx.shadowOffsetY = 0
      ctx.shadowBlur = 0
    }

    // 极细腻内沿描边，界定暗色封面边缘
    traceRoundedRect(ctx, tx + 0.5, ty + 0.5, tw - 1, th - 1, TILE_RADIUS)
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.07)'
    ctx.lineWidth = 1
    ctx.stroke()

    ctx.restore()
  }

  // 5) 若极端素数作品数无法整除，用极简暗色策展徽标块优雅填补剩余空位，严禁黑洞
  if (layout.emptySlots.length > 0) {
    const periodShort = selectedYear.value === 'all' ? '全部历程' : `${selectedYear.value} 年度`
    const countShort = `${items.length} 部作品`

    for (const slot of layout.emptySlots) {
      const sx = Math.round(originX + slot.col * (unitW + gap))
      const sy = Math.round(originY + slot.row * (unitH + gap))
      const sx2 = Math.round(
        originX + (slot.col + slot.colSpan) * unitW + (slot.col + slot.colSpan - 1) * gap,
      )
      const sy2 = Math.round(
        originY + (slot.row + slot.rowSpan) * unitH + (slot.row + slot.rowSpan - 1) * gap,
      )
      const sw = Math.max(1, sx2 - sx)
      const sh = Math.max(1, sy2 - sy)

      ctx.save()
      traceRoundedRect(ctx, sx, sy, sw, sh, TILE_RADIUS)
      ctx.clip()

      const slotGrad = ctx.createLinearGradient(sx, sy, sx + sw, sy + sh)
      slotGrad.addColorStop(0, '#141418')
      slotGrad.addColorStop(1, '#0e0e11')
      ctx.fillStyle = slotGrad
      ctx.fillRect(sx, sy, sw, sh)

      const cx = sx + sw / 2
      const cy = sy + sh / 2

      if (sw >= 110 && sh >= 110) {
        const brandFs = Math.round(clamp(sw * 0.085, 13, 22))
        const tracking = brandFs * 0.18
        ctx.font = `600 ${brandFs}px ${serifFamily}`
        ctx.fillStyle = 'rgba(245, 245, 247, 0.72)'
        ctx.textAlign = 'left'
        ctx.textBaseline = 'middle'
        const bw = measureTrackedWidth(ctx, 'TSUMUGI', tracking)
        drawTrackedText(ctx, 'TSUMUGI', cx - bw / 2, cy - 18, tracking)

        ctx.fillStyle = 'rgba(255, 255, 255, 0.14)'
        ctx.fillRect(cx - 14, cy, 28, 1)

        const subFs = Math.round(clamp(sw * 0.052, 11, 14))
        ctx.font = `500 ${subFs}px ${sansFamily}`
        ctx.fillStyle = 'rgba(245, 245, 247, 0.48)'
        ctx.textAlign = 'center'
        ctx.fillText(truncateText(ctx, periodShort, sw - 20), cx, cy + 18)

        if (sh >= 160) {
          ctx.font = `500 ${Math.max(10, subFs - 1)}px ${monoFamily}`
          ctx.fillStyle = 'rgba(245, 245, 247, 0.36)'
          ctx.fillText(truncateText(ctx, countShort, sw - 20), cx, cy + 38)
        }
      }

      traceRoundedRect(ctx, sx + 0.5, sy + 0.5, sw - 1, sh - 1, TILE_RADIUS)
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.065)'
      ctx.lineWidth = 1
      ctx.stroke()
      ctx.restore()
    }
  }

  // 6) 典藏海报底部策展铭牌栏
  if (hasFooter) {
    const fy = H - FOOTER_HEIGHT
    ctx.fillStyle = BG_COLOR
    ctx.fillRect(0, fy, W, FOOTER_HEIGHT)

    ctx.fillStyle = 'rgba(255, 255, 255, 0.08)'
    ctx.fillRect(0, fy, W, 1)

    const padX = 32
    const midY = fy + FOOTER_HEIGHT / 2

    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.font = `600 24px ${serifFamily}`
    ctx.fillStyle = '#f5f5f7'
    const brandW = drawTrackedText(ctx, 'TSUMUGI', padX, midY + 1, 4.2)

    const dividerX = padX + brandW + 20
    ctx.fillStyle = 'rgba(255, 255, 255, 0.18)'
    ctx.fillRect(dividerX, midY - 10, 1, 20)

    const basePeriod =
      selectedYear.value === 'all' ? '全部游戏历程' : `${selectedYear.value} 年度回顾`
    const periodLabel = selectedCollectionName.value
      ? `${basePeriod} · ${selectedCollectionName.value}`
      : basePeriod

    const statText = formatTotalStat(items.length, displayedTotalSeconds.value)
    const dateText = formatTodayDot()

    ctx.textAlign = 'right'
    ctx.font = `500 13px ${monoFamily}`
    const dateW = ctx.measureText(dateText).width
    ctx.fillStyle = 'rgba(255, 255, 255, 0.42)'
    ctx.fillText(dateText, W - padX, midY + 1)

    const rightDividerX = W - padX - dateW - 18
    ctx.fillStyle = 'rgba(255, 255, 255, 0.16)'
    ctx.fillRect(rightDividerX, midY - 8, 1, 16)

    ctx.font = `500 15px ${sansFamily}`
    ctx.fillStyle = 'rgba(245, 245, 247, 0.92)'
    const statX = rightDividerX - 18
    const statW = ctx.measureText(statText).width
    ctx.fillText(statText, statX, midY + 1)

    const periodX = dividerX + 20
    const maxPeriodW = Math.max(80, statX - statW - 24 - periodX)
    ctx.textAlign = 'left'
    ctx.font = `500 15px ${sansFamily}`
    ctx.fillStyle = 'rgba(245, 245, 247, 0.72)'
    ctx.fillText(truncateText(ctx, periodLabel, maxPeriodW), periodX, midY + 1)
  }

  ctx.restore()
  rendering.value = false
}

async function fetchCollage() {
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await statsApi.collage({
      year: selectedYear.value,
      collection_id: selectedCollectionId.value,
    })
    collageData.value = res
    if (!userTouchedUnplayed.value) {
      includeUnplayed.value = res.played_games_count < 3
    }
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : '加载历程拼图数据失败'
  } finally {
    loading.value = false
  }
  await renderCanvas()
}

function toggleIncludeUnplayed(checked: boolean) {
  userTouchedUnplayed.value = true
  includeUnplayed.value = checked
}

async function exportPng() {
  const canvas = canvasRef.value
  if (!canvas || !canExport.value) return

  exporting.value = true
  try {
    await renderCanvas()
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob((b) => resolve(b), 'image/png'),
    )
    if (!blob) {
      store.notify('生成图片失败，请重试', 'error')
      return
    }
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `tsumugi-journey-${selectedYear.value}-${selectedRatio.value}.png`
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1500)
    store.notify('已导出历程拼图 PNG', 'success')
  } catch {
    store.notify('导出图片失败', 'error')
  } finally {
    exporting.value = false
  }
}

watch([selectedYear, selectedCollectionId], () => {
  void fetchCollage()
})

watch([selectedRatio, layoutMode, showLabels, includeUnplayed, hideNsfw], () => {
  if (!loading.value && !errorMsg.value) {
    void renderCanvas()
  }
})

onMounted(() => {
  void fetchCollage()
})
</script>

<template>
  <div class="collage-panel">
    <!-- 顶部极简控制栏 -->
    <div class="collage-toolbar">
      <div class="toolbar-row">
        <div class="control-group">
          <span class="control-label">时间范围</span>
          <div class="pill-segment">
            <button
              type="button"
              class="seg-btn"
              :class="{ active: selectedYear === 'all' }"
              @click="selectedYear = 'all'"
            >
              全部历程
            </button>
            <button
              v-for="yr in availableYears"
              :key="yr"
              type="button"
              class="seg-btn tabular-nums"
              :class="{ active: selectedYear === yr }"
              @click="selectedYear = yr"
            >
              {{ yr }} 年度
            </button>
          </div>
        </div>

        <div v-if="store.collections.length > 0" class="control-group">
          <span class="control-label">分组</span>
          <select
            class="compact-select"
            :value="selectedCollectionId ?? ''"
            @change="
              selectedCollectionId = ($event.target as HTMLSelectElement).value
                ? Number(($event.target as HTMLSelectElement).value)
                : null
            "
          >
            <option value="">全部分组</option>
            <option v-for="col in store.collections" :key="col.id" :value="col.id">
              {{ col.name }}
            </option>
          </select>
        </div>

        <div class="control-group">
          <span class="control-label">画幅</span>
          <div class="pill-segment">
            <button
              v-for="preset in RATIO_PRESETS"
              :key="preset.key"
              type="button"
              class="seg-btn"
              :class="{ active: selectedRatio === preset.key }"
              :title="preset.dimLabel"
              @click="selectedRatio = preset.key"
            >
              {{ preset.label }}
            </button>
          </div>
        </div>

        <div class="toolbar-spacer" />

        <button
          type="button"
          class="export-cta"
          :disabled="!canExport"
          @click="exportPng"
        >
          <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M10 3.5v8.5m0 0l-3.2-3.2M10 12l3.2-3.2M4 15.5h12" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span>{{ exporting ? '导出中…' : '导出 PNG' }}</span>
        </button>
      </div>

      <div class="toolbar-row secondary-row">
        <div class="pill-segment subtle">
          <button
            type="button"
            class="seg-btn"
            :class="{ active: layoutMode === 'poster' }"
            @click="layoutMode = 'poster'"
          >
            典藏海报
          </button>
          <button
            type="button"
            class="seg-btn"
            :class="{ active: layoutMode === 'pure' }"
            @click="layoutMode = 'pure'"
          >
            纯净拼图
          </button>
        </div>

        <label class="toggle-chip">
          <input v-model="showLabels" type="checkbox" />
          <span>显示标题与时长</span>
        </label>

        <label class="toggle-chip">
          <input
            type="checkbox"
            :checked="includeUnplayed"
            @change="toggleIncludeUnplayed(($event.target as HTMLInputElement).checked)"
          />
          <span>包含未游玩作品</span>
        </label>

        <label class="toggle-chip">
          <input v-model="hideNsfw" type="checkbox" />
          <span>隐藏成人向 (R18)</span>
        </label>

        <div class="toolbar-spacer" />

        <span class="meta-hint tabular-nums">
          {{ resolvedWidth }}×{{ resolvedHeight }}
          <template v-if="resolvedGridText"> · {{ resolvedGridText }} 网格</template>
          · {{ displayedItems.length }} 部作品
        </span>
      </div>
    </div>

    <!-- 画布实时预览舞台 -->
    <div class="collage-stage">
      <div v-if="loading" class="stage-state">
        <div class="spinner" />
        <span>正在生成历程拼图…</span>
      </div>

      <div v-else-if="errorMsg" class="stage-state error">
        <span>{{ errorMsg }}</span>
      </div>

      <div v-else-if="displayedItems.length === 0" class="stage-state">
        <span class="empty-title">当前筛选条件下暂无可拼图作品</span>
        <button
          v-if="hiddenUnplayedAvailable"
          type="button"
          class="ghost-action-btn"
          @click="toggleIncludeUnplayed(true)"
        >
          包含未游玩作品
        </button>
      </div>

      <div v-else class="canvas-frame" :class="`ratio-${selectedRatio}`">
        <canvas ref="canvasRef" class="collage-canvas" />
        <div v-if="rendering" class="render-badge">渲染中…</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.collage-panel {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 18px 26px 24px;
  gap: 16px;
  overflow-y: auto;
}

.collage-toolbar {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.028);
  box-shadow: inset 0 1px 0 var(--divider-subtle);
  flex-shrink: 0;
}

.toolbar-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.secondary-row {
  padding-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.055);
}

.control-group {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.control-label {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}

.pill-segment {
  display: inline-flex;
  align-items: center;
  padding: 2px;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.045);
  gap: 2px;
}

.pill-segment.subtle {
  background: rgba(255, 255, 255, 0.035);
}

.seg-btn {
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 5px 10px;
  line-height: 1.25;
  cursor: pointer;
  transition: background 0.16s ease, color 0.16s ease;
  white-space: nowrap;
}

.seg-btn:hover {
  color: var(--text-primary);
}

.seg-btn.active {
  background: rgba(255, 255, 255, 0.14);
  color: #f5f5f7;
  font-weight: 500;
}

.compact-select {
  height: 29px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.09);
  background: rgba(20, 20, 24, 0.9);
  color: var(--text-primary);
  font-size: 12px;
  outline: none;
  cursor: pointer;
}

.compact-select:focus {
  border-color: rgba(255, 255, 255, 0.24);
}

.toggle-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
  padding: 3px 6px;
  border-radius: 7px;
  transition: color 0.15s ease, background 0.15s ease;
}

.toggle-chip:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.04);
}

.toggle-chip input[type='checkbox'] {
  accent-color: #f5f5f7;
  width: 13.5px;
  height: 13.5px;
  cursor: pointer;
}

.toolbar-spacer {
  flex: 1;
  min-width: 8px;
}

.meta-hint {
  font-size: 11.5px;
  color: var(--text-muted);
}

.export-cta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 15px;
  border: none;
  border-radius: 9px;
  background: #f5f5f7;
  color: #0a0a0c;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.16s ease, transform 0.16s ease;
  white-space: nowrap;
}

.export-cta:hover:not(:disabled) {
  opacity: 0.92;
}

.export-cta:active:not(:disabled) {
  transform: scale(0.985);
}

.export-cta:disabled {
  opacity: 0.36;
  cursor: not-allowed;
}

/* 预览舞台 */
.collage-stage {
  flex: 1;
  min-height: 360px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 16px;
  background: rgba(0, 0, 0, 0.34);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
  padding: 18px;
  overflow: hidden;
}

.canvas-frame {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  max-width: 100%;
  max-height: 100%;
  border-radius: 10px;
  overflow: hidden;
  box-shadow:
    0 20px 50px rgba(0, 0, 0, 0.58),
    0 0 0 1px rgba(255, 255, 255, 0.08);
  background: #0a0a0c;
}

.canvas-frame.ratio-adaptive {
  max-width: min(100%, 980px);
  max-height: min(60vh, 560px);
}

.canvas-frame.ratio-adaptive .collage-canvas {
  width: auto;
  height: auto;
  max-width: 100%;
  max-height: min(60vh, 560px);
}

.canvas-frame.ratio-16x9 {
  width: 100%;
  max-width: 960px;
}

.canvas-frame.ratio-3x4 {
  height: min(60vh, 560px);
  aspect-ratio: 3 / 4;
}

.canvas-frame.ratio-1x1 {
  height: min(58vh, 540px);
  aspect-ratio: 1 / 1;
}

.collage-canvas {
  display: block;
  width: 100%;
  height: auto;
  max-height: 100%;
  object-fit: contain;
}

.canvas-frame.ratio-3x4 .collage-canvas,
.canvas-frame.ratio-1x1 .collage-canvas {
  width: 100%;
  height: 100%;
}

.render-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(10, 10, 12, 0.72);
  backdrop-filter: blur(8px);
  color: rgba(245, 245, 247, 0.85);
  font-size: 11px;
  pointer-events: none;
}

.stage-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-secondary);
  font-size: 13px;
}

.stage-state.error {
  color: var(--danger-text);
}

.empty-title {
  color: var(--text-muted);
}

.ghost-action-btn {
  padding: 6px 14px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-primary);
  font-size: 12.5px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.ghost-action-btn:hover {
  background: rgba(255, 255, 255, 0.11);
}

.spinner {
  width: 22px;
  height: 22px;
  border: 2px solid rgba(255, 255, 255, 0.14);
  border-top-color: #f4f4f5;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
