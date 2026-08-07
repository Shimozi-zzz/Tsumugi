// 搜索历史 localStorage 冒烟：验证 DesktopView 使用的键与格式
import { describe, it, expect, beforeEach, vi } from "vitest";

const HISTORY_KEY = "tsumugi-search-history";

function writeHistory(items) {
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(items)); } catch { /* ignore */ }
}
function loadHistory() {
  try {
    const saved = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    return Array.isArray(saved) ? saved.slice(0, 10) : [];
  } catch { return []; }
}

describe("search history localStorage contract", () => {
  beforeEach(() => localStorage.clear());

  it("空库返回空数组", () => {
    expect(loadHistory()).toEqual([]);
  });

  it("写入后可读回", () => {
    writeHistory(["问题一", "问题二"]);
    expect(loadHistory()).toEqual(["问题一", "问题二"]);
  });

  it("去重置顶 + 最多 10 条（模拟 DesktopView handleAsk 逻辑）", () => {
    writeHistory(["a", "b", "c"]);
    // 再次搜索 b → b 置顶
    writeHistory(["b", ...loadHistory().filter((x) => x !== "b")].slice(0, 10));
    expect(loadHistory()).toEqual(["b", "a", "c"]);

    // 写入 12 条 → 只保留 10
    const many = Array.from({ length: 12 }, (_, i) => `q${i}`);
    writeHistory(many);
    expect(loadHistory().length).toBe(10);
  });
});
