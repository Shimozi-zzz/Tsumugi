// 主题系统测试：3 套收敛主题 + 有约束的自定义层（强调色色相/密度/圆角）
import { describe, it, expect, beforeEach } from "vitest";
import {
  THEMES, loadTheme, applyTheme, loadCustom, saveCustom,
  DEFAULT_CUSTOM, ACCENT_HUE_RANGE, RADIUS_RANGE,
} from "../themes.js";

describe("theme system", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("data-density");
  });

  it("THEMES 收敛为三套（经典白/薄荷/樱花）", () => {
    expect(THEMES.map((t) => t.key)).toEqual(["default", "mint", "sakura"]);
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
});
