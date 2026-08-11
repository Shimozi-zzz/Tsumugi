// 主题系统（收敛版，见 ADR 0020）
// 四套主题共享同一套设计 token（间距/圆角/阴影/密度在 index.css 的 :root 定义），
// 主题只改色彩变量。自定义层：强调色色相微调 + 信息密度 + 圆角大小（有约束）。
import { hexToHsl, hslCss } from "./bookshelf.js";

export const THEMES = [
  { key: "default", label: "编目抽屉" },
];

const STORAGE_KEY = "tsumugi-theme";
const CUSTOM_KEY = "tsumugi-theme-custom";

// 各主题基准强调色（自定义色相在此基准上小幅旋转）。
// 本轮定案（ADR 0059）：仅保留默认"编目抽屉"纸感主题（#b25b36 暖橙）；
// mint/sakura/dark 已移除。
const ACCENTS = {
  default: "#b25b36",
};

// 深色主题派生逻辑（本轮无深色主题，保留分支为将来扩展）
const DARK_THEMES = new Set();

// 自定义默认值：色相偏移 0、舒适密度、圆角 16px
export const DEFAULT_CUSTOM = { accentHue: 0, density: "comfortable", radius: 16 };
export const ACCENT_HUE_RANGE = { min: -20, max: 20 }; // 有约束的色相调整范围
export const RADIUS_RANGE = { min: 12, max: 24 };

export function loadTheme() {
  try {
    const t = localStorage.getItem(STORAGE_KEY) || "default";
    return THEMES.some((x) => x.key === t) ? t : "default";
  } catch {
    return "default";
  }
}

export function loadCustom() {
  try {
    const raw = localStorage.getItem(CUSTOM_KEY);
    if (raw) return { ...DEFAULT_CUSTOM, ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return { ...DEFAULT_CUSTOM };
}

export function saveCustom(custom) {
  try { localStorage.setItem(CUSTOM_KEY, JSON.stringify(custom)); } catch { /* ignore */ }
}

function applyAccentHue(theme, offset) {
  const base = ACCENTS[theme] || ACCENTS.default;
  const { h, s, l } = hexToHsl(base);
  const hue = ((Math.round(h) + (offset || 0)) % 360 + 360) % 360;
  const el = document.documentElement;
  const isDark = DARK_THEMES.has(theme);
  if (isDark) {
    // 深色主题：强调色取中亮（保证深底对比）、hover 更亮、soft 用深色染（≈0.13 明度）
    el.style.setProperty("--accent", hslCss(hue, Math.min(s, 0.72), 0.68));
    el.style.setProperty("--accent-hover", hslCss(hue, Math.min(s, 0.7), 0.78));
    el.style.setProperty("--accent-soft", hslCss(hue, 0.42, 0.13));
  } else {
    el.style.setProperty("--accent", hslCss(hue, s, l));
    el.style.setProperty("--accent-hover", hslCss(hue, Math.min(s, 0.85), Math.max(l - 0.06, 0.3)));
    el.style.setProperty("--accent-soft", hslCss(hue, Math.min(s * 0.5, 0.5), 0.96));
  }
}

// 大风格主题（视觉语言层）：整体版式/材质/信息呈现，区别于色彩主题（THEMES）。
// 通过 html[data-style-theme] 切换；后续注册其它大风格主题时，各自以
// `html[data-style-theme="..."]` 作用域覆盖基础样式。
export const STYLE_THEMES = [
  {
    key: "catalog-drawer",
    label: "编目抽屉·索书卡",
    description: "真实档案卡：暖纸底 + 档卡横线 + 密集元数据行",
  },
];

const STYLE_STORAGE_KEY = "tsumugi-style-theme";

export function loadStyleTheme() {
  try {
    const t = localStorage.getItem(STYLE_STORAGE_KEY);
    return STYLE_THEMES.some((x) => x.key === t) ? t : STYLE_THEMES[0].key;
  } catch {
    return STYLE_THEMES[0].key;
  }
}

export function applyStyleTheme(key) {
  const k = STYLE_THEMES.some((x) => x.key === key) ? key : STYLE_THEMES[0].key;
  document.documentElement.setAttribute("data-style-theme", k);
  try { localStorage.setItem(STYLE_STORAGE_KEY, k); } catch { /* ignore */ }
}

export function applyTheme(theme, custom = DEFAULT_CUSTOM) {
  document.documentElement.setAttribute("data-theme", theme);
  document.documentElement.setAttribute("data-density", custom.density === "compact" ? "compact" : "comfortable");
  document.documentElement.style.setProperty("--radius-lg", `${Math.min(Math.max(custom.radius, RADIUS_RANGE.min), RADIUS_RANGE.max)}px`);
  applyAccentHue(theme, custom.accentHue);
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* 忽略隐私模式等 */
  }
}
