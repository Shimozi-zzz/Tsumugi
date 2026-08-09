// 封面动态取色（ADR 0034：Ambient Color from Cover Art）
// - 前端 Canvas 实时提取（复用安利卡"转 data URL 内联"防 Canvas taint 方案，
//   见 imageUrlToDataUrl）；结果按封面 URL 缓存（模块级 Map），避免反复重算；
// - 算法：图像缩小到 32×32 → RGB 粗量化直方图 → 取主导色 + 第二主色；
// - 边界：加载失败 / 非 CORS 远程 / 纯黑白灰（不鲜明）→ 返回 null，前端回退到
//   主题表面色，不强行渲染看不清的效果。
import { imageUrlToDataUrl } from "./shareCard.js";

const cache = new Map(); // src -> Promise<palette|null>
const CACHE_MAX = 200;

export function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h = 0, s = 0;
  const l = (max + min) / 2;
  const d = max - min;
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

/** 是否"足够鲜明"（可作氛围色）：排除近灰/纯黑/纯白（对比度过低）。 */
export function isVivid(r, g, b) {
  const { s, l } = rgbToHsl(r, g, b);
  return s >= 0.10 && l > 0.12 && l < 0.90;
}

/**
 * 从 RGBA 像素数组提取 1-2 个主色调。
 * @returns {{primary:{r,g,b}, secondary:{r,g,b}|null} | null}（无鲜明色时 null）
 */
export function dominantColors(pixels) {
  const buckets = new Map();
  const shift = 4; // 量化：高 4 位 → 4096 桶
  for (let i = 0; i < pixels.length; i += 4) {
    const a = pixels[i + 3];
    if (a < 100) continue; // 跳过半透明像素
    const r = pixels[i], g = pixels[i + 1], b = pixels[i + 2];
    const key = (r >> shift) << 8 | (g >> shift) << 4 | (b >> shift);
    let e = buckets.get(key);
    if (!e) { e = { r: 0, g: 0, b: 0, count: 0 }; buckets.set(key, e); }
    e.r += r; e.g += g; e.b += b; e.count += 1;
  }
  const avg = (e) => ({ r: Math.round(e.r / e.count), g: Math.round(e.g / e.count), b: Math.round(e.b / e.count) });
  const sorted = [...buckets.values()].sort((a, b) => b.count - a.count);
  const primaryEntry = sorted.find((e) => { const c = avg(e); return isVivid(c.r, c.g, c.b); });
  if (!primaryEntry) return null; // 封面整体偏黑白灰 → 降级
  const primary = avg(primaryEntry);

  let secondary = null;
  const secondaryEntry = sorted.find((e) => e !== primaryEntry && isVivid(...Object.values(avg(e))));
  if (secondaryEntry) {
    const q = avg(secondaryEntry);
    const h1 = rgbToHsl(primary.r, primary.g, primary.b).h;
    const h2 = rgbToHsl(q.r, q.g, q.b).h;
    const hueDiff = Math.min(Math.abs(h1 - h2), 360 - Math.abs(h1 - h2));
    const lDiff = Math.abs(rgbToHsl(primary.r, primary.g, primary.b).l - rgbToHsl(q.r, q.g, q.b).l);
    if (hueDiff > 30 || lDiff > 0.2) secondary = q; // 与主色差异足够才作为第二主色
  }
  return { primary, secondary };
}

/** 内部计算（Canvas 读像素 → 直方图主导色）。独立导出以便测试验证缓存命中。 */
export async function _computePalette(src, size) {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  const read = async (imgSrc) => {
    const img = await new Promise((res, rej) => {
      const i = new Image();
      i.onload = () => res(i);
      i.onerror = () => rej(new Error("load"));
      i.src = imgSrc;
    });
    ctx.drawImage(img, 0, 0, size, size);
    return dominantColors(ctx.getImageData(0, 0, size, size).data);
  };
  try {
    // 直接读（同源 /static 成功；跨域会因 taint 抛错）
    return await read(src);
  } catch {
    // taint 或加载失败 → 转 data URL（CORS fetch）再读
    const dataUrl = await imageUrlToDataUrl(src);
    if (!dataUrl) return null;
    return await read(dataUrl);
  }
}

/**
 * 从封面地址提取主色调（前端 Canvas）。带缓存：同一 URL 只算一次，命中时直接返回
 * 同一 Promise（不重复计算）。返回 Promise<{primary, secondary}|null> 或 null（无 src）。
 * 非 async：避免 async 每次调用都包一层新 Promise 包装，破坏缓存引用的可观察性。
 */
export function extractPalette(src, { size = 32 } = {}) {
  if (!src) return null;
  if (cache.has(src)) return cache.get(src);
  const promise = _computePalette(src, size).catch(() => null);
  cache.set(src, promise);
  if (cache.size > CACHE_MAX) {
    const first = cache.keys().next().value;
    cache.delete(first);
  }
  return promise;
}

/** 测试/清理用：清空取色缓存。 */
export function clearPaletteCache() {
  cache.clear();
}
