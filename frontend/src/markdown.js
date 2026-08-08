// 手写轻量 Markdown 渲染器（书评/文档预览用，不引入第三方库）
// 先整体转义 HTML 再应用 markdown 标记，避免 XSS；链接仅允许 http(s)。
//
// 修复记录（ADR 0026）：
// - 行内代码改为占位符/优先匹配，避免 `` `code` `` 里再被加粗/斜体误处理；
// - 加粗/斜体改为逐字符 tokenizer（递归内联），支持 `**外层*斜体*内容**` 嵌套，
//   不再撕裂成 `*<em>外层</em>...*`；
// - 支持有序列表（1. / 1) 开头）。

function escapeHtml(s) {
  // 不转义 `>`：块级引用依赖原始 `>`，且裸 `>`（无 `<`）不会被浏览器解析为标签，XSS 安全
  return String(s).replace(/[&<"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ---- 行内 tokenizer：代码 / 粗体(可嵌斜体) / 斜体 / 删除线 / 链接 ----
// 在已转义的文本上逐字符扫描；code 直接输出（不再处理内部），其它标记递归处理内容。
const RE_CODE = /^`([^`]+)`/;
const RE_TRIPLE = /^\*\*\*(?!\s)([^*\n]+?)(?<!\s)\*\*\*/;
const RE_BOLD = /^\*\*(?!\s)([\s\S]*?)(?<!\s)\*\*/;
const RE_EMPH = /^\*(?!\s)([^*\n]+?)(?<!\s)\*/;
const RE_DEL = /^~~(?!\s)([^~\n]+?)(?<!\s)~~/;
const RE_LINK = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/;

function inline(text) {
  let out = "";
  let i = 0;
  const n = text.length;
  while (i < n) {
    const rest = text.slice(i);
    let m;
    if ((m = rest.match(RE_CODE))) {
      out += `<code>${m[1]}</code>`; i += m[0].length; continue;
    }
    if ((m = rest.match(RE_TRIPLE))) {
      out += `<strong><em>${m[1]}</em></strong>`; i += m[0].length; continue;
    }
    if ((m = rest.match(RE_BOLD))) {
      out += `<strong>${inline(m[1])}</strong>`; i += m[0].length; continue;
    }
    if ((m = rest.match(RE_EMPH))) {
      out += `<em>${inline(m[1])}</em>`; i += m[0].length; continue;
    }
    if ((m = rest.match(RE_DEL))) {
      out += `<del>${inline(m[1])}</del>`; i += m[0].length; continue;
    }
    if ((m = rest.match(RE_LINK))) {
      out += `<a href="${m[2]}" target="_blank" rel="noreferrer">${inline(m[1])}</a>`;
      i += m[0].length; continue;
    }
    out += rest[0];
    i += 1;
  }
  return out;
}

// 块级：标题 / 无序·有序列表 / 引用 / 段落
function renderBlocks(blockText) {
  const lines = blockText.split("\n");
  const out = [];
  let list = null; // { ordered: bool, items: [] }
  const flushList = () => {
    if (list) {
      const tag = list.ordered ? "ol" : "ul";
      out.push(`<${tag}>${list.items.map((x) => `<li>${inline(x)}</li>`).join("")}</${tag}>`);
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
    const liU = line.match(/^\s*[-*+]\s+(.*)$/);
    const liO = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (liU || liO) {
      const ordered = !!liO;
      const itemText = liO ? liO[1] : liU[1];
      if (list && list.ordered !== ordered) flushList();
      if (!list) list = { ordered, items: [] };
      list.items.push(itemText);
      continue;
    }
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
