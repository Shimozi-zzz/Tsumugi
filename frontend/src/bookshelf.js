// 书架/书脊视图：配色分配与种子（纯函数，可测试）
// 决策见 docs/decisions/0019-bookshelf-view.md

/**
 * 简单字符串哈希（用于把条目映射到稳定的书脊色调）。
 */
export function stringHash(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

/**
 * 条目的主分类标签（书架按分类给相近色调）；无标签用 id 兜底。
 */
export function primaryTag(it) {
  if (!it) return "";
  if (Array.isArray(it.tags) && it.tags.length) return it.tags[0];
  if (Array.isArray(it.tag_names) && it.tag_names.length) return it.tag_names[0];
  return "";
}

/**
 * 书脊配色种子：主标签哈希（同标签作品 → 相近色相，观感如按分类归架）；
 * 无标签 → id 哈希（稳定）。
 */
export function spineSeed(it) {
  const tag = primaryTag(it);
  return stringHash(tag || String((it && it.id) || ""));
}

/**
 * #RRGGBB → HSL（不合法输入回退到灰蓝，保证书脊始终有可用色）。
 */
export function hexToHsl(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex || "").trim());
  if (!m) return { h: 220, s: 0.45, l: 0.55 };
  const n = parseInt(m[1], 16);
  const r = ((n >> 16) & 255) / 255;
  const g = ((n >> 8) & 255) / 255;
  const b = (n & 255) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  const d = max - min;
  let h = 0;
  let s = 0;
  if (d !== 0) {
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = ((g - b) / d + (g < b ? 6 : 0)) * 60; break;
      case g: h = ((b - r) / d + 2) * 60; break;
      default: h = ((r - g) / d + 4) * 60; break;
    }
  }
  return { h, s, l };
}

export function hslCss(h, s, l) {
  return `hsl(${Math.round(h)}, ${Math.round(s * 100)}%, ${Math.round(l * 100)}%)`;
}

/**
 * 由主题 accent 派生书脊色：seed 决定色相偏移，饱和度/明度向"书脊质感的
 * 低饱和中明度"收敛（不引入取色库，不脱离主题色系）。
 */
export function spineColor(accentHex, seed) {
  const { h, s, l } = hexToHsl(accentHex);
  const hue = (Math.round(h) + ((seed * 47) % 360) + 360) % 360;
  return hslCss(
    hue,
    Math.min(Math.max(s * 0.72, 0.32), 0.5),
    Math.min(Math.max(l * 0.72, 0.4), 0.58),
  );
}
