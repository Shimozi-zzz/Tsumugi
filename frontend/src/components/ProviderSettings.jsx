// LLM Provider 设置：Provider 选择 + 表单 + 测试连接 + Ollama 引导
import React, { useEffect, useState } from "react";
import {
  fetchLLMProviders, saveLLMProvider, enableLLMProvider, deleteLLMProvider,
  testLLMConnection, fetchOllamaStatus,
} from "../api.js";
import { toast } from "../toast.js";

const PRESETS = [
  { key: "deepseek", label: "DeepSeek", provider_type: "openai_compatible",
    base_url: "https://api.deepseek.com/v1", model_id: "deepseek-chat", api_key_ref: "{DEEPSEEK_API_KEY}" },
  { key: "openai", label: "OpenAI 兼容（自定义）", provider_type: "openai_compatible", base_url: "", model_id: "", api_key_ref: "" },
  { key: "ollama", label: "Ollama 本地", provider_type: "ollama",
    base_url: "http://localhost:11434/v1", model_id: "qwen2.5:3b", api_key_ref: "" },
];

export default function ProviderSettings() {
  const [providers, setProviders] = useState([]);
  const [enabledName, setEnabledName] = useState(null);
  const [presetKey, setPresetKey] = useState("ollama");
  const [form, setForm] = useState({ name: "", provider_type: "ollama", base_url: "http://localhost:11434/v1", model_id: "qwen2.5:3b", api_key_ref: "" });
  const [saving, setSaving] = useState(false);
  const [ollama, setOllama] = useState({ available: false, models: [], reason: "" });

  const load = () => {
    fetchLLMProviders().then((d) => {
      setProviders(d.providers);
      setEnabledName(d.enabled_name);
    }).catch(() => {});
    fetchOllamaStatus().then(setOllama).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  function applyPreset(key) {
    setPresetKey(key);
    const p = PRESETS.find((x) => x.key === key);
    setForm({ name: key, provider_type: p.provider_type, base_url: p.base_url,
      model_id: p.model_id, api_key_ref: p.api_key_ref });
    setTestResult(null);
  }

  async function handleSave(e) {
    e.preventDefault();
    setSaving(true);
    try {
      await saveLLMProvider(form);
      load();
      toast.success(`已保存「${form.name}」`);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    const payload = { name: form.name, provider_type: form.provider_type,
      base_url: form.base_url, model_id: form.model_id, api_key_ref: form.api_key_ref };
    const r = await testLLMConnection(payload);
    if (r.ok) toast.success(r.message);
    else toast.error(r.message);
  }

  const isOllama = form.provider_type === "ollama";

  return (
    <div className="space-y-4">
      <div className="desk-askbar rounded-2xl p-5"
        style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)" }}>
        <h3 className="text-sm font-medium mb-2">选择模型后端</h3>
        <div className="flex flex-wrap gap-2 mb-3">
          {PRESETS.map((p) => (
            <button type="button" key={p.key} onClick={() => applyPreset(p.key)}
              className={"settings-option" + (presetKey === p.key ? " settings-option-active" : "")}>
              {p.label}
            </button>
          ))}
        </div>

        <form onSubmit={handleSave} className="flex flex-col gap-2.5">
          <input placeholder="配置名称（如 deepseek / ollama）" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="tsm-input border rounded px-2.5 py-2 text-sm" />
          <input placeholder="Base URL" value={form.base_url}
            onChange={(e) => setForm({ ...form, base_url: e.target.value })}
            className="tsm-input border rounded px-2.5 py-2 text-sm" />
          <input placeholder="Model ID（如 deepseek-chat / qwen2.5:3b）" value={form.model_id}
            onChange={(e) => setForm({ ...form, model_id: e.target.value })}
            className="tsm-input border rounded px-2.5 py-2 text-sm" />
          {isOllama ? (
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
              Ollama 本地无需 API Key（走本机服务）。
            </p>
          ) : (
            <>
              <input placeholder="填 {ENV_VAR} 引用环境变量，或直接粘贴真实 Key" value={form.api_key_ref}
                onChange={(e) => setForm({ ...form, api_key_ref: e.target.value })}
                className="tsm-input border rounded px-2.5 py-2 text-sm" />
              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                两种方式均可：填 <code>{`{DEEPSEEK_API_KEY}`}</code> 引用已有环境变量，
                或直接粘贴真实 Key（后端自动写入 .env，<b>不落库明文</b>）。
              </p>
            </>
          )}
          <div className="flex gap-2">
            <button type="submit" disabled={saving} className="settings-action">
              {saving ? "保存中…" : "保存配置"}
            </button>
            <button type="button" onClick={handleTest} className="settings-action">
              测试连接
            </button>
          </div>
        </form>
      </div>

      <div className="desk-askbar rounded-2xl p-5"
        style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)" }}>
        <h3 className="text-sm font-medium mb-2">Ollama 本地方案</h3>
        {ollama.available ? (
          <p className="text-xs mb-2" style={{ color: "var(--ok)" }}>
            检测到本地 Ollama 服务，已安装模型：{ollama.models.join(", ") || "（无）"}
          </p>
        ) : (
          <>
            <p className="text-xs mb-2" style={{ color: "var(--text-secondary)" }}>
              未检测到本地 Ollama（{ollama.reason || "无法连接 localhost:11434"}）。
              零成本本地方案，手动两步即可：
            </p>
            <ol className="text-xs space-y-1.5 mb-2" style={{ color: "var(--text-secondary)" }}>
              <li>1. 到 <a href="https://ollama.com/download" target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>ollama.com/download</a> 下载安装 Ollama</li>
              <li>2. 终端运行以下命令拉取推荐模型（对中文友好、体积适中）：</li>
            </ol>
            <div className="flex items-center gap-2 mb-2">
              <code className="px-2.5 py-1.5 rounded-lg text-xs" style={{ backgroundColor: "rgba(255,255,255,0.06)" }}>
                ollama pull qwen2.5:3b
              </code>
              <button
                onClick={() => { try { navigator.clipboard.writeText("ollama pull qwen2.5:3b"); } catch {} }}
                className="px-2 py-1 rounded-lg text-xs"
                style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
                复制命令
              </button>
            </div>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
              完成后在左侧选择"Ollama 本地"→ 填 model_id（如 qwen2.5:3b）→ 保存并启用。
            </p>
          </>
        )}
      </div>

      <div className="desk-askbar rounded-2xl p-5"
        style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)" }}>
        <h3 className="text-sm font-medium mb-2">已保存配置</h3>
        {providers.length === 0 && (
          <p className="text-xs" style={{ color: "var(--text-secondary)" }}>暂无已保存的 Provider。</p>
        )}
        <ul className="space-y-1.5">
          {providers.map((p) => (
            <li key={p.name} className="flex items-center justify-between px-2 py-1.5 rounded-lg text-sm"
              style={{ backgroundColor: "rgba(255,255,255,0.04)" }}>
              <div className="flex items-center gap-2 min-w-0">
                <span className="font-medium truncate">{p.name}</span>
                <span className="text-xs px-1.5 py-0.5 rounded-full"
                  style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
                  {p.provider_type === "ollama" ? "本地" : "远程"}
                </span>
                {p.enabled && (
                  <span className="text-xs px-1.5 py-0.5 rounded-full"
                    style={{ backgroundColor: "var(--tag-bg)", color: "var(--tag-text)" }}>已启用</span>
                )}
                <span className="text-xs truncate" style={{ color: "var(--text-secondary)" }}>{p.model_id}</span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button onClick={() => { applyPreset(p.name); setForm({ name: p.name, provider_type: p.provider_type, base_url: p.base_url, model_id: p.model_id, api_key_ref: p.api_key_ref }); setPresetKey(p.name); }}
                  className="text-xs" style={{ color: "var(--text-secondary)" }}>编辑</button>
                <button onClick={async () => { await enableLLMProvider(p.name, !p.enabled); load(); }}
                  className="text-xs" style={{ color: "var(--accent)" }}>
                  {p.enabled ? "停用" : "启用"}
                </button>
                <button onClick={async () => { await deleteLLMProvider(p.name); load(); }}
                  className="text-xs" style={{ color: "var(--danger)" }}>删除</button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
