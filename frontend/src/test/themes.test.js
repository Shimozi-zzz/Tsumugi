// 主题系统测试：3 套收敛主题 + 有约束的自定义层（强调色色相/密度/圆角）
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect, beforeEach } from "vitest";
import {
  THEMES, loadTheme, applyTheme, loadCustom, saveCustom,
  DEFAULT_CUSTOM, ACCENT_HUE_RANGE, RADIUS_RANGE,
} from "../themes.js";

function parseHslHue(css) {
  const m = /hsl\(([^)]+)\)/.exec(css);
  if (!m) return null;
  return parseFloat(m[1].split(",")[0]);
}

describe("theme system", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("data-density");
  });

  it("THEMES 仅默认（编目抽屉，ADR 0059 起保留一套主题）", () => {
    expect(THEMES.map((t) => t.key)).toEqual(["default"]);
  });

  it("applyTheme('dark') 正常切换并持久化", () => {
    applyTheme("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem("tsumugi-theme")).toBe("dark");
    applyTheme("mint");
    expect(document.documentElement.getAttribute("data-theme")).toBe("mint");
  });

  it("applyTheme 切换 data-theme 并持久化", () => {
    applyTheme("mint");
    expect(document.documentElement.getAttribute("data-theme")).toBe("mint");
    expect(localStorage.getItem("tsumugi-theme")).toBe("mint");
    applyTheme("sakura");
    expect(document.documentElement.getAttribute("data-theme")).toBe("sakura");
  });

  it("无持久化时默认经典白（default）", () => {
    expect(loadTheme()).toBe("default");
  });

  it("未知主题回退默认", () => {
    localStorage.setItem("tsumugi-theme", "violet-obsidian");
    expect(loadTheme()).toBe("default");
  });

  it("默认密度为舒适，且 data-density 正确写入", () => {
    applyTheme("default");
    expect(document.documentElement.getAttribute("data-density")).toBe("comfortable");
    applyTheme("default", { ...DEFAULT_CUSTOM, density: "compact" });
    expect(document.documentElement.getAttribute("data-density")).toBe("compact");
  });

  it("自定义圆角写入 --radius-lg（有范围约束）", () => {
    applyTheme("default", { ...DEFAULT_CUSTOM, radius: 20 });
    expect(document.documentElement.style.getPropertyValue("--radius-lg")).toBe("20px");
    // 超范围被钳制
    applyTheme("default", { ...DEFAULT_CUSTOM, radius: 999 });
    expect(parseInt(document.documentElement.style.getPropertyValue("--radius-lg"), 10))
      .toBe(RADIUS_RANGE.max);
  });

  it("强调色色相微调写入 --accent，0° 时也写入基准色", () => {
    applyTheme("default", { ...DEFAULT_CUSTOM, accentHue: 12 });
    const accent = document.documentElement.style.getPropertyValue("--accent");
    expect(accent).toMatch(/^hsl\(/);
    expect(document.documentElement.style.getPropertyValue("--accent-soft")).toMatch(/^hsl\(/);
    applyTheme("default", { ...DEFAULT_CUSTOM, accentHue: 0 });
    expect(document.documentElement.style.getPropertyValue("--accent")).toMatch(/^hsl\(/);
  });

  it("自定义持久化 roundtrip", () => {
    const c = { accentHue: 8, density: "compact", radius: 18 };
    saveCustom(c);
    expect(loadCustom()).toEqual(c);
    expect(loadCustom().accentHue).toBe(8);
  });

  it("自定义范围常量合理", () => {
    expect(ACCENT_HUE_RANGE.min).toBeLessThan(0);
    expect(ACCENT_HUE_RANGE.max).toBeGreaterThan(0);
    expect(RADIUS_RANGE.min).toBeLessThan(RADIUS_RANGE.max);
  });

  it("默认主题 accent 已暖橙化（色相 ~18° 暖调）", () => {
    applyTheme("default");
    const dHue = parseHslHue(document.documentElement.style.getPropertyValue("--accent"));
    expect(dHue).toBeGreaterThan(0);
    expect(dHue).toBeLessThan(40); // 暖橙（原蓝 ~221°）
  });

  it("index.css：仅保留默认主题块，mint/sakura/dark 已移除", () => {
    const css = fs.readFileSync(path.resolve(__dirname, "../index.css"), "utf8");
    expect(css).toContain("--accent: #b25b36;");
    expect(css).toContain("--accent-hover: #9c4c2c;");
    expect(css).toContain("--accent-soft: #f9ede5;");
    expect(css).toContain("--font-heading:");
    expect(css).not.toContain('html[data-theme="mint"]');
    expect(css).not.toContain('html[data-theme="sakura"]');
    expect(css).not.toContain('html[data-theme="dark"]');
    // 氛围色强度保持（浅色克制）
    const root = css.slice(0, css.indexOf("html[data-theme"));
    expect(root).toContain("--ambient-alpha: 0.14;");
  });

  it("编目抽屉默认色板（ADR 0056）：纸感底色/分层 + --font-mono + 近直角圆角 token", () => {
    const css = fs.readFileSync(path.resolve(__dirname, "../index.css"), "utf8");
    const root = css.slice(0, css.indexOf("html[data-theme"));
    expect(root).toContain("--bg: #f4efe3;");          // 米黄纸底
    expect(root).toContain("--surface-0: #efe8d8;");   // 纸感分层
    expect(root).toContain("--surface-1: #faf5ea;");
    expect(root).toContain("--surface-2: #e9dfca;");
    expect(root).toContain("--font-mono:");            // 等宽编号字体 token
    expect(root).toContain("--radius-lg: 10px;");      // 近直角（原 16px）
    expect(root).toContain("--radius-sm: 4px;");
  });

  it("暖橙 accent 下书脊色相基准也是暖调（hexToHsl 基准），依赖 accent 的效果协调", () => {
    const { hexToHsl } = require("../bookshelf.js");
    expect(Math.round(hexToHsl("#b25b36").h)).toBe(18); // 书脊色相旋转基准为暖橙
  });
});
