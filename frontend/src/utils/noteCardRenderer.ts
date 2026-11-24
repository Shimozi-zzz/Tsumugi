import type { Game, GameNote, RatingDimensionKey } from '@/types'
import { formatPlaytimeText } from '@/utils/noteDocExport'

export interface NoteCardRenderOptions {
  game: Game
  notes: GameNote[]
  coverSrc: string
  playSeconds: number
  maskSpoilers: boolean
  blurCover: boolean
  showRatings: boolean
  showWatermark: boolean
}

const SANS_FONT =
  '"Noto Sans SC", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif'
const SERIF_FONT =
  '"Cormorant Garamond", "Noto Serif SC", "Songti SC", Georgia, serif'
const MONO_FONT =
  '"JetBrains Mono", "SFMono-Regular", ui-monospace, Menlo, monospace'

const RATING_DIMENSIONS: Array<{ key: RatingDimensionKey; label: string }> = [
  { key: 'story', label: '剧本' },
  { key: 'visual', label: '美术与演出' },
  { key: 'music', label: '音乐' },
  { key: 'atmosphere', label: '氛围与体验' },
]

const NOTE_TYPE_LABELS: Record<string, { label: string; bg: string; fg: string }> = {
  work: { label: '作品总评', bg: 'rgba(16, 185, 129, 0.16)', fg: '#6ee7b7' },
  character: { label: '角色手记', bg: 'rgba(245, 158, 11, 0.16)', fg: '#fcd34d' },
  misc: { label: '游玩随记', bg: 'rgba(255, 255, 255, 0.09)', fg: '#d4d4d8' },
}

const STATUS_LABELS: Record<string, string> = {
  todo: '未开始',
  unplayed: '未开始',
  playing: '攻略中',
  done: '已通关',
  completed: '已通关',
}

interface InlineRun {
  kind: 'text' | 'bold' | 'code' | 'spoiler'
  text: string
}

interface MeasuredLine {
  runs: Array<{ kind: InlineRun['kind']; text: string; width: number }>
  totalWidth: number
}

type MdBlock =
  | { type: 'heading'; level: number; runs: InlineRun[] }
  | { type: 'paragraph'; runs: InlineRun[] }
  | { type: 'quote'; lines: InlineRun[][] }
  | { type: 'list'; ordered: boolean; items: InlineRun[][] }
  | { type: 'code'; lines: string[] }
  | { type: 'hr' }
  | { type: 'spoiler_box'; summary: string; body: MdBlock[] }

function loadImage(url: string): Promise<HTMLImageElement | null> {
  if (!url) return Promise.resolve(null)
  return new Promise((resolve) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.decoding = 'async'
    img.onload = () => {
      if (img.naturalWidth > 0 && img.naturalHeight > 0) resolve(img)
      else resolve(null)
    }
    img.onerror = () => resolve(null)
    img.src = url
  })
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
) {
  const iw = img.naturalWidth
  const ih = img.naturalHeight
  if (iw <= 0 || ih <= 0) return
  const imgRatio = iw / ih
  const boxRatio = dw / dh
  let sx = 0
  let sy = 0
  let sw = iw
  let sh = ih
  if (imgRatio > boxRatio) {
    sw = ih * boxRatio
    sx = (iw - sw) * 0.5
  } else {
    sh = iw / boxRatio
    sy = (ih - sh) * 0.28
  }
  ctx.drawImage(img, sx, sy, sw, sh, dx, dy, dw, dh)
}

function parseInlineRuns(raw: string, maskSpoilers: boolean): InlineRun[] {
  const tokens: InlineRun[] = []
  const pattern =
    /(`[^`\n]+`|>![\s\S]+?!<|\|\|[^|\n]+?\|\||\*\*[^*\n]+\*\*|__[^_\n]+__|\[[^\]\n]+\]\([^)\s]+\))/g
  let lastIndex = 0
  let match: RegExpExecArray | null

  const pushPlain = (txt: string) => {
    if (!txt) return
    const cleaned = txt.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1$2').replace(/~~([^~\n]+)~~/g, '$1')
    if (cleaned) tokens.push({ kind: 'text', text: cleaned })
  }

  while ((match = pattern.exec(raw)) !== null) {
    if (match.index > lastIndex) {
      pushPlain(raw.slice(lastIndex, match.index))
    }
    const seg = match[0]
    if (seg.startsWith('`') && seg.endsWith('`')) {
      tokens.push({ kind: 'code', text: seg.slice(1, -1) })
    } else if (seg.startsWith('>!') && seg.endsWith('!<')) {
      const inner = seg.slice(2, -2).trim()
      tokens.push(
        maskSpoilers
          ? { kind: 'spoiler', text: ' '.repeat(Math.max(4, Math.min(12, Math.ceil(inner.length * 0.6)))) }
          : { kind: 'text', text: inner },
      )
    } else if (seg.startsWith('||') && seg.endsWith('||')) {
      const inner = seg.slice(2, -2).trim()
      tokens.push(
        maskSpoilers
          ? { kind: 'spoiler', text: ' '.repeat(Math.max(4, Math.min(12, Math.ceil(inner.length * 0.6)))) }
          : { kind: 'text', text: inner },
      )
    } else if ((seg.startsWith('**') && seg.endsWith('**')) || (seg.startsWith('__') && seg.endsWith('__'))) {
      tokens.push({ kind: 'bold', text: seg.slice(2, -2) })
    } else if (seg.startsWith('[')) {
      const m = seg.match(/^\[([^\]\n]+)\]/)
      tokens.push({ kind: 'text', text: m?.[1] || seg })
    } else {
      pushPlain(seg)
    }
    lastIndex = pattern.lastIndex
  }
  if (lastIndex < raw.length) {
    pushPlain(raw.slice(lastIndex))
  }
  return tokens
}

function parseMarkdownBlocks(md: string, maskSpoilers: boolean): MdBlock[] {
  const source = (md || '').replace(/\r\n/g, '\n')
  if (!source.trim()) {
    return [{ type: 'paragraph', runs: [{ kind: 'text', text: '（暂无正文内容）' }] }]
  }

  const stashedDetails: Array<{ summary: string; body: MdBlock[] }> = []
  const normalized = source.replace(
    /<details\b[^>]*>([\s\S]*?)<\/details>/gi,
    (_m, inner: string) => {
      let summary = '剧透内容'
      const bodyRaw = inner.replace(/<summary\b[^>]*>([\s\S]*?)<\/summary>/i, (_sm, s: string) => {
        const clean = s.trim()
        if (clean) summary = clean
        return ''
      })
      const idx = stashedDetails.length
      stashedDetails.push({
        summary,
        body: parsePlainBlocks(bodyRaw.trim(), maskSpoilers),
      })
      return `\n\n@@TSUMUGI_CARD_DETAILS_${idx}@@\n\n`
    },
  )

  const blocks = parsePlainBlocks(normalized, maskSpoilers)
  const finalBlocks: MdBlock[] = []
  for (const blk of blocks) {
    if (blk.type === 'paragraph' && blk.runs.length === 1 && blk.runs[0].kind === 'text') {
      const m = blk.runs[0].text.trim().match(/^@@TSUMUGI_CARD_DETAILS_(\d+)@@$/)
      if (m) {
        const stashed = stashedDetails[Number(m[1])]
        if (stashed) {
          finalBlocks.push({ type: 'spoiler_box', summary: stashed.summary, body: stashed.body })
          continue
        }
      }
    }
    finalBlocks.push(blk)
  }
  return finalBlocks
}

function parsePlainBlocks(src: string, maskSpoilers: boolean): MdBlock[] {
  const lines = src.split('\n')
  const blocks: MdBlock[] = []
  let i = 0

  while (i < lines.length) {
    const trimmed = lines[i].trim()
    if (!trimmed) {
      i++
      continue
    }

    if (trimmed.startsWith('```')) {
      const codeLines: string[] = []
      i++
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i])
        i++
      }
      if (i < lines.length) i++
      blocks.push({ type: 'code', lines: codeLines.length ? codeLines : [''] })
      continue
    }

    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      blocks.push({ type: 'hr' })
      i++
      continue
    }

    const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)$/)
    if (headingMatch) {
      blocks.push({
        type: 'heading',
        level: headingMatch[1].length,
        runs: parseInlineRuns(headingMatch[2], maskSpoilers),
      })
      i++
      continue
    }

    if (trimmed.startsWith('>') && !trimmed.startsWith('>!')) {
      const quoteLines: InlineRun[][] = []
      while (i < lines.length) {
        const qt = lines[i].trim()
        if (qt.startsWith('>') && !qt.startsWith('>!')) {
          quoteLines.push(parseInlineRuns(qt.replace(/^>\s?/, ''), maskSpoilers))
          i++
        } else {
          break
        }
      }
      blocks.push({ type: 'quote', lines: quoteLines })
      continue
    }

    if (/^[-*+]\s+/.test(trimmed)) {
      const items: InlineRun[][] = []
      while (i < lines.length && /^[-*+]\s+/.test(lines[i].trim())) {
        items.push(parseInlineRuns(lines[i].trim().replace(/^[-*+]\s+/, ''), maskSpoilers))
        i++
      }
      blocks.push({ type: 'list', ordered: false, items })
      continue
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      const items: InlineRun[][] = []
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(parseInlineRuns(lines[i].trim().replace(/^\d+\.\s+/, ''), maskSpoilers))
        i++
      }
      blocks.push({ type: 'list', ordered: true, items })
      continue
    }

    const paraLines: InlineRun[][] = []
    while (i < lines.length) {
      const cur = lines[i].trim()
      if (
        !cur ||
        cur.startsWith('```') ||
        /^(?:-{3,}|\*{3,}|_{3,})$/.test(cur) ||
        /^#{1,4}\s+/.test(cur) ||
        (cur.startsWith('>') && !cur.startsWith('>!')) ||
        /^[-*+]\s+/.test(cur) ||
        /^\d+\.\s+/.test(cur)
      ) {
        break
      }
      paraLines.push(parseInlineRuns(cur, maskSpoilers))
      i++
    }
    const mergedRuns: InlineRun[] = []
    paraLines.forEach((lr, idx) => {
      if (idx > 0) mergedRuns.push({ kind: 'text', text: ' ' })
      mergedRuns.push(...lr)
    })
    blocks.push({ type: 'paragraph', runs: mergedRuns })
  }

  return blocks
}

function wrapPlainText(
  ctx: CanvasRenderingContext2D,
  text: string,
  font: string,
  maxWidth: number,
  maxLines?: number,
): string[] {
  ctx.font = font
  const clean = (text || '').trim()
  if (!clean) return []
  const lines: string[] = []
  let current = ''

  for (const ch of Array.from(clean)) {
    const next = current + ch
    if (ctx.measureText(next).width <= maxWidth) {
      current = next
    } else {
      if (current) lines.push(current)
      current = ch
      if (maxLines && lines.length >= maxLines) {
        break
      }
    }
  }
  if (current && (!maxLines || lines.length < maxLines)) {
    lines.push(current)
  }
  if (maxLines && lines.length === maxLines) {
    const consumedLen = lines.join('').length
    if (consumedLen < Array.from(clean).length) {
      let last = lines[maxLines - 1]
      while (last.length > 1 && ctx.measureText(`${last}…`).width > maxWidth) {
        last = last.slice(0, -1)
      }
      lines[maxLines - 1] = `${last}…`
    }
  }
  return lines
}

function splitRunUnits(text: string): string[] {
  // 对连续 ASCII 词按词切分，CJK 按字切分，保证中英混排换行自然
  const matches = text.match(/[A-Za-z0-9_.-]+|\s+|[\s\S]/g)
  return matches || [text]
}

function fontForRun(kind: InlineRun['kind'], baseSize: number, baseFamily: string, baseWeight = 400): string {
  if (kind === 'bold') return `600 ${baseSize}px ${baseFamily}`
  if (kind === 'code') return `500 ${Math.max(11, baseSize - 1.5)}px ${MONO_FONT}`
  return `${baseWeight} ${baseSize}px ${baseFamily}`
}

function wrapInlineRuns(
  ctx: CanvasRenderingContext2D,
  runs: InlineRun[],
  maxWidth: number,
  baseSize: number,
  baseFamily: string,
  baseWeight = 400,
): MeasuredLine[] {
  const lines: MeasuredLine[] = []
  let curRuns: MeasuredLine['runs'] = []
  let curW = 0

  const flushLine = () => {
    lines.push({ runs: curRuns, totalWidth: curW })
    curRuns = []
    curW = 0
  }

  const pushChunk = (kind: InlineRun['kind'], text: string) => {
    ctx.font = fontForRun(kind, baseSize, baseFamily, baseWeight)
    const extraW = kind === 'code' ? 10 : kind === 'spoiler' ? 8 : 0
    const unitW = ctx.measureText(text).width + extraW
    if (curW > 0 && curW + unitW > maxWidth) {
      flushLine()
      if (/^\s+$/.test(text) && kind === 'text') return
    }
    const last = curRuns[curRuns.length - 1]
    if (last && last.kind === kind && kind !== 'code' && kind !== 'spoiler') {
      last.text += text
      last.width += unitW
    } else {
      curRuns.push({ kind, text, width: unitW })
    }
    curW += unitW
  }

  for (const run of runs) {
    if (run.kind === 'spoiler') {
      pushChunk('spoiler', run.text)
      continue
    }
    const units = splitRunUnits(run.text)
    for (const unit of units) {
      ctx.font = fontForRun(run.kind, baseSize, baseFamily, baseWeight)
      const w = ctx.measureText(unit).width
      if (w > maxWidth && unit.length > 1) {
        for (const ch of Array.from(unit)) {
          pushChunk(run.kind, ch)
        }
      } else {
        pushChunk(run.kind, unit)
      }
    }
  }
  if (curRuns.length > 0 || lines.length === 0) {
    flushLine()
  }
  return lines
}

function drawMeasuredLines(
  ctx: CanvasRenderingContext2D,
  lines: MeasuredLine[],
  x: number,
  startY: number,
  lineHeight: number,
  baseSize: number,
  baseFamily: string,
  textColor: string,
  boldColor: string,
  baseWeight = 400,
): number {
  let y = startY
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'

  for (const line of lines) {
    let cx = x
    const midY = y + lineHeight / 2
    for (const run of line.runs) {
      if (run.kind === 'spoiler') {
        const bw = Math.max(36, run.width)
        const bh = baseSize + 5
        ctx.save()
        traceRoundedRect(ctx, cx + 1, midY - bh / 2, bw - 2, bh, 4)
        ctx.fillStyle = 'rgba(255, 255, 255, 0.16)'
        ctx.fill()
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.12)'
        ctx.lineWidth = 1
        ctx.stroke()
        ctx.restore()
        cx += run.width
        continue
      }

      if (run.kind === 'code') {
        const bh = baseSize + 5
        ctx.save()
        traceRoundedRect(ctx, cx + 1, midY - bh / 2, run.width - 2, bh, 4)
        ctx.fillStyle = 'rgba(255, 255, 255, 0.08)'
        ctx.fill()
        ctx.font = fontForRun('code', baseSize, baseFamily, baseWeight)
        ctx.fillStyle = '#e4e4e7'
        ctx.fillText(run.text, cx + 5, midY)
        ctx.restore()
        cx += run.width
        continue
      }

      ctx.font = fontForRun(run.kind, baseSize, baseFamily, baseWeight)
      ctx.fillStyle = run.kind === 'bold' ? boldColor : textColor
      ctx.fillText(run.text, cx, midY)
      cx += run.width
    }
    y += lineHeight
  }
  return y
}

function formatDateDot(): string {
  const d = new Date()
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`
}

function releaseYearOf(raw?: string | null): string {
  const m = (raw || '').match(/\d{4}/)
  return m ? m[0] : ''
}

function drawOrMeasureBlocks(
  ctx: CanvasRenderingContext2D,
  blocks: MdBlock[],
  x: number,
  startY: number,
  maxWidth: number,
  draw: boolean,
  maskSpoilers: boolean,
): number {
  let y = startY

  for (let bIdx = 0; bIdx < blocks.length; bIdx++) {
    const blk = blocks[bIdx]

    if (blk.type === 'hr') {
      y += 6
      if (draw) {
        ctx.fillStyle = 'rgba(255, 255, 255, 0.08)'
        ctx.fillRect(x, y, maxWidth, 1)
      }
      y += 16
      continue
    }

    if (blk.type === 'heading') {
      const size = blk.level <= 1 ? 19 : blk.level === 2 ? 17 : 15
      const lh = size + 10
      if (bIdx > 0) y += 6
      const lines = wrapInlineRuns(ctx, blk.runs, maxWidth, size, SERIF_FONT, 600)
      if (draw) {
        drawMeasuredLines(ctx, lines, x, y, lh, size, SERIF_FONT, '#f5f5f7', '#ffffff', 600)
      }
      y += lines.length * lh
      if (blk.level === 2) {
        y += 4
        if (draw) {
          ctx.fillStyle = 'rgba(255, 255, 255, 0.08)'
          ctx.fillRect(x, y, maxWidth, 1)
        }
        y += 10
      } else {
        y += 6
      }
      continue
    }

    if (blk.type === 'paragraph') {
      const lines = wrapInlineRuns(ctx, blk.runs, maxWidth, 14.5, SANS_FONT, 400)
      if (draw) {
        drawMeasuredLines(
          ctx,
          lines,
          x,
          y,
          25,
          14.5,
          SANS_FONT,
          'rgba(244, 244, 245, 0.88)',
          '#ffffff',
          400,
        )
      }
      y += lines.length * 25 + 10
      continue
    }

    if (blk.type === 'quote') {
      const qPadX = 14
      const qPadY = 10
      const qLineH = 23
      const measuredLinesList = blk.lines.map((q) =>
        wrapInlineRuns(ctx, q, maxWidth - qPadX - 12, 13.5, SANS_FONT, 400),
      )
      const totalLines = measuredLinesList.reduce((acc, l) => acc + l.length, 0)
      const boxH = qPadY * 2 + totalLines * qLineH

      if (draw) {
        ctx.save()
        traceRoundedRect(ctx, x, y, maxWidth, boxH, 8)
        ctx.fillStyle = 'rgba(255, 255, 255, 0.032)'
        ctx.fill()
        ctx.fillStyle = 'rgba(255, 255, 255, 0.28)'
        ctx.fillRect(x, y + 6, 2.5, Math.max(12, boxH - 12))
        let qy = y + qPadY
        for (const mLines of measuredLinesList) {
          qy = drawMeasuredLines(
            ctx,
            mLines,
            x + qPadX,
            qy,
            qLineH,
            13.5,
            SANS_FONT,
            'rgba(212, 212, 216, 0.9)',
            '#f4f4f5',
            400,
          )
        }
        ctx.restore()
      }
      y += boxH + 12
      continue
    }

    if (blk.type === 'list') {
      const indent = 20
      const lh = 24
      for (let itemIdx = 0; itemIdx < blk.items.length; itemIdx++) {
        const marker = blk.ordered ? `${itemIdx + 1}.` : '•'
        const lines = wrapInlineRuns(ctx, blk.items[itemIdx], maxWidth - indent, 14, SANS_FONT, 400)
        if (draw) {
          ctx.font = `500 13px ${MONO_FONT}`
          ctx.fillStyle = 'rgba(244, 244, 245, 0.5)'
          ctx.textAlign = 'left'
          ctx.textBaseline = 'middle'
          ctx.fillText(marker, x + 2, y + lh / 2)
          drawMeasuredLines(
            ctx,
            lines,
            x + indent,
            y,
            lh,
            14,
            SANS_FONT,
            'rgba(244, 244, 245, 0.88)',
            '#ffffff',
            400,
          )
        }
        y += lines.length * lh + 3
      }
      y += 9
      continue
    }

    if (blk.type === 'code') {
      const padY = 10
      const lh = 20
      const wrappedCode: string[] = []
      for (const rawLine of blk.lines) {
        const pieces = wrapPlainText(ctx, rawLine || ' ', `400 12.5px ${MONO_FONT}`, maxWidth - 28)
        wrappedCode.push(...(pieces.length ? pieces : [' ']))
      }
      const boxH = padY * 2 + wrappedCode.length * lh
      if (draw) {
        ctx.save()
        traceRoundedRect(ctx, x, y, maxWidth, boxH, 8)
        ctx.fillStyle = 'rgba(0, 0, 0, 0.38)'
        ctx.fill()
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)'
        ctx.lineWidth = 1
        ctx.stroke()
        ctx.font = `400 12.5px ${MONO_FONT}`
        ctx.fillStyle = '#d4d4d8'
        ctx.textAlign = 'left'
        ctx.textBaseline = 'middle'
        let cy = y + padY
        for (const cl of wrappedCode) {
          ctx.fillText(cl, x + 14, cy + lh / 2)
          cy += lh
        }
        ctx.restore()
      }
      y += boxH + 12
      continue
    }

    if (blk.type === 'spoiler_box') {
      if (maskSpoilers) {
        const boxH = 38
        if (draw) {
          ctx.save()
          traceRoundedRect(ctx, x, y, maxWidth, boxH, 8)
          ctx.fillStyle = 'rgba(255, 255, 255, 0.04)'
          ctx.fill()
          ctx.strokeStyle = 'rgba(255, 255, 255, 0.09)'
          ctx.lineWidth = 1
          ctx.stroke()
          ctx.font = `500 12.5px ${SANS_FONT}`
          ctx.fillStyle = 'rgba(244, 244, 245, 0.65)'
          ctx.textAlign = 'left'
          ctx.textBaseline = 'middle'
          ctx.fillText(`剧透内容已遮蔽 · ${blk.summary}`, x + 14, y + boxH / 2)
          ctx.restore()
        }
        y += boxH + 12
      } else {
        const innerStartY = y + 32
        const innerEndY = drawOrMeasureBlocks(
          ctx,
          blk.body,
          x + 14,
          innerStartY,
          maxWidth - 28,
          false,
          false,
        )
        const boxH = innerEndY - y + 6
        if (draw) {
          ctx.save()
          traceRoundedRect(ctx, x, y, maxWidth, boxH, 8)
          ctx.fillStyle = 'rgba(255, 255, 255, 0.03)'
          ctx.fill()
          ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)'
          ctx.lineWidth = 1
          ctx.stroke()
          ctx.font = `500 12.5px ${SANS_FONT}`
          ctx.fillStyle = '#fcd34d'
          ctx.textAlign = 'left'
          ctx.textBaseline = 'middle'
          ctx.fillText(blk.summary, x + 14, y + 16)
          ctx.restore()
          drawOrMeasureBlocks(ctx, blk.body, x + 14, innerStartY, maxWidth - 28, true, false)
        }
        y += boxH + 12
      }
    }
  }

  return y
}

/**
 * 渲染暗夜杂志风手记分享长图（Canvas 2x DPI）。
 */
export async function renderNoteShareCard(
  canvas: HTMLCanvasElement,
  opts: NoteCardRenderOptions,
): Promise<{ width: number; height: number }> {
  const W = 900
  const DPR = 2
  const padX = 48
  const innerW = W - padX * 2
  const coverW = 168
  const coverH = 238
  const rightX = padX + coverW + 28
  const rightW = innerW - coverW - 28

  const coverImg = opts.coverSrc ? await loadImage(opts.coverSrc) : null

  const measureCtx = canvas.getContext('2d')
  if (!measureCtx) {
    throw new Error('无法初始化图片画布')
  }

  const game = opts.game
  const statusKey = (game.status || 'todo').trim().toLowerCase()
  const statusLabel = STATUS_LABELS[statusKey] || '未开始'
  const playtimeText = formatPlaytimeText(opts.playSeconds)
  const yearText = releaseYearOf(game.release_date)

  const titleLines = wrapPlainText(measureCtx, game.title, `600 28px ${SERIF_FONT}`, rightW, 2)
  const subTitle =
    (game.sub_title || '').trim() && game.sub_title.trim() !== game.title.trim()
      ? game.sub_title.trim()
      : ''

  const metaParts: string[] = []
  if ((game.developer || '').trim()) metaParts.push(game.developer.trim())
  if (yearText) metaParts.push(yearText)
  metaParts.push(statusLabel)
  metaParts.push(`已游玩 ${playtimeText}`)
  const metaLine = metaParts.join('  ·  ')

  const dims = game.rating_dimensions || {}
  const dimEntries = RATING_DIMENSIONS.filter((d) => dims[d.key] != null).map((d) => ({
    label: d.label,
    score: Number(dims[d.key]),
  }))
  const hasRatings =
    opts.showRatings && (game.rating_overall != null || dimEntries.length > 0)
  const rawShortReview = (game.short_review || '').trim()
  const shortReview = opts.showRatings && rawShortReview ? rawShortReview : ''
  const shortReviewLines = shortReview
    ? wrapPlainText(measureCtx, shortReview, `400 13.5px ${SANS_FONT}`, rightW - 22, 3)
    : []

  const parsedNotes = opts.notes.map((n) => ({
    note: n,
    titleLines: wrapPlainText(
      measureCtx,
      n.title || NOTE_TYPE_LABELS[n.note_type]?.label || '手记',
      `600 20px ${SERIF_FONT}`,
      innerW - 76,
      2,
    ),
    blocks: parseMarkdownBlocks(n.content_md || '', opts.maskSpoilers),
  }))

  const layoutHeader = (ctx: CanvasRenderingContext2D, draw: boolean): number => {
    const topY = 44
    if (draw) {
      ctx.save()
      ctx.shadowColor = 'rgba(0, 0, 0, 0.55)'
      ctx.shadowBlur = 24
      ctx.shadowOffsetY = 10
      traceRoundedRect(ctx, padX, topY, coverW, coverH, 10)
      ctx.fillStyle = '#141418'
      ctx.fill()
      ctx.restore()

      ctx.save()
      traceRoundedRect(ctx, padX, topY, coverW, coverH, 10)
      ctx.clip()
      if (coverImg) {
        if (opts.blurCover) {
          ctx.filter = 'blur(14px)'
          drawCoverImage(ctx, coverImg, padX - 10, topY - 10, coverW + 20, coverH + 20)
          ctx.filter = 'none'
        } else {
          drawCoverImage(ctx, coverImg, padX, topY, coverW, coverH)
        }
      } else {
        ctx.fillStyle = '#18181d'
        ctx.fillRect(padX, topY, coverW, coverH)
        ctx.font = `600 18px ${SERIF_FONT}`
        ctx.fillStyle = 'rgba(244, 244, 245, 0.55)'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(game.title.slice(0, 6), padX + coverW / 2, topY + coverH / 2)
      }
      ctx.restore()

      ctx.save()
      traceRoundedRect(ctx, padX + 0.5, topY + 0.5, coverW - 1, coverH - 1, 10)
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.14)'
      ctx.lineWidth = 1
      ctx.stroke()
      ctx.restore()
    }

    let ry = topY + 2
    if (draw) {
      ctx.font = `600 28px ${SERIF_FONT}`
      ctx.fillStyle = '#f5f5f7'
      ctx.textAlign = 'left'
      ctx.textBaseline = 'middle'
      for (const tl of titleLines) {
        ctx.fillText(tl, rightX, ry + 17)
        ry += 35
      }
    } else {
      ry += titleLines.length * 35
    }

    if (subTitle) {
      if (draw) {
        ctx.font = `400 13px ${SANS_FONT}`
        ctx.fillStyle = 'rgba(244, 244, 245, 0.5)'
        const subLines = wrapPlainText(ctx, subTitle, `400 13px ${SANS_FONT}`, rightW, 1)
        ctx.fillText(subLines[0] || '', rightX, ry + 11)
      }
      ry += 22
    }

    if (draw) {
      ctx.font = `400 12.5px ${SANS_FONT}`
      ctx.fillStyle = 'rgba(244, 244, 245, 0.68)'
      const metaFitted = wrapPlainText(ctx, metaLine, `400 12.5px ${SANS_FONT}`, rightW, 1)
      ctx.fillText(metaFitted[0] || '', rightX, ry + 14)
    }
    ry += 28

    if (hasRatings) {
      ry += 8
      if (draw) {
        ctx.save()
        ctx.textAlign = 'left'
        ctx.textBaseline = 'middle'
        if (game.rating_overall != null) {
          ctx.font = `600 18px ${SANS_FONT}`
          ctx.fillStyle = '#fcd34d'
          ctx.fillText('★', rightX, ry + 15)

          const scoreStr = Number(game.rating_overall).toFixed(1)
          ctx.font = `600 26px ${SERIF_FONT}`
          ctx.fillStyle = '#f5f5f7'
          ctx.fillText(scoreStr, rightX + 24, ry + 15)
          const sw = ctx.measureText(scoreStr).width

          ctx.font = `500 12px ${MONO_FONT}`
          ctx.fillStyle = 'rgba(244, 244, 245, 0.48)'
          ctx.fillText('/ 10', rightX + 24 + sw + 6, ry + 18)
        }
        ctx.restore()
      }
      if (game.rating_overall != null) {
        ry += 34
      }

      if (dimEntries.length > 0) {
        const colGap = 24
        const colW = (rightW - colGap) / 2
        const rows = Math.ceil(dimEntries.length / 2)
        if (draw) {
          for (let dIdx = 0; dIdx < dimEntries.length; dIdx++) {
            const col = dIdx % 2
            const row = Math.floor(dIdx / 2)
            const dx = rightX + col * (colW + colGap)
            const dy = ry + row * 24

            const item = dimEntries[dIdx]
            ctx.font = `400 12px ${SANS_FONT}`
            ctx.fillStyle = 'rgba(244, 244, 245, 0.68)'
            ctx.textAlign = 'left'
            ctx.textBaseline = 'middle'
            ctx.fillText(item.label, dx, dy + 10)

            const valStr = item.score.toFixed(1)
            ctx.font = `500 12px ${MONO_FONT}`
            ctx.fillStyle = '#e4e4e7'
            ctx.textAlign = 'right'
            ctx.fillText(valStr, dx + colW, dy + 10)

            const barX = dx + 74
            const barW = Math.max(40, colW - 74 - 34)
            const barY = dy + 8
            ctx.fillStyle = 'rgba(255, 255, 255, 0.09)'
            traceRoundedRect(ctx, barX, barY, barW, 4, 2)
            ctx.fill()

            const fillRatio = Math.max(0, Math.min(1, item.score / 10))
            const fillGrad = ctx.createLinearGradient(barX, barY, barX + barW, barY)
            fillGrad.addColorStop(0, 'rgba(244, 244, 245, 0.58)')
            fillGrad.addColorStop(1, 'rgba(252, 211, 77, 0.9)')
            ctx.fillStyle = fillGrad
            traceRoundedRect(ctx, barX, barY, Math.max(4, barW * fillRatio), 4, 2)
            ctx.fill()
          }
        }
        ry += rows * 24 + 4
      }
    }

    if (shortReviewLines.length > 0) {
      ry += 8
      const qH = 14 + shortReviewLines.length * 21
      if (draw) {
        ctx.save()
        traceRoundedRect(ctx, rightX, ry, rightW, qH, 8)
        ctx.fillStyle = 'rgba(255, 255, 255, 0.032)'
        ctx.fill()
        ctx.fillStyle = 'rgba(255, 255, 255, 0.25)'
        ctx.fillRect(rightX, ry + 6, 2.5, Math.max(10, qH - 12))

        ctx.font = `400 13.5px ${SANS_FONT}`
        ctx.fillStyle = 'rgba(244, 244, 245, 0.88)'
        ctx.textAlign = 'left'
        ctx.textBaseline = 'middle'
        let sy = ry + 7
        for (const sl of shortReviewLines) {
          ctx.fillText(sl, rightX + 12, sy + 10.5)
          sy += 21
        }
        ctx.restore()
      }
      ry += qH
    }

    return Math.max(topY + coverH, ry) + 28
  }

  const layoutBody = (ctx: CanvasRenderingContext2D, startY: number, draw: boolean): number => {
    let y = startY
    if (draw) {
      ctx.fillStyle = 'rgba(255, 255, 255, 0.08)'
      ctx.fillRect(padX, y, innerW, 1)
    }
    y += 28

    for (let nIdx = 0; nIdx < parsedNotes.length; nIdx++) {
      const entry = parsedNotes[nIdx]
      if (nIdx > 0) {
        y += 8
        if (draw) {
          ctx.fillStyle = 'rgba(255, 255, 255, 0.07)'
          ctx.fillRect(padX, y, innerW, 1)
        }
        y += 24
      }

      const typeMeta = NOTE_TYPE_LABELS[entry.note.note_type] || NOTE_TYPE_LABELS.work
      if (draw) {
        ctx.save()
        traceRoundedRect(ctx, padX, y + 3, 58, 22, 6)
        ctx.fillStyle = typeMeta.bg
        ctx.fill()
        ctx.font = `600 11px ${SANS_FONT}`
        ctx.fillStyle = typeMeta.fg
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(typeMeta.label, padX + 29, y + 14)
        ctx.restore()

        ctx.font = `600 20px ${SERIF_FONT}`
        ctx.fillStyle = '#f5f5f7'
        ctx.textAlign = 'left'
        ctx.textBaseline = 'middle'
        let ty = y
        for (let tlIdx = 0; tlIdx < entry.titleLines.length; tlIdx++) {
          ctx.fillText(entry.titleLines[tlIdx], padX + 68, ty + 14)
          ty += 28
        }
      }
      y += Math.max(28, entry.titleLines.length * 28) + 14

      y = drawOrMeasureBlocks(ctx, entry.blocks, padX, y, innerW, draw, opts.maskSpoilers)
    }
    return y + 12
  }

  // Pass 1：精确测量总高度
  const afterHeaderY = layoutHeader(measureCtx, false)
  const afterBodyY = parsedNotes.length > 0 ? layoutBody(measureCtx, afterHeaderY, false) : afterHeaderY + 12
  const FOOTER_H = 56
  const totalH = Math.min(16000, Math.max(360, Math.ceil(afterBodyY + FOOTER_H)))

  canvas.width = W * DPR
  canvas.height = totalH * DPR

  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('无法初始化图片画布')

  ctx.save()
  ctx.scale(DPR, DPR)
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'

  // 背景基底
  ctx.fillStyle = '#0c0c0f'
  ctx.fillRect(0, 0, W, totalH)

  // 顶部极克制封面氛围虚化晕染
  if (coverImg && !opts.blurCover) {
    ctx.save()
    ctx.beginPath()
    ctx.rect(0, 0, W, 320)
    ctx.clip()
    ctx.globalAlpha = 0.16
    ctx.filter = 'blur(44px)'
    drawCoverImage(ctx, coverImg, -40, -60, W + 80, 380)
    ctx.filter = 'none'
    ctx.globalAlpha = 1
    const fadeGrad = ctx.createLinearGradient(0, 0, 0, 320)
    fadeGrad.addColorStop(0, 'rgba(12, 12, 15, 0.35)')
    fadeGrad.addColorStop(1, '#0c0c0f')
    ctx.fillStyle = fadeGrad
    ctx.fillRect(0, 0, W, 320)
    ctx.restore()
  }

  // Pass 2：实际绘制头部、手记正文与底栏
  const bodyStartY = layoutHeader(ctx, true)
  if (parsedNotes.length > 0) {
    layoutBody(ctx, bodyStartY, true)
  }

  const fy = totalH - FOOTER_H
  ctx.fillStyle = '#0c0c0f'
  ctx.fillRect(0, fy, W, FOOTER_H)
  ctx.fillStyle = 'rgba(255, 255, 255, 0.08)'
  ctx.fillRect(padX, fy, innerW, 1)

  const fMidY = fy + FOOTER_H / 2 + 1
  ctx.font = `400 12px ${MONO_FONT}`
  ctx.fillStyle = 'rgba(244, 244, 245, 0.48)'
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'
  ctx.fillText(`游玩时长 ${playtimeText}  ·  ${formatDateDot()}`, padX, fMidY)

  if (opts.showWatermark) {
    ctx.font = `600 15px ${SERIF_FONT}`
    ctx.fillStyle = 'rgba(244, 244, 245, 0.42)'
    ctx.textAlign = 'right'
    ctx.fillText('TSUMUGI', W - padX, fMidY)
  }

  // 外围极细内描边
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)'
  ctx.lineWidth = 1
  ctx.strokeRect(0.5, 0.5, W - 1, totalH - 1)

  ctx.restore()
  return { width: canvas.width, height: canvas.height }
}
