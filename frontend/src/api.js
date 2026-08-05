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

// 上传条目封面图
export async function uploadItemCover(id, file) {
  const fd = new FormData();
  fd.append("file", file);
  const resp = await fetch(`${API_BASE}/items/${id}/cover`, { method: "POST", body: fd });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || `上传封面失败（${resp.status}）`);
  return body;
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
