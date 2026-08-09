// 神殿首页（ADR 0039，Layer 1：不含角色台词系统）
// 用空间隐喻 + 留白 + 仪式节奏传达"被认真对待的空间"，不是数据仪表盘：
// - 纵轴构图：上方鸟居轮廓线（极简几何符号）→ 中部搜索栏（焦点"祭坛"）→
//   下方"最近供奉"（最近收藏的封面以纵深/退级方式排布，非平铺网格）；
// - 氛围：最近活跃作品的封面主色作为环境光（radial 渐变），随"最近在关注什么"
//   变化；无数据/取色失败回退主题表面色；
// - 仪式过渡：每日首次打开播放"暗幕渐亮 + 内容渐次呈现"（纯 CSS transition），
//   同一天后续访问简化；点击/按键可跳过。
import React, { useEffect, useState } from "react";
import { filePathToUrl } from "../api.js";
import { extractPalette } from "../ambient.js";

const RITUAL_KEY = "tsumugi-home-ritual";

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** 每日首次打开才播放完整仪式。注意：这是纯查询，不在 useState 初始器里写
 * localStorage——React StrictMode 会双调初始器，若在初始器里 setItem 会提前消耗
 * "当天已播放"标记。改为"播放时再标记"（见 reveal effect）。 */
function shouldPlayRitual() {
  try { return localStorage.getItem(RITUAL_KEY) !== todayStr(); } catch { return false; }
}

function markRitualShown() {
  try { localStorage.setItem(RITUAL_KEY, todayStr()); } catch { /* ignore */ }
}

function ambientAlpha() {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue("--ambient-alpha").trim();
    const n = parseFloat(v);
    if (Number.isFinite(n)) return n;
  } catch { /* ignore */ }
  return 0.16;
}

function coverOf(it) {
  if (it.file_path) { const u = filePathToUrl(it.file_path); if (u) return u; }
  return it.image_url || null;
}

// 极简鸟居轮廓线（几何符号，点到为止，非写实场景）
function ToriiOutline() {
  return (
    <svg viewBox="0 0 200 160" width={150} height={120} className="shrine-item"
      aria-hidden fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
      style={{ color: "var(--accent)", opacity: 0.4 }}>
      <path d="M38 50 Q100 38 162 50" />   {/* 笠木（微翘） */}
      <path d="M34 76 H166" />              {/* 贯 */}
      <path d="M54 50 V146 M146 50 V146" /> {/* 柱 */}
      <path d="M96 50 V108 M104 50 V108" /> {/* 中央加固 */}
    </svg>
  );
}

// 最近供奉：最近收藏的封面以纵深/退级方式排布（中心突出、两侧退后变淡）
function RecentOfferings({ items, recentReviews, onOpenWork }) {
  if (!items || items.length === 0) return null;
  const shown = items.slice(0, 5);
  const center = (shown.length - 1) / 2;
  return (
    <div className="shrine-item flex flex-col items-center gap-2.5">
      <div className="text-[11px] tracking-[0.3em]" style={{ color: "var(--text-secondary)" }}>最近供奉</div>
      <div className="flex items-end justify-center gap-3">
        {shown.map((it, i) => {
          const dist = Math.abs(i - center);
          const cover = coverOf(it);
          return (
            <button key={it.id} type="button" onClick={() => onOpenWork?.(it)} title={it.title}
              className="transition-transform duration-300"
              style={{
                transform: `translateY(${dist * 12}px) scale(${1 - dist * 0.07})`,
                opacity: 1 - dist * 0.16,
              }}>
              {cover ? (
                <img src={cover} alt="" loading="lazy"
                  className="rounded-lg object-cover"
                  style={{ width: 58, height: 80, boxShadow: "var(--shadow-md)", background: "var(--card-thumb)" }}
                  onError={(e) => { e.target.style.display = "none"; }} />
              ) : (
                <div className="rounded-lg flex items-center justify-center"
                  style={{ width: 58, height: 80, background: "var(--card-thumb)", color: "var(--accent)", fontSize: 18 }}>
                  {(it.title || "?").slice(0, 1)}
                </div>
              )}
            </button>
          );
        })}
      </div>
      {recentReviews && recentReviews.length > 0 && (
        <div className="text-[11px] text-center leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          {recentReviews.slice(0, 2).map((r) => `「${r.title || "读后感"}」`).join(" · ")}
        </div>
      )}
    </div>
  );
}

export default function HomeShrine({ representativeCover, recentItems, recentReviews, onOpenWork, children }) {
  const [palette, setPalette] = useState(null);
  const [ritual, setRitual] = useState(() => shouldPlayRitual());
  const [revealed, setRevealed] = useState(false);
  const [skipped, setSkipped] = useState(false);

  // 氛围色：代表封面主色 → 环境光；无封面/取色失败 → 回退主题表面色
  useEffect(() => {
    if (!representativeCover) { setPalette(null); return; }
    let cancelled = false;
    extractPalette(representativeCover).then((p) => {
      if (!cancelled) setPalette(p && p.primary ? p.primary : null);
    });
    return () => { cancelled = true; };
  }, [representativeCover]);

  // 仪式：下一帧开始"揭幕"（暗幕渐亮 + 内容渐次呈现）；播放即标记当天已看
  useEffect(() => {
    if (!ritual) { setRevealed(true); return; }
    markRitualShown();
    const t = setTimeout(() => setRevealed(true), 60);
    return () => clearTimeout(t);
  }, [ritual]);

  // 可跳过：任意点击 / 按键直接完成揭幕
  useEffect(() => {
    if (!ritual) return;
    const skip = () => { setSkipped(true); setRevealed(true); };
    window.addEventListener("keydown", skip);
    document.addEventListener("click", skip);
    return () => {
      window.removeEventListener("keydown", skip);
      document.removeEventListener("click", skip);
    };
  }, [ritual]);

  const alpha = ambientAlpha() * 0.7; // 首页环境光比详情面板更收敛
  const ambientBg = palette
    ? `radial-gradient(90% 55% at 50% 6%, rgba(${palette.r},${palette.g},${palette.b},${alpha}), transparent 70%)`
    : "none";

  const cls = ["shrine", ritual ? "shrine-ritual" : "", revealed ? "shrine-revealed" : "", skipped ? "shrine-skip" : ""].filter(Boolean).join(" ");

  return (
    <div className={"h-full " + cls}>
      {/* 暗幕（仪式时从暗到亮） */}
      <div className="shrine-veil" />
      {/* 环境光（封面取色） */}
      <div className="absolute inset-0 pointer-events-none"
        style={{ opacity: palette ? 1 : 0, transition: "opacity 0.8s ease", background: ambientBg, zIndex: 0 }} />
      {/* 内容：纵轴构图 */}
      <div className="relative z-1 h-full flex flex-col items-center justify-center px-6" style={{ paddingBottom: "6vh" }}>
        <ToriiOutline />
        <div className="shrine-item mt-6 w-full max-w-xl">
          {children}
        </div>
        <div className="mt-8">
          <RecentOfferings items={recentItems} recentReviews={recentReviews} onOpenWork={onOpenWork} />
        </div>
        {ritual && !revealed && (
          <div className="shrine-item absolute bottom-8 text-[10px] tracking-widest"
            style={{ color: "var(--text-secondary)" }}>点击任意处 跳过</div>
        )}
      </div>
    </div>
  );
}
