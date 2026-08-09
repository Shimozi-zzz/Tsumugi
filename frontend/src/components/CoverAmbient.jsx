// 封面取色 hover 高光（ADR 0037）
// 网格卡片 / 书脊 hover 时的封面取色柔和光晕：
// - hover 才触发取色（复用 ambient.js 的 URL 缓存，重复 hover 不重复计算）；
// - 强度明显弱于详情面板氛围：alpha = --ambient-alpha × alphaFactor（默认 0.6，
//   浅色≈0.10、深色≈0.18）；
// - 无封面/取色失败 → 回退主题 accent 高亮（仍保留 hover 反馈）；
// - 进出平滑 transition。
import React, { useEffect, useRef, useState } from "react";
import { extractPalette } from "../ambient.js";

function ambientAlpha() {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue("--ambient-alpha").trim();
    const n = parseFloat(v);
    if (Number.isFinite(n)) return n;
  } catch { /* ignore */ }
  return 0.16;
}

export default function CoverAmbient({
  src, alphaFactor = 0.6, radius = "var(--radius-lg)", blur = 18, spread = 2,
  className = "", children,
}) {
  const [hovered, setHovered] = useState(false);
  const [paletteColor, setPaletteColor] = useState(null); // rgba 字符串
  const lastSrc = useRef(null);

  useEffect(() => {
    if (!hovered) return;
    if (src !== lastSrc.current) { setPaletteColor(null); lastSrc.current = src; }
    if (!src) return; // 无封面 → 保持 null（走 accent 降级高光）
    let cancelled = false;
    extractPalette(src).then((p) => {
      if (cancelled) return;
      const alpha = ambientAlpha() * alphaFactor;
      setPaletteColor(p && p.primary ? `rgba(${p.primary.r},${p.primary.g},${p.primary.b},${alpha})` : null);
    });
    return () => { cancelled = true; };
  }, [hovered, src, alphaFactor]);

  // hover 中：优先封面取色；取色失败/无封面 → 主题 accent 降级高光；否则透明
  const glow = hovered
    ? (paletteColor || "color-mix(in srgb, var(--accent) 16%, transparent)")
    : "0 0 0px 0px transparent";

  return (
    <div className={"relative " + className}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}>
      <div aria-hidden data-testid="ambient-hover"
        style={{
          position: "absolute", inset: 0, borderRadius: radius,
          pointerEvents: "none", zIndex: 1,
          boxShadow: `0 0 ${blur}px ${spread}px ${glow}`,
          transition: "box-shadow 0.3s ease",
        }} />
      {children}
    </div>
  );
}
