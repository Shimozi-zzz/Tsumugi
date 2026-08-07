// Bangumi 账号连接 + 收藏批量导入（OAuth 引导 / 连接状态 / 批量导入进度 / 结果摘要）
import React, { useEffect, useState } from "react";
import { toast } from "../toast.js";
import {
  fetchBangumiOAuthStatus, saveBangumiOAuthConfig, fetchBangumiAuthorizeUrl,
  disconnectBangumi, startBangumiImport, fetchBangumiImportStatus,
} from "../api.js";

export default function BangumiPanel() {
  const [status, setStatus] = useState(null);
  const [cid, setCid] = useState("");
  const [csec, setCsec] = useState("");
  const [pollingConn, setPollingConn] = useState(false);
  const [job, setJob] = useState(null);
  const [importing, setImporting] = useState(false);

  const load = () => fetchBangumiOAuthStatus().then(setStatus).catch(() => {});
  useEffect(() => { load(); }, []);

  async function saveConfig(e) {
    e.preventDefault();
    try {
      await saveBangumiOAuthConfig({ client_id: cid.trim(), client_secret: csec.trim() });
      toast.success("应用凭证已保存（写入 .env，不落库）");
      setCid(""); setCsec("");
      load();
    } catch (err) { toast.error(err.message); }
  }

  async function connect() {
    try {
      const { authorize_url } = await fetchBangumiAuthorizeUrl();
      window.open(authorize_url, "_blank");
      setPollingConn(true);
      toast.info("已在新窗口打开 Bangumi 授权页，完成授权后自动检测…");
      let done = false;
      const iv = setInterval(async () => {
        if (done) return;
        const s = await fetchBangumiOAuthStatus().catch(() => null);
        if (s && s.connected) {
          done = true; clearInterval(iv); setPollingConn(false); setStatus(s);
          toast.success("Bangumi 连接成功");
        }
      }, 1200);
      setTimeout(() => { if (!done) { clearInterval(iv); setPollingConn(false); } }, 120000);
    } catch (err) { toast.error(err.message); }
  }

  async function disconnect() {
    try {
      await disconnectBangumi();
      toast.info("已断开 Bangumi 连接");
      setStatus((s) => ({ ...(s || {}), connected: false }));
    } catch (err) { toast.error(err.message); }
  }

  async function startImport() {
    setImporting(true);
    try {
      const { job_id } = await startBangumiImport();
      toast.info("开始导入 Bangumi 收藏…");
      setJob({ job_id, state: "running", current: 0, total: 0, imported: 0, skipped: 0, failed: 0, failures: [] });
      let done = false;
      const iv = setInterval(async () => {
        if (done) return;
        const j = await fetchBangumiImportStatus(job_id).catch(() => null);
        if (j) {
          setJob(j);
          if (j.state === "done" || j.state === "error") {
            done = true; clearInterval(iv); setImporting(false);
            if (j.state === "done") toast.success(j.message || "导入完成");
            else toast.error(j.message || "导入失败");
          }
        }
      }, 800);
      setTimeout(() => { if (!done) { clearInterval(iv); setImporting(false); } }, 1800000);
    } catch (err) { toast.error(err.message); setImporting(false); }
  }

  const configured = status?.config_configured;
  const connected = status?.connected;
  const pct = job && job.total > 0 ? Math.min(Math.round((job.current / job.total) * 100), 100) : 0;

  return (
    <div className="space-y-4">
      <div className="desk-askbar p-5">
        <h3 className="text-sm font-medium mb-1">连接 Bangumi 账号</h3>
        <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
          授权后可一键把你 Bangumi 上的完整收藏（追番状态 + 个人评分）批量导入本地图书馆。
        </p>

        {!configured && (
          <div className="text-sm space-y-2">
            <ol className="list-decimal list-inside text-xs" style={{ color: "var(--text-secondary)" }}>
              <li>到 <a href="https://bgm.tv/dev/app" target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>Bangumi 开发者后台</a> 注册一个应用，获取 client_id / client_secret；</li>
              <li>在应用的回调地址里填：<code className="px-1 py-0.5 rounded" style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
                {status?.redirect_uri || "http://127.0.0.1:8001/api/bangumi/oauth/callback"}</code></li>
              <li>把 client_id / client_secret 填到下面并保存（自动写入 .env，不落库明文）。</li>
            </ol>
            <form onSubmit={saveConfig} className="flex flex-col gap-2 pt-1">
              <input placeholder="client_id" value={cid} onChange={(e) => setCid(e.target.value)}
                className="tsm-input border rounded px-2.5 py-2 text-sm" />
              <input placeholder="client_secret" type="password" value={csec} onChange={(e) => setCsec(e.target.value)}
                className="tsm-input border rounded px-2.5 py-2 text-sm" />
              <button type="submit" className="px-3 py-1.5 rounded-xl text-sm font-medium self-start"
                style={{ backgroundColor: "var(--accent)", color: "#fff" }}>保存凭证</button>
            </form>
          </div>
        )}

        {configured && !connected && (
          <div className="text-sm space-y-2">
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
              凭证已配置。点击下方按钮前往 Bangumi 授权（回调地址需已在开发者后台登记：{status?.redirect_uri}）。
            </p>
            <button onClick={connect} disabled={pollingConn}
              className="px-3 py-1.5 rounded-xl text-sm font-medium disabled:opacity-40"
              style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
              {pollingConn ? "等待授权完成…" : "连接 Bangumi 账号"}
            </button>
          </div>
        )}

        {connected && (
          <div className="text-sm space-y-3">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: "var(--ok)" }} />
              <span style={{ color: "var(--text)" }}>已连接</span>
              {status?.user_id && (
                <span className="text-xs px-1.5 py-0.5 rounded-full"
                  style={{ backgroundColor: "var(--tag-bg)", color: "var(--tag-text)" }}>
                  用户 {status.user_id}
                </span>
              )}
              <button onClick={disconnect} className="text-xs ml-2" style={{ color: "var(--danger)" }}>断开连接</button>
            </div>

            <button onClick={startImport} disabled={importing}
              className="px-4 py-1.5 rounded-xl text-sm font-medium disabled:opacity-40"
              style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
              {importing ? "导入中…" : "批量导入我的收藏"}
            </button>

            {job && (job.state === "running" || job.state === "pending" || job.state === "done") && (
              <div className="rounded-xl p-3"
                style={{ backgroundColor: "rgba(255,255,255,0.05)", border: "1px solid var(--panel-border)" }}>
                <div className="flex items-center justify-between text-xs mb-1">
                  <span style={{ color: "var(--text-secondary)" }}>已导入 {job.imported} / {job.total || "…"}</span>
                  <span style={{ color: "var(--accent)" }}>{job.total > 0 ? `${pct}%` : "…"}</span>
                </div>
                <div className="h-2 rounded-full overflow-hidden" style={{ backgroundColor: "rgba(255,255,255,0.08)" }}>
                  <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: "var(--accent)" }} />
                </div>
                <div className="text-[11px] mt-1.5" style={{ color: "var(--text-secondary)" }}>
                  跳过重复 {job.skipped} · 失败 {job.failed}
                  {job.failures?.length > 0 && (
                    <div className="mt-1 line-clamp-2">{job.failures.slice(0, 2).join("；")}</div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
