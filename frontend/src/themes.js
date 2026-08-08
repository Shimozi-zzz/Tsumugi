// 主题系统（收敛版，见 ADR 0020）
// 四套主题共享同一套设计 token（间距/圆角/阴影/密度在 index.css 的 :root 定义），
// 主题只改色彩变量。自定义层：强调色色相微调 + 信息密度 + 圆角大小（有约束）。
import { hexToHsl, hslCss } from "./bookshelf.js";

export const THEMES = [
  { key: "default", label: "经典白" },
  { key: "mint", label: "薄荷 × 浅蓝" },
  { key: "sakura", label: "樱花粉" },
  { key: "dark", label: "深夜深蓝" },
];

const STORAGE_KEY = "tsumugi-theme";
const CUSTOM_KEY = "tsumugi-theme-custom";

// 各主题基准强调色（自定义色相在此基准上小幅旋转）
const ACCENTS = {
  default: "#2563eb",
  mint: "#10b981",
  sakura: "#ec4899",
  dark: "#4a9eff",
};

// 深色主题（ADR 0029）：强调色的派生逻辑不同——hover 更亮、soft 用深色染而非近白
const DARK_THEMES = new Set(["dark"]);

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
