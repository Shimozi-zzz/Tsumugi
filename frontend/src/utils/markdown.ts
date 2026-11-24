/**
 * 轻量且防 XSS 的 Markdown 渲染器（专为作品/角色长评手记设计）：
 * - 严格转义所有非白名单 HTML，杜绝脚本注入
 * - 支持标题、无序/有序列表、引用、粗体、斜体、删除线、行内代码、围栏代码块、分割线、安全链接
 * - 原生支持剧透折叠语法：
 *   1. 行内防剧透：>!剧透内容!< 或 ||剧透内容|| -> 点击/回车切换显隐的暗色遮罩
 *   2. 区块折叠：<details><summary>剧透标题</summary>内容</details>
 */

function escapeHtml(raw: string): string {
  return raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function sanitizeHref(raw: string): string {
  const trimmed = raw.trim()
  if (/^(https?:\/\/|mailto:)/i.test(trimmed)) {
    return trimmed.replace(/"/g, '%22')
  }
  return ''
}

function renderInline(raw: string): string {
  const placeholders: string[] = []
  const stash = (html: string): string => {
    const idx = placeholders.length
    placeholders.push(html)
    return `\u0000MD_INLINE_${idx}\u0000`
  }

  // 1. 先抽取行内代码，避免内部符号被二次解析
  let text = raw.replace(/`([^`\n]+)`/g, (_m, code: string) =>
    stash(`<code class="md-inline-code">${escapeHtml(code)}</code>`),
  )

  // 2. 抽取防剧透行内语法：>!剧透内容!< 与 ||剧透内容||
  text = text.replace(/>!([\s\S]+?)!</g, (_m, inner: string) =>
    stash(
      `<span class="md-spoiler" role="button" tabindex="0" data-spoiler="1" aria-label="点击显示剧透">${renderInlinePlain(inner)}</span>`,
    ),
  )
  text = text.replace(/\|\|([^|\n]+?)\|\|/g, (_m, inner: string) =>
    stash(
      `<span class="md-spoiler" role="button" tabindex="0" data-spoiler="1" aria-label="点击显示剧透">${renderInlinePlain(inner)}</span>`,
    ),
  )

  // 3. 安全链接 [label](url)
  text = text.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (_m, label: string, url: string) => {
    const safeUrl = sanitizeHref(url)
    if (!safeUrl) return escapeHtml(label)
    return stash(
      `<a class="md-link" href="${safeUrl}" target="_blank" rel="noopener noreferrer">${renderInlinePlain(label)}</a>`,
    )
  })

  text = renderInlinePlain(text)

  return text.replace(/\u0000MD_INLINE_(\d+)\u0000/g, (_m, idxStr: string) => {
    const idx = Number(idxStr)
    return placeholders[idx] ?? ''
  })
}

function renderInlinePlain(raw: string): string {
  let out = escapeHtml(raw)
  out = out.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  out = out.replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
  out = out.replace(/~~([^~\n]+)~~/g, '<del>$1</del>')
  out = out.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
  return out
}

function renderMarkdownBlocks(src: string): string {
  const lines = src.replace(/\r\n/g, '\n').split('\n')
  const html: string[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    if (!trimmed) {
      i++
      continue
    }

    // 围栏代码块
    if (trimmed.startsWith('```')) {
      const codeLines: string[] = []
      i++
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i])
        i++
      }
      if (i < lines.length) i++
      html.push(`<pre class="md-code-block"><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
      continue
    }

    // 分割线
    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      html.push('<hr class="md-hr" />')
      i++
      continue
    }

    // 标题 h1~h4
    const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)$/)
    if (headingMatch) {
      const level = headingMatch[1].length
      html.push(`<h${level} class="md-h md-h${level}">${renderInline(headingMatch[2])}</h${level}>`)
      i++
      continue
    }

    // 引用块（排除行内剧透 >! ... !< 开头）
    if (trimmed.startsWith('>') && !trimmed.startsWith('>!')) {
      const quoteLines: string[] = []
      while (i < lines.length) {
        const qTrim = lines[i].trim()
        if (qTrim.startsWith('>') && !qTrim.startsWith('>!')) {
          quoteLines.push(qTrim.replace(/^>\s?/, ''))
          i++
        } else {
          break
        }
      }
      html.push(
        `<blockquote class="md-quote">${quoteLines.map((q) => renderInline(q)).join('<br />')}</blockquote>`,
      )
      continue
    }

    // 无序列表
    if (/^[-*+]\s+/.test(trimmed)) {
      const listItems: string[] = []
      while (i < lines.length && /^[-*+]\s+/.test(lines[i].trim())) {
        listItems.push(lines[i].trim().replace(/^[-*+]\s+/, ''))
        i++
      }
      html.push(
        `<ul class="md-list">${listItems.map((it) => `<li>${renderInline(it)}</li>`).join('')}</ul>`,
      )
      continue
    }

    // 有序列表
    if (/^\d+\.\s+/.test(trimmed)) {
      const listItems: string[] = []
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        listItems.push(lines[i].trim().replace(/^\d+\.\s+/, ''))
        i++
      }
      html.push(
        `<ol class="md-list md-ol">${listItems.map((it) => `<li>${renderInline(it)}</li>`).join('')}</ol>`,
      )
      continue
    }

    // 普通段落（连续非特殊行合并）
    const paraLines: string[] = []
    while (i < lines.length) {
      const cur = lines[i]
      const curTrim = cur.trim()
      if (
        !curTrim ||
        curTrim.startsWith('```') ||
        /^(?:-{3,}|\*{3,}|_{3,})$/.test(curTrim) ||
        /^#{1,4}\s+/.test(curTrim) ||
        (curTrim.startsWith('>') && !curTrim.startsWith('>!')) ||
        /^[-*+]\s+/.test(curTrim) ||
        /^\d+\.\s+/.test(curTrim)
      ) {
        break
      }
      paraLines.push(cur)
      i++
    }
    html.push(`<p class="md-p">${paraLines.map((p) => renderInline(p)).join('<br />')}</p>`)
  }

  return html.join('\n')
}

/**
 * 将 Markdown 原文渲染为安全 HTML，兼容 <details><summary>...</summary>...</details> 剧透折叠块。
 */
export function renderNoteMarkdown(markdown: string): string {
  const source = (markdown || '').replace(/\r\n/g, '\n')
  if (!source.trim()) {
    return '<p class="md-empty">暂无正文内容，可切换至「编辑」开始书写。</p>'
  }

  const detailsStash: string[] = []
  const withStashedDetails = source.replace(
    /<details\b[^>]*>([\s\S]*?)<\/details>/gi,
    (_match, inner: string) => {
      let summaryText = '点击展开剧透内容'
      const bodyRaw = inner.replace(
        /<summary\b[^>]*>([\s\S]*?)<\/summary>/i,
        (_sm, sInner: string) => {
          const cleanSummary = sInner.trim()
          if (cleanSummary) summaryText = cleanSummary
          return ''
        },
      )
      const renderedBody = renderMarkdownBlocks(bodyRaw.trim())
      const blockHtml = `<details class="md-details"><summary class="md-summary">${renderInline(summaryText)}</summary><div class="md-details-body">${renderedBody}</div></details>`
      const idx = detailsStash.length
      detailsStash.push(blockHtml)
      return `\n\n@@TSUMUGI_DETAILS_${idx}@@\n\n`
    },
  )

  const rendered = renderMarkdownBlocks(withStashedDetails)
  return rendered.replace(/<p class="md-p">@@TSUMUGI_DETAILS_(\d+)@@<\/p>|@@TSUMUGI_DETAILS_(\d+)@@/g, (_m, a, b) => {
    const idx = Number(a ?? b)
    return detailsStash[idx] ?? ''
  })
}

export function toggleSpoilerFromEvent(ev: MouseEvent | KeyboardEvent): void {
  if (ev instanceof KeyboardEvent && ev.key !== 'Enter' && ev.key !== ' ') {
    return
  }
  const target = ev.target as HTMLElement | null
  const spoiler = target?.closest('.md-spoiler') as HTMLElement | null
  if (!spoiler) return
  if (ev instanceof KeyboardEvent) {
    ev.preventDefault()
  }
  spoiler.classList.toggle('revealed')
}
