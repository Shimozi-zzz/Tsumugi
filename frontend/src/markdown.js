// 手写轻量 Markdown 渲染器（书评/文档预览用，不引入第三方库）
// 先整体转义 HTML 再应用 markdown 标记，避免 XSS；链接仅允许 http(s)。

function escapeHtml(s) {
  // 不转义 `>`：块级引用依赖原始 `>`，且裸 `>`（无 `<`）不会被浏览器解析为标签，XSS 安全
  return String(s).replace(/[&<"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// 行内格式：代码 / 加粗 / 斜体 / 删除线 / 链接
function inline(md) {
  return md
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/~~([^~]+)~~/g, "<del>$1</del>")
    .replace(
      /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noreferrer">$1</a>'
    );
}

// 块级：标题 / 列表 / 引用 / 段落
function renderBlocks(blockText) {
  const lines = blockText.split("\n");
  const out = [];
  let list = null;
  const flushList = () => {
    if (list) {
      out.push(`<ul>${list.map((x) => `<li>${inline(x)}</li>`).join("")}</ul>`);
      list = null;
    }
  };
  for (const line of lines) {
    if (!line.trim()) { flushList(); out.push(""); continue; }
    const h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h) {
      flushList();
      const lv = h[1].length;
      out.push(`<h${lv}>${inline(h[2])}</h${lv}>`);
      continue;
    }
    const li = line.match(/^\s*[-*+]\s+(.*)$/);
    if (li) { list = list || []; list.push(li[1]); continue; }
    const bq = line.match(/^\s*>\s?(.*)$/);
    if (bq) { flushList(); out.push(`<blockquote>${inline(bq[1])}</blockquote>`); continue; }
    flushList();
    out.push(`<p>${inline(line)}</p>`);
  }
  flushList();
  return out.filter(Boolean).join("\n");
}

/**
 * Markdown → HTML 字符串。fenced code（```）按代码块渲染，其余走块级规则。
 */
export function renderMarkdown(text) {
  if (!text) return "";
  const src = String(text).replace(/\r\n/g, "\n");
  const escaped = escapeHtml(src);
  const parts = escaped.split(/```/g); // 奇数为代码块
  let html = "";
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 1) {
      html += `<pre><code>${parts[i].replace(/\n$/, "")}</code></pre>`;
    } else {
      html += renderBlocks(parts[i]);
    }
  }
  return html;
}
