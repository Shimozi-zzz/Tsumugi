// 安利卡弹层：SVG 实时预览 + 下载 PNG（浏览器端导出，后端不参与）
import React, { useEffect, useState } from "react";
import { fetchItemDetail, fetchItemReviews, filePathToUrl } from "../api.js";
import {
  buildShareCardSvg, selectQuote, imageUrlToDataUrl, downloadSvgAsPng,
} from "../shareCard.js";

export default function ShareCardModal({ item, onClose }) {
  const [svg, setSvg] = useState(null);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [detail, reviews] = await Promise.all([
          fetchItemDetail(item.id),
          fetchItemReviews(item.id),
        ]);
        const cover = filePathToUrl(detail.file_path) || detail.image_url || null;
        const coverData = await imageUrlToDataUrl(cover);
        if (cancelled) return;
        const quote = selectQuote(reviews);
        const spoilerOnly = Array.isArray(reviews) && reviews.length > 0 && !quote;
        setSvg(buildShareCardSvg({
          title: detail.title,
          coverHref: coverData,
          rating: detail.my_rating,
          quote,
          spoilerOnly,
          source: detail.source,
        }));
      } catch (e) {
        if (!cancelled) setError(e.message);
      }
    })();
    return () => { cancelled = true; };
  }, [item.id]);

  async function handleDownload() {
    if (!svg || downloading) return;
    setDownloading(true);
    try {
      await downloadSvgAsPng(svg, `anli-${String(item.id).slice(0, 8)}.png`);
    } catch (e) {
      setError(e.message);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(10,12,20,0.55)" }} onClick={onClose}>
      <div className="desk-askbar p-5 w-full max-w-xl flex flex-col items-center"
        onClick={(e) => e.stopPropagation()}
        style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", borderRadius: "var(--radius-floating)" }}>
        <div className="flex items-center justify-between w-full mb-3">
          <h3 className="text-sm font-medium" style={{ color: "var(--text)" }}>安利卡预览</h3>
          <button onClick={onClose} className="text-sm px-2 py-0.5 rounded-lg"
            style={{ color: "var(--text-secondary)" }}>✕</button>
        </div>

        {error && <p className="text-xs mb-2" style={{ color: "var(--danger)" }}>{error}</p>}

        <div className="w-full flex justify-center mb-4">
          {svg ? (
            <div className="rounded-2xl overflow-hidden shadow-lg max-h-[60vh]"
              dangerouslySetInnerHTML={{ __html: svg }} />
          ) : (
            <div className="w-80 h-96 rounded-2xl flex items-center justify-center text-sm"
              style={{ backgroundColor: "rgba(255,255,255,0.05)", color: "var(--text-secondary)" }}>
              生成中…
            </div>
          )}
        </div>

        <button onClick={handleDownload} disabled={!svg || downloading}
          className="px-5 py-2 rounded-xl text-sm font-medium disabled:opacity-40"
          style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
          {downloading ? "导出中…" : "下载图片 (PNG)"}
        </button>
        <p className="mt-2 text-[11px]" style={{ color: "var(--text-secondary)" }}>
          剧透内容不会出现在卡片里；评分来自我的平均分。
        </p>
      </div>
    </div>
  );
}
