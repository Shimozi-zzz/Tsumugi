// 后端 API 封装
// API_BASE：
// - Web 模式（浏览器直接访问 Vite）：未注入 → "/api"，经 Vite 代理到后端 8001
// - 客户端模式（Electron preload 注入 tsumugiBridge）：→ http://127.0.0.1:8001
// 两种模式共享同一后端与数据，实现"web 与客户端同步"。
const API_BASE =
  (typeof window !== "undefined" &&
    window.tsumugiBridge &&
    window.tsumugiBridge.apiBase) ||
  "/api";

// 把后端存储的本地文件路径（如 "./data/uploads/x.png"）转成可访问的 URL。
// 约定：upload_dir -> /static/uploads，thumbnails_dir -> /static/thumbnails。
export function filePathToUrl(filePath) {
  if (!filePath) return null;
  const p = String(filePath).replace(/\\/g, "/");
  if (p.includes("/data/uploads/")) return `${API_BASE.replace(/\/api$/, "")}/static/uploads/${p.split("/data/uploads/")[1]}`;
  if (p.includes("/data/thumbnails/")) return `${API_BASE.replace(/\/api$/, "")}/static/thumbnails/${p.split("/data/thumbnails/")[1]}`;
  return null;
}

export async function uploadItem(file, title, tags) {
  const fd = new FormData();
  fd.append("file", file);
  if (title) fd.append("title", title);
  if (tags) fd.append("tags", tags);
  const resp = await fetch(`${API_BASE}/items/upload`, { method: "POST", body: fd });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || `上传失败（${resp.status}）`);
  return body;
}

export async function fetchItems(filters = {}) {
  // filters: { tag?: string[], tagMatch?: "any"|"all", type?: string, source?: string, skip?, limit? }
  const params = new URLSearchParams();
  if (filters.tag?.length) filters.tag.forEach((t) => params.append("tag", t));
  if (filters.tagMatch) params.set("tag_match", filters.tagMatch);
  if (filters.type) params.set("type", filters.type);
  if (filters.source) params.set("source", filters.source);
  if (filters.skip != null) params.set("skip", filters.skip);
  if (filters.limit != null) params.set("limit", filters.limit);
  const qs = params.toString();
  const resp = await fetch(`${API_BASE}/items${qs ? `?${qs}` : ""}`);
  if (!resp.ok) throw new Error("获取条目失败");
  return resp.json(); // { total, items }
}

export async function fetchTags() {
  const resp = await fetch(`${API_BASE}/tags`);
  if (!resp.ok) throw new Error("获取标签失败");
  return resp.json(); // [{ id, name, count }]
}

export async function renameTag(id, name) {
  const resp = await fetch(`${API_BASE}/tags/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "重命名标签失败");
  return body;
}

export async function deleteTag(id) {
  const resp = await fetch(`${API_BASE}/tags/${id}`, { method: "DELETE" });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || "删除标签失败");
  }
}

export async function mergeTags(targetTagId, sourceTagIds) {
  const resp = await fetch(`${API_BASE}/tags/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_tag_id: targetTagId, source_tag_ids: sourceTagIds }),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "合并标签失败");
  return body;
}

export async function deleteItem(id) {
  const resp = await fetch(`${API_BASE}/items/${id}`, { method: "DELETE" });
  if (!resp.ok) throw new Error("删除失败");
}

// ---- 批量操作 / 单条标签（交互打磨）----
export async function batchTagItems(itemIds, tagNames, mode = "add") {
  const resp = await fetch(`${API_BASE}/items/batch/tags`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item_ids: itemIds, tag_names: tagNames, mode }),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "批量打标签失败");
  return body;
}

export async function batchDeleteItems(itemIds) {
  const resp = await fetch(`${API_BASE}/items/batch/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item_ids: itemIds }),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "批量删除失败");
  return body;
}

export async function setItemTags(itemId, tagNames, mode = "add") {
  const resp = await fetch(`${API_BASE}/items/${itemId}/tags`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tag_names: tagNames, mode }),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "标签更新失败");
  return body;
}

// ---- Bangumi OAuth + 批量导入 ----

export async function fetchBangumiOAuthStatus() {
  const resp = await fetch(`${API_BASE}/bangumi/oauth/status`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "获取 Bangumi 连接状态失败");
  return body;
}

export async function saveBangumiOAuthConfig(cfg) {
  const resp = await fetch(`${API_BASE}/bangumi/oauth/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "保存应用凭证失败");
  return body;
}

export async function fetchBangumiAuthorizeUrl() {
  const resp = await fetch(`${API_BASE}/bangumi/oauth/authorize-url`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "获取授权链接失败");
  return body;
}

export async function disconnectBangumi() {
  const resp = await fetch(`${API_BASE}/bangumi/oauth/disconnect`, { method: "POST" });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "断开连接失败");
  return body;
}

export async function startBangumiImport() {
  const resp = await fetch(`${API_BASE}/bangumi/import`, { method: "POST" });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "启动导入失败");
  return body;
}

export async function fetchBangumiImportStatus(jobId) {
  const resp = await fetch(`${API_BASE}/bangumi/import/status?job_id=${encodeURIComponent(jobId)}`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "获取导入进度失败");
  return body;
}

// 上传条目封面图
export async function uploadItemCover(id, file) {
  const fd = new FormData();
  fd.append("file", file);
  const resp = await fetch(`${API_BASE}/items/${id}/cover`, { method: "POST", body: fd });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || `上传封面失败（${resp.status}）`);
  return body;
}

// ---- Review 读后感 ----

export async function fetchItemReviews(itemId) {
  const resp = await fetch(`${API_BASE}/items/${itemId}/reviews`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "获取书评失败");
  return body;
}

// 全局书评（时间倒序，用于构建"条目 → 追番状态"映射，ADR 0029 分组列表）
export async function fetchAllReviews(limit = 1000) {
  const resp = await fetch(`${API_BASE}/reviews?limit=${limit}`);
  const body = await resp.json().catch(() => []);
  if (!resp.ok) throw new Error(body.detail || "获取书评列表失败");
  return Array.isArray(body) ? body : [];
}

export async function createReview(itemId, payload) {
  const resp = await fetch(`${API_BASE}/items/${itemId}/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "创建书评失败");
  return body;
}

export async function updateReview(reviewId, payload) {
  const resp = await fetch(`${API_BASE}/reviews/${reviewId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "更新书评失败");
  return body;
}

export async function deleteReview(reviewId) {
  const resp = await fetch(`${API_BASE}/reviews/${reviewId}`, { method: "DELETE" });
  if (!resp.ok) throw new Error("删除书评失败");
}

// ---- LLM Provider（可插拔化）----

export async function fetchLLMProviders() {
  const resp = await fetch(`${API_BASE}/llm/providers`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "获取 Provider 失败");
  return body; // { providers, enabled_name }
}

export async function saveLLMProvider(payload) {
  const resp = await fetch(`${API_BASE}/llm/providers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "保存 Provider 失败");
  return body;
}

export async function enableLLMProvider(name, enabled = true) {
  const resp = await fetch(`${API_BASE}/llm/providers/${name}/enable?enabled=${enabled}`, {
    method: "PATCH",
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "切换 Provider 失败");
  return body;
}

export async function deleteLLMProvider(name) {
  const resp = await fetch(`${API_BASE}/llm/providers/${name}`, { method: "DELETE" });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "删除 Provider 失败");
  return body;
}

export async function testLLMConnection(payload) {
  const resp = await fetch(`${API_BASE}/llm/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "测试连接失败");
  return body; // { ok, message }
}

export async function fetchOllamaStatus() {
  const resp = await fetch(`${API_BASE}/llm/ollama-status`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error("检测 Ollama 失败");
  return body; // { available, models, reason }
}

// JSON 方式创建条目（note / image）
export async function createItem(payload) {
  const resp = await fetch(`${API_BASE}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || `创建条目失败（${resp.status}）`);
  return body;
}

// ---- 联合检索（Phase 3/4）----

export async function federatedSearch(query, topK = 5) {
  const resp = await fetch(`${API_BASE}/search/federated`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: topK }),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || `联合检索失败（${resp.status}）`);
  return body; // { query, results, local_results, errors }
}

export async function fetchConnectors() {
  const resp = await fetch(`${API_BASE}/connectors`);
  if (!resp.ok) throw new Error("获取数据源失败");
  return resp.json();
}

// Inspector 统计
export async function fetchStats() {
  const resp = await fetch(`${API_BASE}/stats`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "获取统计失败");
  return body;
}

// 年度活跃度（ADR 0033：书评+收藏加权，按天聚合，GitHub 热力图数据源）
export async function fetchActivity(year) {
  const resp = await fetch(`${API_BASE}/activity${year ? `?year=${year}` : ""}`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "获取年度统计失败");
  return body;
}

// ---- 数据备份/导出/导入（ADR 0038）----

export async function exportBackup() {
  const resp = await fetch(`${API_BASE}/backup/export`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "导出失败");
  return body;
}

export async function importBackup(data) {
  const resp = await fetch(`${API_BASE}/backup/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "导入失败");
  return body;
}

export async function fetchImportStatus(jobId) {
  const resp = await fetch(`${API_BASE}/backup/import/status/${jobId}`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "获取导入状态失败");
  return body;
}

export async function createDeclarativeConnector(config) {
  const resp = await fetch(`${API_BASE}/connectors`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "创建数据源失败");
  return body;
}

export async function deleteConnector(name) {
  const resp = await fetch(`${API_BASE}/connectors/${name}`, { method: "DELETE" });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "删除数据源失败");
  return body;
}

export async function saveConnectorProxy(name, proxyUrl) {
  const resp = await fetch(`${API_BASE}/connectors/${name}/proxy`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ proxy_url: proxyUrl }),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "设置代理失败");
  return body;
}

export async function testConnectorProxy(name, proxyUrl) {
  const resp = await fetch(`${API_BASE}/connectors/${name}/test-proxy`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ proxy_url: proxyUrl }),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "测试失败");
  return body;
}

// ---- 收藏入库（Save to Library，Phase 3）----

export async function saveExternal(item) {
  const resp = await fetch(`${API_BASE}/items/save-external`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(item),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "收藏入库失败");
  return body;
}

// ---- 角色图鉴（详情 / 角色墙）----

export async function fetchCharacters() {
  const resp = await fetch(`${API_BASE}/characters`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "获取角色墙失败");
  return body.characters;
}

// 声优关系聚合（ADR 0032：声优 → 角色 → 作品 三层关系，供声优图谱）
export async function fetchVoiceRelations() {
  const resp = await fetch(`${API_BASE}/voice-relations`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "获取声优关系失败");
  return body;
}

export async function fetchItemDetail(itemId) {
  const resp = await fetch(`${API_BASE}/items/${itemId}/detail`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "获取条目详情失败");
  return body;
}

// 同一作品跨来源的兄弟条目（Review Studio Overview 多来源切换，ADR 0026）
export async function fetchRelatedSources(itemId) {
  const resp = await fetch(`${API_BASE}/items/${itemId}/related`);
  const body = await resp.json().catch(() => []);
  if (!resp.ok) throw new Error(body.detail || "获取关联来源失败");
  return Array.isArray(body) ? body : [];
}

export async function fetchExternalDetail(source, externalId) {
  const resp = await fetch(`${API_BASE}/external/detail?source=${encodeURIComponent(source)}&external_id=${encodeURIComponent(externalId)}`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "获取外部详情失败");
  return body;
}

// ---- 外部资料刷新 / 批量补齐（ADR 0025）----

export async function refreshExternalItem(itemId) {
  const resp = await fetch(`${API_BASE}/items/${itemId}/refresh-external`, {
    method: "POST",
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "刷新外部资料失败");
  return body;
}

export async function backfillReference(limit = 5) {
  const resp = await fetch(`${API_BASE}/external/backfill-reference?limit=${limit}`, {
    method: "POST",
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "批量补齐失败");
  return body;
}

// ---- 第三方插件（ADR 0027：本地文件信任模型）----

export async function fetchPlugins() {
  const resp = await fetch(`${API_BASE}/plugins`);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "获取插件状态失败");
  return body;
}

export async function acknowledgePlugins() {
  const resp = await fetch(`${API_BASE}/plugins/acknowledge`, { method: "POST" });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || "确认插件风险提示失败");
  return body;
}

// ---- 流式问答：解析 SSE 事件 ----
export async function streamRag(query, { onSources, onChunk, onDone, onError }) {
  const resp = await fetch(`${API_BASE}/rag/query/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!resp.ok || !resp.body) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败（${resp.status}）`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (!raw.startsWith("data: ")) continue;
      let evt;
      try {
        evt = JSON.parse(raw.slice(6));
      } catch {
        continue;
      }
      if (evt.type === "sources") onSources?.(evt.sources);
      else if (evt.type === "chunk") onChunk?.(evt.content);
      else if (evt.type === "done") {
        onDone?.(evt.answer, evt.sources);
        return;
      } else if (evt.type === "error") {
        onError?.(evt.message);
        return;
      }
    }
  }
}
