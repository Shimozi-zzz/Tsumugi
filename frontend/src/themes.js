// 主题系统（Phase 5）
// 主题名 -> 显示名。主题通过 html[data-theme] + CSS 变量切换。

export const THEMES = [
  { key: "spring", label: "春樱 Sakura" },
  { key: "summer", label: "夏·空" },
  { key: "violet-obsidian", label: "夜紫书斋" },
  { key: "default", label: "默认" },
];

const STORAGE_KEY = "tsumugi-theme";

export function loadTheme() {
  try {
    return localStorage.getItem(STORAGE_KEY) || "spring";
  } catch {
    return "spring";
  }
}

export function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* 忽略隐私模式等 */
  }
}
