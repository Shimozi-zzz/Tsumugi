// 安利卡（分享卡片）——手写 SVG 生成 + 导出 PNG
// 复用 Stats 面板"手写 SVG"技术路线，不引入图表/Canvas 库。
// 决策见 docs/decisions/0018-share-card.md

const CARD_W = 640;
const CARD_H = 800;
const QUOTE_MAX = 60; // 短评截断字符数

// ---------------------------------------------------------------- 工具

export function escapeXml(s) {
  return String(s ?? "").replace(/[<>&'"]/g, (c) => ({
    "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;",
  }[c]));
}

export function readCssVar(name, fallback) {
  if (typeof document === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export function readThemeColors() {
  return {
    bg: readCssVar("--bg", "#0b0f19"),
    panel: readCssVar("--panel", "rgba(30,34,48,0.42)"),
    accent: readCssVar("--accent", "#f09199"),
    text: readCssVar("--text", "#f3f4f6"),
    textSec: readCssVar("--text-secondary", "#9ca3af"),
    tagBg: readCssVar("--tag-bg", "rgba(255,255,255,0.08)"),
    tagText: readCssVar("--tag-text", "#a5d8f7"),
  };
}

// ---------------------------------------------------------------- 短评选取

export function cleanQuote(content) {
  if (!content) return null;
  const one = String(content).replace(/\s+/g, " ").trim();
  if (!one) return null;
  return one.length > QUOTE_MAX ? one.slice(0, QUOTE_MAX).trim() + "…" : one;
}

/**
 * 选取安利卡短评：**最新一条非 spoiler 的 Review 内容**（已清洗截断）。
 * - 全部 Review 都标了 spoiler → 返回 null（调用方据此显示"作者选择不剧透"）；
 * - 没有任何 Review → 返回 null（调用方据此整块省略短评区）。
 * 理由见 ADR 0018：安利卡要分享到应用外部，spoilered 内容绝不进卡片。
 */
export function selectQuote(reviews) {
  const list = Array.isArray(reviews) ? reviews : [];
  const nonSpoiler = list.filter((r) => !r.spoiler);
  if (nonSpoiler.length === 0) return null;
  return cleanQuote(nonSpoiler[0].content); // fetchItemReviews 已时间倒序，[0] 为最新
}

export function wrapText(text, maxChars) {
  const lines = [];
  for (let i = 0; i < text.length; i += maxChars) {
    lines.push(text.slice(i, i + maxChars));
  }
  return lines;
}

// ---------------------------------------------------------------- SVG 构建

function coverBlock(c, coverHref) {
  const x = 180, y = 84, w = 280, h = 373, r = 20;
  if (coverHref) {
    return [
      `<rect x="${x - 6}" y="${y + 8}" width="${w}" height="${h}" rx="${r + 4}" fill="rgba(0,0,0,0.28)"/>`,
      `<clipPath id="coverClip"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}"/></clipPath>`,
      `<g clip-path="url(#coverClip)">`,
      `  <image href="${escapeXml(coverHref)}" x="${x}" y="${y}" width="${w}" height="${h}" preserveAspectRatio="xMidYMid slice"/>`,
      `  <rect x="${x}" y="${y}" width="${w}" height="${h}" fill="none" stroke="rgba(255,255,255,0.14)" stroke-width="1.5" rx="${r}"/>`,
      `</g>`,
    ].join("\n");
  }
  // 占位封面：柔和渐变 + 标题首字
  const gid = "thumbGrad";
  return [
    `<rect x="${x - 6}" y="${y + 8}" width="${w}" height="${h}" rx="${r + 4}" fill="rgba(0,0,0,0.28)"/>`,
    `<clipPath id="coverClip"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}"/></clipPath>`,
    `<g clip-path="url(#coverClip)">`,
    `  <rect x="${x}" y="${y}" width="${w}" height="${h}" fill="url(#${gid})"/>`,
    `  <rect x="${x}" y="${y}" width="${w}" height="${h}" fill="none" stroke="rgba(255,255,255,0.14)" stroke-width="1.5" rx="${r}"/>`,
    `</g>`,
  ].join("\n");
}

/**
 * 生成安利卡 SVG 字符串。
 * rating 为 null 时**不渲染评分区**（分享向，不硬凑）；quote 为空且 spoilerOnly
 * 为真时显示"作者选择不剧透"；两者皆空则整块省略短评区。
 */
export function buildShareCardSvg({
  title, coverHref, rating, quote, spoilerOnly, source, colors,
}) {
  const c = colors || readThemeColors();
  const W = CARD_W, H = CARD_H;
  const cx = W / 2;

  // 标题断行（最多 2 行，每行 ~16 字）
  const titleLines = wrapText(String(title || "未命名"), 16).slice(0, 2);
  const titleY = 524;

  // 评分区
  let ratingBlock = "";
  if (typeof rating === "number") {
    ratingBlock = [
      `<text x="${cx - 26}" y="572" text-anchor="middle" font-size="17" fill="${c.accent}">★</text>`,
      `<text x="${cx + 8}" y="572" text-anchor="start" font-size="17" font-weight="700" fill="${c.text}">${escapeXml(String(rating))}</text>`,
      `<text x="${cx + 48}" y="572" text-anchor="start" font-size="12" fill="${c.textSec}">我的评分</text>`,
    ].join("\n");
  }

  // 短评区
  let quoteBlock = "";
  if (quote) {
    const lines = wrapText(quote, 20).slice(0, 3);
    const baseY = 612;
    quoteBlock = lines
      .map((ln, i) => {
        const isFirst = i === 0;
        const isLast = i === lines.length - 1;
        const prefix = isFirst ? "「" : "";
        const suffix = isLast ? "」" : "";
        return `<text x="${cx}" y="${baseY + i * 26}" text-anchor="middle" font-size="15" font-style="italic" fill="${c.textSec}">${escapeXml(prefix + ln + suffix)}</text>`;
      })
      .join("\n");
  } else if (spoilerOnly) {
    quoteBlock = `<text x="${cx}" y="612" text-anchor="middle" font-size="13" fill="${c.textSec}">作者选择不剧透</text>`;
  }

  const hasTitle = titleLines.length > 0;
  const sourceY = hasTitle ? titleY + (titleLines.length - 1) * 34 + 26 : 560;

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <defs>
    <linearGradient id="bgGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${c.bg}"/>
      <stop offset="1" stop-color="${c.panel}"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.5" cy="0.18" r="0.65">
      <stop offset="0" stop-color="${c.accent}" stop-opacity="0.30"/>
      <stop offset="1" stop-color="${c.accent}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="thumbGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${c.accent}" stop-opacity="0.85"/>
      <stop offset="1" stop-color="${c.panel}" stop-opacity="0.9"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="${W}" height="${H}" rx="32" fill="url(#bgGrad)"/>
  <rect x="0" y="0" width="${W}" height="${H}" rx="32" fill="url(#glow)"/>
  <text x="${cx}" y="52" text-anchor="middle" font-size="13" letter-spacing="4" fill="${c.textSec}">TSUMUGI · 安利</text>
  ${coverBlock(c, coverHref)}
  ${titleLines.map((ln, i) => `<text x="${cx}" y="${titleY + i * 34}" text-anchor="middle" font-size="26" font-weight="700" fill="${c.text}">${escapeXml(ln)}</text>`).join("\n")}
  <rect x="${cx - 40}" y="${sourceY - 14}" width="80" height="24" rx="12" fill="${c.tagBg}"/>
  <text x="${cx}" y="${sourceY + 1}" text-anchor="middle" font-size="11" fill="${c.tagText}">${escapeXml(source || "Tsumugi")}</text>
  ${ratingBlock}
  ${quoteBlock}
  <text x="${cx}" y="${H - 26}" text-anchor="middle" font-size="11" fill="${c.textSec}">from Tsumugi · 个人知识库</text>
</svg>`;
}

// ---------------------------------------------------------------- 导出 PNG（浏览器端）

function blobToDataUrl(blob) {
  return new Promise((resolve) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result);
    fr.onerror = () => resolve(null);
    fr.readAsDataURL(blob);
  });
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("图片加载失败"));
    img.src = src;
  });
}

/**
 * 把封面转成 data URL 内联进 SVG，避免 Canvas 被跨域图片污染（taint）。
 * 本地 /static 缓存封面同源可正常 fetch；远程无 CORS 的返回 null（退化为占位图）。
 */
export async function imageUrlToDataUrl(src) {
  if (!src) return null;
  if (src.startsWith("data:")) return src;
  try {
    const resp = await fetch(src, { mode: "cors" });
    if (!resp.ok) return null;
    const blob = await resp.blob();
    if (!blob.type.startsWith("image/")) return null;
    return await blobToDataUrl(blob);
  } catch {
    return null;
  }
}

export async function svgStringToPngBlob(svgString, scale = 2) {
  const blob = new Blob([svgString], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const img = await loadImage(url);
    const canvas = document.createElement("canvas");
    canvas.width = img.width * scale;
    canvas.height = img.height * scale;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return new Promise((resolve, reject) => {
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("PNG 编码失败"))), "image/png");
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}

export async function downloadSvgAsPng(svgString, filename) {
  const png = await svgStringToPngBlob(svgString);
  const url = URL.createObjectURL(png);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || "anli-card.png";
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
