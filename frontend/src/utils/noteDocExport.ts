import type { Game, GameNote, RatingDimensionKey } from '@/types'

const RATING_DIMENSIONS: Array<{ key: RatingDimensionKey; label: string }> = [
  { key: 'story', label: '剧本' },
  { key: 'visual', label: '美术与演出' },
  { key: 'music', label: '音乐' },
  { key: 'atmosphere', label: '氛围与体验' },
]

const NOTE_TYPE_LABELS: Record<string, string> = {
  work: '作品总评',
  character: '角色手记',
  misc: '游玩随记',
}

const STATUS_LABELS: Record<string, string> = {
  todo: '未开始',
  unplayed: '未开始',
  playing: '攻略中',
  done: '已通关',
  completed: '已通关',
}

export function formatPlaytimeText(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds || 0))
  if (s === 0) return '0 小时'
  if (s < 60) return '不足 1 分钟'
  const mins = Math.floor(s / 60)
  if (mins < 60) return `${mins} 分钟`
  return `${(s / 3600).toFixed(1)} 小时`
}

function cleanInlineForPlainText(raw: string, maskSpoilers: boolean): string {
  let text = raw
    .replace(/`([^`\n]+)`/g, '$1')
    .replace(/\[([^\]\n]+)\]\([^)]+\)/g, '$1')
    .replace(/\*\*([^*\n]+)\*\*/g, '$1')
    .replace(/__([^_\n]+)__/g, '$1')
    .replace(/~~([^~\n]+)~~/g, '$1')
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1$2')

  if (maskSpoilers) {
    text = text
      .replace(/>!([\s\S]*?)!</g, '[剧透已隐藏]')
      .replace(/\|\|([^|\n]+?)\|\|/g, '[剧透已隐藏]')
  } else {
    text = text
      .replace(/>!([\s\S]*?)!</g, '$1')
      .replace(/\|\|([^|\n]+?)\|\|/g, '$1')
  }
  return text
}

function markdownToPlainText(md: string, maskSpoilers: boolean): string {
  const source = (md || '').replace(/\r\n/g, '\n')
  if (!source.trim()) return '（暂无正文）'

  const withoutDetails = source.replace(
    /<details\b[^>]*>([\s\S]*?)<\/details>/gi,
    (_m, inner: string) => {
      let summary = '剧透折叠内容'
      const body = inner.replace(
        /<summary\b[^>]*>([\s\S]*?)<\/summary>/i,
        (_sm, sInner: string) => {
          const clean = sInner.trim()
          if (clean) summary = clean
          return ''
        },
      )
      if (maskSpoilers) {
        return `\n[${summary}：剧透已隐藏]\n`
      }
      return `\n[${summary}]\n${body.trim()}\n`
    },
  )

  const outLines: string[] = []
  let inCode = false
  for (const rawLine of withoutDetails.split('\n')) {
    const trimmed = rawLine.trim()
    if (trimmed.startsWith('```')) {
      inCode = !inCode
      continue
    }
    if (inCode) {
      outLines.push(`  ${rawLine}`)
      continue
    }
    if (!trimmed) {
      if (outLines.length > 0 && outLines[outLines.length - 1] !== '') {
        outLines.push('')
      }
      continue
    }
    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      outLines.push('────────────────────────')
      continue
    }
    const headingMatch = trimmed.match(/^#{1,6}\s+(.+)$/)
    if (headingMatch) {
      outLines.push(cleanInlineForPlainText(headingMatch[1], maskSpoilers))
      continue
    }
    if (trimmed.startsWith('>') && !trimmed.startsWith('>!')) {
      outLines.push(`「${cleanInlineForPlainText(trimmed.replace(/^>\s?/, ''), maskSpoilers)}」`)
      continue
    }
    if (/^[-*+]\s+/.test(trimmed)) {
      outLines.push(`• ${cleanInlineForPlainText(trimmed.replace(/^[-*+]\s+/, ''), maskSpoilers)}`)
      continue
    }
    outLines.push(cleanInlineForPlainText(trimmed, maskSpoilers))
  }
  return outLines.join('\n').trim() || '（暂无正文）'
}

/**
 * 构建无图片的纯文本导出（.txt），清晰结构化，适合存档或跨工具粘贴。
 */
export function buildPlainTextExport(
  game: Game,
  notes: GameNote[],
  opts: { maskSpoilers: boolean },
): string {
  const lines: string[] = []
  const statusKey = (game.status || 'todo').trim().toLowerCase()
  const statusZh = STATUS_LABELS[statusKey] || '未开始'
  const playSec = game.play_record?.total_seconds || 0

  lines.push(game.title)
  if ((game.sub_title || '').trim() && game.sub_title.trim() !== game.title.trim()) {
    lines.push(game.sub_title.trim())
  }
  lines.push('========================================')
  if ((game.developer || '').trim()) lines.push(`开发商：${game.developer.trim()}`)
  if ((game.release_date || '').trim()) lines.push(`发售日：${game.release_date.trim()}`)
  lines.push(`进度：${statusZh} · 累计游玩：${formatPlaytimeText(playSec)}`)

  const dims = game.rating_dimensions || {}
  const dimParts = RATING_DIMENSIONS.filter((d) => dims[d.key] != null).map(
    (d) => `${d.label} ${Number(dims[d.key]).toFixed(1)}`,
  )
  if (game.rating_overall != null || dimParts.length > 0) {
    const scoreHead =
      game.rating_overall != null ? `综合评分：${Number(game.rating_overall).toFixed(1)} / 10` : '评分明细'
    lines.push(dimParts.length > 0 ? `${scoreHead}（${dimParts.join(' · ')}）` : scoreHead)
  }

  const shortReview = (game.short_review || '').trim()
  if (shortReview) {
    lines.push(`短评：${shortReview}`)
  }

  if (notes.length > 0) {
    lines.push('')
    notes.forEach((note, idx) => {
      if (idx > 0) {
        lines.push('')
        lines.push('----------------------------------------')
        lines.push('')
      }
      const typeLabel = NOTE_TYPE_LABELS[note.note_type] || '手记'
      lines.push(`[${typeLabel}] ${note.title || typeLabel}`)
      lines.push('')
      lines.push(markdownToPlainText(note.content_md || '', opts.maskSpoilers))
    })
  }

  lines.push('')
  return lines.join('\n')
}
