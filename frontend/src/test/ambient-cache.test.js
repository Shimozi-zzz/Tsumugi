// 封面取色缓存复用（ADR 0034/0037）：同一封面第二次调用命中缓存、不重复计算
import { describe, it, expect, beforeEach } from "vitest";
import { clearPaletteCache, extractPalette } from "../ambient.js";

beforeEach(() => { clearPaletteCache(); });

describe("extractPalette 缓存复用", () => {
  it("同一封面返回同一个缓存 Promise（不重复计算）", () => {
    const p1 = extractPalette("https://x/cover.jpg");
    const p2 = extractPalette("https://x/cover.jpg");
    expect(p1).toBe(p2); // 同一引用 = 命中缓存
  });

  it("不同封面各自计算（不同 Promise）", () => {
    const a = extractPalette("https://x/a.jpg");
    const b = extractPalette("https://x/b.jpg");
    expect(a).not.toBe(b);
  });

  it("同一封面第二次调用不再进入计算（对真实计算打桩验证）", async () => {
    // 直接验证内部计算函数调用次数：_computePalette 应只被调用一次
    const calls = [];
    const orig = globalThis.document.createElement.bind(globalThis.document);
    globalThis.document.createElement = (tag) => {
      if (tag === "canvas") calls.push("canvas");
      return orig(tag);
    };
    try {
      await extractPalette("https://x/z.jpg");
      await extractPalette("https://x/z.jpg");
    } finally {
      globalThis.document.createElement = orig;
    }
    // jsdom 无 canvas 2d 上下文，_computePalette 到 getContext 即返回 null；此处验证
    // 同一 URL 只创建一次 canvas（即只计算一次）
    expect(calls.filter((c) => c === "canvas").length).toBe(1);
  });

  it("无 src 直接返回 null，不缓存", () => {
    expect(extractPalette("")).toBeNull();
  });
});
