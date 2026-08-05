// Tsumugi 桌面图书馆（三栏布局）
// 布局：图标导航栏(ask固定顶 + 可排序区 + settings固定底) + 侧栏(搜索/分组标签) + 中央工作区
// 设置页分类：外观 / 导航栏 / 数据源（分类筛选在最上方）
import React, { useEffect, useRef, useState } from "react";
import {
  fetchItems, fetchTags, streamRag, federatedSearch, deleteItem, saveExternal,
  filePathToUrl, createItem, uploadItem, uploadItemCover,
  fetchConnectors, createDeclarativeConnector, deleteConnector,
} from "../api.js";
import InspectorPanel from "./InspectorPanel.jsx";

// 可排序的功能按钮（settings 固定底部、ask 固定顶部，不可移）
const NAV = {
  ask: { key: "ask", label: "问答", icon: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /><path d="M9 10h6" />
    </svg>
  ) },
  library: { key: "library", label: "图书馆", icon: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 19V5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1-2-2zm0 0a2 2 0 0 0 2 2h13" /><path d="M9 7h6M9 11h6" />
    </svg>
  ) },
  inspector: { key: "inspector", label: "分析", icon: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3v18h18" /><path d="M7 14l4-4 3 3 5-6" />
    </svg>
  ) },
  settings: { key: "settings", label: "设置", icon: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  ) },
};

// 可自由排序的键（settings 除外）
const SORTABLE_KEYS = ["ask", "library", "inspector"];

const NAV_ORDER_KEY = "tsumugi-nav-order";

function loadNavOrder() {
  try {
    const saved = JSON.parse(localStorage.getItem(NAV_ORDER_KEY) || "null");
    if (Array.isArray(saved)) {
      // 只保留有效键，补上缺失的
      const valid = SORTABLE_KEYS.filter((k) => saved.includes(k));
      SORTABLE_KEYS.forEach((k) => { if (!valid.includes(k)) valid.push(k); });
      return valid;
    }
  } catch { /* ignore */ }
  return [...SORTABLE_KEYS];
}

export default function DesktopView({ items, total, allTags, refresh, bg, updateBg, theme, setTheme, textOverlays, updateTextOverlays }) {
  const [section, setSection] = useState("ask"); // 默认打开问答
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [activeTag, setActiveTag] = useState(null);
  const [activeGroup, setActiveGroup] = useState("all");
  const [navOrder, setNavOrder] = useState(() => loadNavOrder());

  // 文字涂鸦编辑模式（蒙版）
  const [overlayEditMode, setOverlayEditMode] = useState(false);
  // 长按导航调整模式
  const [navRearrangeMode, setNavRearrangeMode] = useState(false);
  // 设置保存提示
  const [savedToast, setSavedToast] = useState(false);

  // 侧栏可拖拽宽度（最大页面 1/3）
  const [sidebarWidth, setSidebarWidth] = useState(224);
  const dragRef = useRef(null);
  const sidebarRef = useRef(null);

  // 搜索历史（localStorage 持久化，搜索框侧边下拉展示）
  const [searchHistory, setSearchHistory] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("tsumugi-search-history") || "[]");
      return Array.isArray(saved) ? saved.slice(0, 10) : [];
    } catch { return []; }
  });
  const [historyOpen, setHistoryOpen] = useState(false);
  // 图书馆本地查找关键字（按标题/内容过滤当前网格）
  const [libQuery, setLibQuery] = useState("");
  // 标签区默认折叠，主动点击展开
  const [tagsOpen, setTagsOpen] = useState(false);
  // 自定义分组（localStorage 持久化）：{ id, name, tags: string[] }
  const [customGroups, setCustomGroups] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("tsumugi-custom-groups") || "[]");
      return Array.isArray(saved) ? saved : [];
    } catch { return []; }
  });
  // 新建分组浮层状态
  const [showGroupModal, setShowGroupModal] = useState(false);
  const [groupName, setGroupName] = useState("");
  const [groupTagSelection, setGroupTagSelection] = useState([]);
  // 当前激活的自定义分组
  const [customActive, setCustomActive] = useState(null);

  const saveCustomGroups = (groups) => {
    setCustomGroups(groups);
    try { localStorage.setItem("tsumugi-custom-groups", JSON.stringify(groups)); } catch { /* ignore */ }
  };

  const openGroupModal = () => {
    // 预选当前激活标签
    setGroupTagSelection(activeTag ? [activeTag] : []);
    setGroupName("");
    setShowGroupModal(true);
  };

  const toggleGroupTag = (name) => {
    setGroupTagSelection((prev) => prev.includes(name) ? prev.filter((x) => x !== name) : [...prev, name]);
  };

  const addCustomGroup = () => {
    const name = groupName.trim();
    if (!name) return;
    saveCustomGroups([...customGroups, { id: Date.now(), name, tags: [...groupTagSelection] }]);
    setGroupName("");
    setGroupTagSelection([]);
    setShowGroupModal(false);
  };

  const removeCustomGroup = (id) => saveCustomGroups(customGroups.filter((g) => g.id !== id));

  // 问答状态
  const [query, setQuery] = useState("");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState([]);
  const [fedResults, setFedResults] = useState([]);
  const [askError, setAskError] = useState("");
  const [answerOpen, setAnswerOpen] = useState(false);
  const askInputRef = useRef(null);

  // 导入状态
  const [file, setFile] = useState(null);
  const [importTags, setImportTags] = useState("");
  const [uploading, setUploading] = useState(false);
  const [importMsg, setImportMsg] = useState("");
  const [showImport, setShowImport] = useState(false);
  const [importTab, setImportTab] = useState("file"); // file | note
  const [noteTitle, setNoteTitle] = useState("");
  const [noteContent, setNoteContent] = useState("");
  const [noteTags, setNoteTags] = useState("");
  const [creatingNote, setCreatingNote] = useState(false);

  // 数据源管理（设置页）
  const [connectors, setConnectors] = useState([]);
  const [connMsg, setConnMsg] = useState("");
  const [showConnForm, setShowConnForm] = useState(false);
  const [connForm, setConnForm] = useState({
    name: "", display_name: "", base_url: "", search_endpoint: "",
    result_path: "", field_map_title: "", field_map_external_id: "",
    field_map_description: "",
  });

  // 设置页分类 tab
  const [settingsTab, setSettingsTab] = useState("appearance"); // appearance | nav | sources

  const sortedTags = [...allTags].sort((a, b) => b.count - a.count);

  // 资料库网格：走后端筛选
  const [gridItems, setGridItems] = useState([]);
  const [gridTotal, setGridTotal] = useState(0);
  const [gridLoading, setGridLoading] = useState(false);
  const [groupCounts, setGroupCounts] = useState({ all: total, note: 0, image: 0, external: 0 });

  useEffect(() => {
    Promise.all([
      fetchItems({ type: "note", limit: 1 }),
      fetchItems({ type: "image", limit: 1 }),
      fetchItems({ type: "external_ref", limit: 1 }),
    ])
      .then(([n, im, ex]) => setGroupCounts({ all: total, note: n.total, image: im.total, external: ex.total }))
      .catch(() => {});
  }, [items, total]);

  useEffect(() => {
    setGridLoading(true);
    const typeMap = { all: undefined, note: "note", image: "image", external: "external_ref" };
    // 自定义分组：用分组的标签筛选（tag_match=all）
    const groupTagFilter = activeGroup === "custom" && customActive ? customActive.tags : undefined;
    fetchItems({
      tag: activeTag ? [activeTag] : groupTagFilter?.length ? groupTagFilter : undefined,
      tagMatch: groupTagFilter?.length ? "all" : undefined,
      type: activeGroup === "custom" ? undefined : typeMap[activeGroup],
      skip: 0,
      limit: 200,
    })
      .then((d) => { setGridItems(d.items); setGridTotal(d.total); })
      .catch(() => {})
      .finally(() => setGridLoading(false));
  }, [activeTag, activeGroup, customActive, items]);

  // 导航排序持久化
  const saveNavOrder = (order) => {
    setNavOrder(order);
    try { localStorage.setItem(NAV_ORDER_KEY, JSON.stringify(order)); } catch { /* ignore */ }
  };

  const moveNav = (key, dir) => {
    const idx = navOrder.indexOf(key);
    const to = idx + dir;
    if (idx < 0 || to < 0 || to >= navOrder.length) return;
    const next = [...navOrder];
    [next[idx], next[to]] = [next[to], next[idx]];
    saveNavOrder(next);
  };

  // 文字涂鸦：增删改（位置/文字/大小/颜色）
  const addTextOverlay = () => {
    const id = Date.now();
    updateTextOverlays([
      ...textOverlays,
      { id, text: "新文字", x: 30, y: 30, size: 28, color: "var(--accent)" },
    ]);
  };

  const updateOverlay = (id, patch) => {
    updateTextOverlays(textOverlays.map((o) => (o.id === id ? { ...o, ...patch } : o)));
  };

  const removeOverlay = (id) => {
    updateTextOverlays(textOverlays.filter((o) => o.id !== id));
  };

  // 长按导航按钮进入调整模式
  const longPressTimer = useRef(null);
  const startLongPress = () => {
    longPressTimer.current = setTimeout(() => setNavRearrangeMode(true), 550);
  };
  const cancelLongPress = () => {
    if (longPressTimer.current) clearTimeout(longPressTimer.current);
  };

  function handleSection(s) {
    setSection(s);
    if (s === "ask") setTimeout(() => askInputRef.current?.focus?.(), 50);
  }

  async function handleAsk() {
    if (!query.trim() || asking) return;
    const q = query.trim();
    setAsking(true);
    setAnswer("");
    setSources([]);
    setFedResults([]);
    setAskError("");
    setAnswerOpen(true);
    // 记录搜索历史（去重，最新在前，最多 10 条）
    setSearchHistory((prev) => {
      const next = [q, ...prev.filter((x) => x !== q)].slice(0, 10);
      try { localStorage.setItem("tsumugi-search-history", JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
    setHistoryOpen(false);
    try {
      try {
        const fd = await federatedSearch(q);
        setFedResults(fd.results || []);
      } catch { /* 外部失败不阻塞本地 */ }
      await streamRag(q, {
        onSources: (s) => setSources(s),
        onChunk: (p) => setAnswer((prev) => prev + p),
        onDone: () => {},
        onError: (msg) => setAskError(msg),
      });
    } catch (err) {
      setAskError(err.message);
    } finally {
      setAsking(false);
    }
  }

  // 点击历史记录回填并搜索
  function handleHistoryClick(q) {
    setQuery(q);
    setHistoryOpen(false);
    handleAskFromValue(q);
  }

  async function handleAskFromValue(q) {
    if (!q.trim() || asking) return;
    setAsking(true);
    setAnswer("");
    setSources([]);
    setFedResults([]);
    setAskError("");
    setAnswerOpen(true);
    setSearchHistory((prev) => {
      const next = [q, ...prev.filter((x) => x !== q)].slice(0, 10);
      try { localStorage.setItem("tsumugi-search-history", JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
    try {
      try {
        const fd = await federatedSearch(q);
        setFedResults(fd.results || []);
      } catch { /* ignore */ }
      await streamRag(q, {
        onSources: (s) => setSources(s),
        onChunk: (p) => setAnswer((prev) => prev + p),
        onDone: () => {},
        onError: (msg) => setAskError(msg),
      });
    } catch (err) {
      setAskError(err.message);
    } finally {
      setAsking(false);
    }
  }

  function clearHistory() {
    setSearchHistory([]);
    try { localStorage.setItem("tsumugi-search-history", "[]"); } catch { /* ignore */ }
    setHistoryOpen(false);
  }

  async function handleSave(r) {
    try {
      await saveExternal({
        source: r.source, external_id: r.external_id, title: r.title,
        description: r.description, image_url: r.image_url, tags: r.tags,
      });
      refresh();
    } catch (err) {
      setAskError(err.message);
    }
  }

  async function handleImport(e) {
    e.preventDefault();
    if (!file) return setImportMsg("请先选择文件");
    setUploading(true);
    setImportMsg("");
    try {
      const result = await uploadItem(file, null, importTags);
      setImportMsg(result.duplicated ? "内容已存在，跳过导入" : `已导入「${result.title}」`);
      setFile(null);
      setImportTags("");
      refresh();
    } catch (err) {
      setImportMsg(err.message);
    } finally {
      setUploading(false);
    }
  }

  async function handleCreateNote(e) {
    e.preventDefault();
    if (!noteTitle.trim() || !noteContent.trim()) {
      return setImportMsg("笔记需要标题和内容");
    }
    setCreatingNote(true);
    setImportMsg("");
    try {
      const result = await createItem({
        title: noteTitle.trim(),
        type: "note",
        content: noteContent,
        tag_names: noteTags ? noteTags.split(",").map((s) => s.trim()).filter(Boolean) : undefined,
      });
      setImportMsg(result.duplicated ? "内容已存在，跳过导入" : `已创建笔记「${result.title}」`);
      setNoteTitle("");
      setNoteContent("");
      setNoteTags("");
      refresh();
    } catch (err) {
      setImportMsg(err.message);
    } finally {
      setCreatingNote(false);
    }
  }

  function cardCover(it) {
    if (it.image_url) return it.image_url;
    if (it.file_path) return filePathToUrl(it.file_path);
    return null;
  }

  // 更换条目封面
  const coverFileRef = useRef(null);
  const coverTargetRef = useRef(null);

  function handleCoverFile(e) {
    const file = e.target.files?.[0];
    const id = coverTargetRef.current;
    if (!file || !id) return;
    uploadItemCover(id, file)
      .then(() => refresh())
      .catch((err) => setConnMsg(err.message));
    e.target.value = "";
  }

  const loadConnectors = () => fetchConnectors().then(setConnectors).catch(() => {});
  useEffect(() => { loadConnectors(); }, []);

  // Esc 关闭导入浮层
  useEffect(() => {
    if (!showImport) return;
    const onKey = (e) => { if (e.key === "Escape") setShowImport(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showImport]);

  // 侧栏拖拽调宽（最大页面 1/3）
  useEffect(() => {
    const el = sidebarRef.current;
    if (!el) return;
    const startDrag = (e) => {
      e.preventDefault();
      const startX = e.clientX;
      const startW = el.offsetWidth;
      const maxW = Math.floor(window.innerWidth / 3);
      const onMove = (ev) => {
        const w = Math.min(Math.max(startW + (ev.clientX - startX), 160), maxW);
        setSidebarWidth(w);
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    };
    const handle = dragRef.current;
    handle.addEventListener("mousedown", startDrag);
    return () => handle.removeEventListener("mousedown", startDrag);
  }, []);

  async function handleCreateConnector(e) {
    e.preventDefault();
    try {
      await createDeclarativeConnector({
        name: connForm.name.trim(),
        display_name: connForm.display_name.trim() || undefined,
        base_url: connForm.base_url.trim(),
        search_endpoint: connForm.search_endpoint.trim(),
        result_path: connForm.result_path.trim() || undefined,
        field_map: {
          title: connForm.field_map_title.trim(),
          external_id: connForm.field_map_external_id.trim(),
          description: connForm.field_map_description.trim() || undefined,
        },
      });
      setConnMsg(`已创建数据源「${connForm.name.trim()}」`);
      setShowConnForm(false);
      setConnForm({ name: "", display_name: "", base_url: "", search_endpoint: "",
        result_path: "", field_map_title: "", field_map_external_id: "", field_map_description: "" });
      loadConnectors();
    } catch (err) {
      setConnMsg(err.message);
    }
  }

  async function handleDeleteConnector(name) {
    try {
      await deleteConnector(name);
      setConnMsg(`已删除数据源「${name}」`);
      loadConnectors();
    } catch (err) {
      setConnMsg(err.message);
    }
  }

  // 背景设置
  const bgFileRef = useRef(null);
  function handleSaveSettings() {
    // 所有设置均实时持久化到 localStorage，此按钮仅作确认反馈
    setSavedToast(true);
    setTimeout(() => setSavedToast(false), 1500);
  }
  function handleBgFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result;
      if (dataUrl.length > 4 * 1024 * 1024) {
        setConnMsg("图片过大（>4MB），请换一张较小的图片。");
        return;
      }
      updateBg({ image: dataUrl });
      setConnMsg("背景图已设置");
    };
    reader.readAsDataURL(file);
    e.target.value = "";
  }

  function coverLabel(it) {
    if (it.type === "image") return "絵";
    if (it.type === "external_ref") return it.source.slice(0, 2).toUpperCase();
    return it.title.slice(0, 1);
  }

  const groupItems = [["all", "全部", groupCounts.all], ["note", "笔记", groupCounts.note],
    ["image", "图片", groupCounts.image],
    ["external", "外部收藏", groupCounts.external]];

  const sortedNavKeys = navOrder.filter((k) => k !== "ask");
  const settingsTabList = [
    { key: "appearance", label: "外观" },
    { key: "nav", label: "导航栏" },
    { key: "sources", label: "数据源" },
  ];
  // 是否已有问答内容（决定搜索框居中/置顶）
  const hasContent = !!(answer || sources.length > 0 || fedResults.length > 0);
  // 图书馆网格：按 libQuery 本地过滤（标题/内容）
  const libFiltered = gridItems.filter((it) => {
    if (!libQuery.trim()) return true;
    const q = libQuery.trim().toLowerCase();
    return (it.title || "").toLowerCase().includes(q) || (it.content || "").toLowerCase().includes(q);
  });

  return (
    <div className="desktop-view flex relative"
      style={{ minHeight: "calc(100vh - 60px)" }}>
      <div className="desk-ambient pointer-events-none" aria-hidden="true" />

      {/* 文字涂鸦层（可拖动，编辑模式显示蒙版）——z 高于蒙版才能拖动 */}
      {textOverlays.map((o) => (
        <div key={o.id}
          className="text-overlay absolute cursor-move select-none"
          style={{ left: o.x, top: o.y, fontSize: o.size, color: o.color, opacity: overlayEditMode ? 0.95 : 0.5, zIndex: overlayEditMode ? 45 : 5 }}
          onMouseDown={(e) => {
            if (!overlayEditMode) return;
            e.preventDefault();
            e.stopPropagation();
            const startX = e.clientX, startY = e.clientY;
            const baseX = o.x, baseY = o.y;
            const onMove = (ev) => updateOverlay(o.id, { x: baseX + (ev.clientX - startX), y: baseY + (ev.clientY - startY) });
            const onUp = () => { document.removeEventListener("mousemove", onMove); document.removeEventListener("mouseup", onUp); };
            document.addEventListener("mousemove", onMove);
            document.addEventListener("mouseup", onUp);
          }}>
          {o.text}
          {overlayEditMode && (
            <span className="absolute -top-6 -right-2 text-[10px] px-1.5 py-0.5 rounded-full"
              style={{ backgroundColor: "var(--danger)", color: "#fff", cursor: "pointer" }}
              onClick={(e) => { e.stopPropagation(); removeOverlay(o.id); }}>
              ✕
            </span>
          )}
        </div>
      ))}

      {/* 文字涂鸦编辑蒙版（蒙版在文字下方，文字可拖动） */}
      {overlayEditMode && (
        <div className="fixed inset-0 z-40" style={{ backgroundColor: "rgba(8,10,18,0.55)" }}
          onClick={() => setOverlayEditMode(false)}>
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center gap-3 text-center"
            onClick={(e) => e.stopPropagation()}>
            <div className="px-4 py-2 rounded-2xl text-sm"
              style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", color: "var(--text)" }}>
              拖动文字调整位置；点击 ✕ 删除
            </div>
            <div className="flex gap-2">
              <button onClick={addTextOverlay}
                className="px-3 py-1.5 rounded-xl text-xs font-medium"
                style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
                + 添加文字
              </button>
              <button onClick={() => setOverlayEditMode(false)}
                className="px-3 py-1.5 rounded-xl text-xs"
                style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
                完成
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 长按调整导航模式的提示条 */}
      {navRearrangeMode && (
        <div className="fixed top-20 left-1/2 -translate-x-1/2 z-40 flex items-center gap-2 px-4 py-2 rounded-2xl text-sm"
          style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", color: "var(--text)", boxShadow: "0 8px 30px rgba(0,0,0,0.2)" }}>
          拖动功能键调整顺序
          <button onClick={() => setNavRearrangeMode(false)}
            className="px-2 py-0.5 rounded-lg text-xs"
            style={{ backgroundColor: "var(--accent)", color: "#fff" }}>完成</button>
        </div>
      )}

      {/* 1. 图标导航栏：ask固定顶 + 可排序区 + settings固定底 */}
      <nav className="desk-nav flex flex-col items-center py-4 gap-1.5 z-10"
        style={{ width: 52, backgroundColor: "var(--rail-bg)", borderRight: "1px solid var(--panel-border)" }}>
        <div className="mb-3 text-base font-semibold" style={{ color: "var(--accent)" }}>紬</div>
        {/* ask 固定一号位 */}
        <button onClick={() => handleSection("ask")} title="问答"
          className="p-2 rounded-xl transition-colors"
          style={{ color: section === "ask" ? "var(--accent)" : "var(--text-secondary)",
            backgroundColor: section === "ask" ? "var(--accent-soft)" : "transparent" }}>
          {NAV.ask.icon}
        </button>
        {/* 可排序区（不含 ask，长按进入调整模式，调整模式下可拖动） */}
        <div className="flex-1 flex flex-col items-center gap-1.5 overflow-y-auto py-2">
          {sortedNavKeys.map((k) => (
            <button key={k}
              onClick={() => { if (!navRearrangeMode) handleSection(k); }}
              onMouseDown={() => { if (k !== "settings") startLongPress(); }}
              onMouseUp={cancelLongPress}
              onMouseLeave={cancelLongPress}
              onDragStart={(e) => { if (navRearrangeMode) { e.dataTransfer.setData("text/navkey", k); e.dataTransfer.effectAllowed = "move"; } }}
              onDragOver={(e) => { if (navRearrangeMode) e.preventDefault(); }}
              onDrop={(e) => {
                if (!navRearrangeMode) return;
                e.preventDefault();
                const from = e.dataTransfer.getData("text/navkey");
                if (!from || from === k) return;
                const next = [...navOrder];
                const fi = next.indexOf(from), ti = next.indexOf(k);
                next.splice(fi, 1);
                next.splice(ti, 0, from);
                saveNavOrder(next);
              }}
              title={navRearrangeMode ? "拖动调整位置" : NAV[k].label}
              className="p-2 rounded-xl transition-colors shrink-0"
              style={{ color: section === k ? "var(--accent)" : "var(--text-secondary)",
                backgroundColor: section === k ? "var(--accent-soft)" : "transparent",
                cursor: navRearrangeMode ? "grab" : "pointer",
                outline: navRearrangeMode ? "1px dashed var(--accent)" : "none" }}>
              {NAV[k].icon}
            </button>
          ))}
        </div>
        {/* settings 固定底部 */}
        <button onClick={() => handleSection("settings")} title="设置"
          className="p-2 rounded-xl transition-colors mt-auto"
          style={{ color: section === "settings" ? "var(--accent)" : "var(--text-secondary)",
            backgroundColor: section === "settings" ? "var(--accent-soft)" : "transparent" }}>
          {NAV.settings.icon}
        </button>
      </nav>

      {/* 2. 半透明侧栏（可拖拽调宽） */}
      <aside ref={sidebarRef} className="flex flex-col z-10"
        style={{
          width: sidebarOpen ? sidebarWidth : 36,
          backgroundColor: "var(--rail-bg)",
          borderRight: "1px solid var(--panel-border)",
          backdropFilter: "blur(14px)",
          WebkitBackdropFilter: "blur(14px)",
          transition: "width 0.05s ease",
          position: "relative",
        }}>
        {/* 拖拽手柄 */}
        <div ref={dragRef}
          className="absolute right-0 top-0 bottom-0 z-20"
          style={{ width: 5, cursor: "col-resize", opacity: sidebarOpen ? 1 : 0 }} />
        <button onClick={() => setSidebarOpen((v) => !v)}
          className="self-end mr-1.5 mt-2 text-xs px-1 rounded"
          style={{ color: "var(--text-secondary)" }}>
          {sidebarOpen ? "«" : "»"}
        </button>
        {sidebarOpen && (
          <div className="flex-1 flex flex-col min-h-0">
            {/* 图书馆侧栏内容（分组 + 标签）或 问答提示 */}
            <div className="flex-1 overflow-y-auto px-2.5 pb-2 pt-3">
              {section === "library" && (
                <>
                  {/* 系统分组 */}
                  <div className="text-[11px] mb-1.5 tracking-wider px-1" style={{ color: "var(--text-secondary)" }}>资料库</div>
                  {groupItems.map(([k, label, c]) => (
                    <button key={k} onClick={() => { setActiveGroup(k); setCustomActive(null); }}
                      className="w-full flex justify-between items-center text-left px-2 py-1.5 mb-0.5 rounded-lg text-[13px]"
                      style={{ color: activeGroup === k ? "var(--accent)" : "var(--text)",
                        backgroundColor: activeGroup === k ? "var(--accent-soft)" : "transparent" }}>
                      <span>{label}</span>
                      <span className="text-[11px]" style={{ color: "var(--text-secondary)" }}>{c}</span>
                    </button>
                  ))}

                  {/* 自定义分组：hover 显示删除，柔和展示 */}
                  {customGroups.length > 0 && (
                    <>
                      <div className="flex items-center justify-between mt-4 mb-1.5 px-1">
                        <span className="text-[11px] tracking-wider" style={{ color: "var(--text-secondary)" }}>我的分组</span>
                        <button onClick={openGroupModal} title="新建分组"
                          className="text-[10px] px-1.5 py-0.5 rounded hover:opacity-80"
                          style={{ color: "var(--text-secondary)", backgroundColor: "rgba(255,255,255,0.06)" }}>
                          + 新建
                        </button>
                      </div>
                      {customGroups.map((g) => (
                        <div key={g.id} className="group-item group flex items-center mb-0.5">
                          <button
                            onClick={() => { setActiveGroup("custom"); setActiveTag(null); setCustomActive(g); }}
                            className="flex-1 flex justify-between items-center text-left px-2 py-1.5 rounded-lg text-[13px]"
                            style={{ color: customActive?.id === g.id ? "var(--accent)" : "var(--text)",
                              backgroundColor: customActive?.id === g.id ? "var(--accent-soft)" : "transparent" }}>
                            <span className="truncate">{g.name}</span>
                            <span className="text-[11px]" style={{ color: "var(--text-secondary)" }}>{g.tags.length}</span>
                          </button>
                          <button onClick={() => removeCustomGroup(g.id)} title="删除分组"
                            className="text-[11px] px-1.5 opacity-0 group-hover:opacity-100 transition-opacity"
                            style={{ color: "var(--danger)" }}>✕</button>
                        </div>
                      ))}
                    </>
                  )}
                  {customGroups.length === 0 && (
                    <button onClick={openGroupModal}
                      className="w-full flex items-center gap-1.5 px-2 py-1.5 mt-3 rounded-lg text-[12px] opacity-70 hover:opacity-100"
                      style={{ color: "var(--text-secondary)" }}>
                      <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.8">
                        <path d="M12 5v14M5 12h14" />
                      </svg>
                      新建分组
                    </button>
                  )}
                  {/* 标签：常态折叠，点击展开 */}
                  <button onClick={() => setTagsOpen((v) => !v)}
                    className="w-full flex items-center justify-between mt-4 mb-1.5 text-left">
                    <span className="text-[11px] tracking-wider" style={{ color: "var(--text-secondary)" }}>标签</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full"
                      style={{ color: "var(--text-secondary)", backgroundColor: "rgba(255,255,255,0.06)" }}>
                      {tagsOpen ? "收起 ▲" : `${sortedTags.length} 个 ▸`}
                    </span>
                  </button>
                  {tagsOpen && (
                    <>
                      {sortedTags.length === 0 && (
                        <div className="text-xs px-2 py-1" style={{ color: "var(--text-secondary)" }}>暂无标签</div>
                      )}
                      {sortedTags.map((t) => (
                        <button key={t.id} onClick={() => setActiveTag(activeTag === t.name ? null : t.name)}
                          className="w-full flex justify-between items-center text-left px-2 py-1.5 mb-0.5 rounded-lg text-[13px]"
                          style={{ color: activeTag === t.name ? "var(--tag-text)" : "var(--text)",
                            backgroundColor: activeTag === t.name ? "var(--tag-bg)" : "transparent" }}>
                          <span className="truncate"># {t.name}</span>
                          <span className="text-[11px]" style={{ color: "var(--text-secondary)" }}>{t.count}</span>
                        </button>
                      ))}
                    </>
                  )}
                </>
              )}
              {/* 搜索历史：仅问答区块显示（分析/设置不显示） */}
              {section === "ask" && (
                <div className="flex flex-col">
                  <div className="text-[11px] mb-1.5 tracking-wider flex items-center justify-between"
                    style={{ color: "var(--text-secondary)" }}>
                    <span>搜索历史</span>
                    {searchHistory.length > 0 && (
                      <button onClick={clearHistory} className="text-[10px] hover:opacity-70">清空</button>
                    )}
                  </div>
                  {searchHistory.length === 0 ? (
                    <div className="text-xs px-1" style={{ color: "var(--text-secondary)" }}>暂无搜索记录</div>
                  ) : (
                    <ul className="space-y-0.5">
                      {searchHistory.slice(0, 8).map((h, i) => (
                        <li key={i}>
                          <button onClick={() => handleHistoryClick(h)}
                            className="w-full flex items-center gap-1.5 text-left px-2 py-1 rounded-lg text-[12px] truncate"
                            style={{ color: "var(--text)", backgroundColor: "rgba(255,255,255,0.04)" }}>
                            <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="1.8"
                              className="shrink-0" style={{ color: "var(--text-secondary)" }}>
                              <path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" />
                            </svg>
                            <span className="truncate">{h}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>

            {/* 导入：图标 -> 点击展开浮层 */}
            <div className="px-2.5 pb-3 pt-1 border-t flex items-center gap-1.5"
              style={{ borderColor: "var(--panel-border)" }}>
              <button onClick={() => setShowImport(true)} title="导入"
                className="p-2 rounded-xl transition-colors"
                style={{ color: "var(--text-secondary)", backgroundColor: "rgba(255,255,255,0.04)" }}>
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.6">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5 5 5-5" /><path d="M12 15V3" />
                </svg>
              </button>
              {sidebarOpen && (
                <span className="text-xs" style={{ color: "var(--text-secondary)" }}>导入</span>
              )}
            </div>
          </div>
        )}
      </aside>

      {/* 3. 中央工作区 */}
      <div className="flex-1 relative overflow-y-auto p-6 z-10">

        {section === "library" && (
          <>
            <div className="flex items-center justify-between gap-3 mb-5">
              <div className="flex items-center gap-2">
                <span className="text-[15px] font-medium tracking-wide" style={{ color: "var(--text)" }}>
                  {activeTag ? `# ${activeTag}` : "全部资料"}
                </span>
                <span className="text-[11px] px-2 py-0.5 rounded-full"
                  style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>{gridTotal}</span>
              </div>
              {/* 图书馆本地查找（按标题/内容过滤当前网格） */}
              <div className="flex items-center gap-2 rounded-full px-3.5 py-2 w-64"
                style={{ backgroundColor: "var(--input-bg)", border: "1px solid var(--input-border)" }}>
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2"
                  className="shrink-0" style={{ color: "var(--text-secondary)" }}>
                  <circle cx="11" cy="11" r="7" /><path d="M21 21l-4.35-4.35" />
                </svg>
                <input value={libQuery}
                  onChange={(e) => setLibQuery(e.target.value)}
                  placeholder="查找存储的内容…"
                  className="flex-1 bg-transparent outline-none text-sm min-w-0"
                  style={{ color: "var(--text)" }} />
              </div>
            </div>

            {gridLoading ? (
              <div className="flex items-center justify-center h-64 text-sm"
                style={{ color: "var(--text-secondary)" }}>加载中…</div>
            ) : libFiltered.length === 0 ? (
              <div className="flex items-center justify-center h-64 text-sm"
                style={{ color: "var(--text-secondary)" }}>
                {gridItems.length === 0 ? "暂无资料，在左侧「导入」添加吧。" : "没有匹配的存储内容。"}
              </div>
            ) : (
              <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))" }}>
                {libFiltered.map((it) => (
                  <div key={it.id} className="desk-card group"
                    style={{ borderRadius: 20, overflow: "hidden", border: "1px solid var(--panel-border)",
                      backgroundColor: "var(--card-bg)", transition: "transform 0.2s ease, border-color 0.2s ease" }}>
                    <div className="relative" style={{ aspectRatio: "3/4", background: "var(--card-thumb)" }}>
                      {cardCover(it) ? (
                        <img src={cardCover(it)} alt={it.title} loading="lazy"
                          className="w-full h-full object-cover"
                          onError={(e) => { e.target.style.display = "none"; }} />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-2xl"
                          style={{ color: "var(--accent)" }}>{coverLabel(it)}</div>
                      )}
                      {it.source !== "local" && (
                        <span className="absolute top-1.5 left-1.5 text-[10px] px-1.5 py-0.5 rounded-full"
                          style={{ backgroundColor: "var(--accent)", color: "#fff" }}>{it.source}</span>
                      )}
                      {/* 更换封面（hover 显示） */}
                      <button
                        onClick={() => { coverTargetRef.current = it.id; coverFileRef.current?.click(); }}
                        className="absolute top-1.5 right-1.5 text-[10px] px-1.5 py-0.5 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                        style={{ backgroundColor: "rgba(8,10,18,0.65)", color: "#fff" }}>
                        换封面
                      </button>
                    </div>
                    <div className="p-2">
                      <div className="text-[13px] font-medium leading-snug line-clamp-2"
                        style={{ color: "var(--card-text)", minHeight: 34 }}>{it.title}</div>
                      <div className="flex items-center justify-between mt-0.5">
                        <span className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                          {it.type === "external_ref" ? it.source : it.type === "image" ? "图片" : `${it.chunks_count} 块`}
                        </span>
                        <button onClick={async () => { await deleteItem(it.id); refresh(); }}
                          className="text-[11px] opacity-0 group-hover:opacity-100 transition-opacity"
                          style={{ color: "var(--danger)" }}>删除</button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {section === "ask" && (
          <div className="max-w-3xl mx-auto flex flex-col h-full">
            {/* 搜索栏（仅问答区块显示；无内容居中，有内容置顶） */}
            <div className="flex justify-center transition-all duration-500 ease-in-out"
              style={{
                alignItems: hasContent ? "flex-start" : "center",
                paddingTop: hasContent ? "1rem" : "16vh",
                paddingBottom: hasContent ? "1rem" : "0",
              }}>
              <div className="relative w-full max-w-2xl">
                <div
                  className="w-full desk-searchbar flex items-center gap-3 rounded-full px-5 py-3"
                  style={{
                    backgroundColor: "var(--input-bg)",
                    border: "1px solid var(--input-border)",
                    backdropFilter: "blur(12px)",
                    WebkitBackdropFilter: "blur(12px)",
                    transition: "border-color 0.2s ease, box-shadow 0.2s ease",
                    boxShadow: "0 2px 16px rgba(0,0,0,0.08)",
                  }}>
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2"
                    className="shrink-0" style={{ color: "var(--text-secondary)" }}>
                    <circle cx="11" cy="11" r="7" /><path d="M21 21l-4.35-4.35" />
                  </svg>
                  <input ref={askInputRef} value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onFocus={(e) => { e.currentTarget.parentElement.style.borderColor = "var(--accent)"; e.currentTarget.parentElement.style.boxShadow = "0 0 0 3px var(--accent-soft)"; }}
                    onBlur={(e) => { e.currentTarget.parentElement.style.borderColor = "var(--input-border)"; e.currentTarget.parentElement.style.boxShadow = "0 2px 16px rgba(0,0,0,0.08)"; }}
                    onKeyDown={(e) => { if (e.key === "Enter") handleAsk(); }}
                    placeholder="搜索知识库并提问…（Enter）"
                    className="flex-1 bg-transparent outline-none text-base min-w-0"
                    style={{ color: "var(--text)" }} />
                  {/* 历史记录按钮 */}
                  <button onClick={() => setHistoryOpen((v) => !v)} title="搜索历史"
                    className="shrink-0 p-1.5 rounded-full transition-colors"
                    style={{ color: "var(--text-secondary)", backgroundColor: historyOpen ? "var(--accent-soft)" : "transparent" }}>
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8">
                      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /><path d="M12 7v5l3 2" />
                    </svg>
                  </button>
                  <button onClick={handleAsk} disabled={asking || !query.trim()}
                    className="text-sm px-4 py-1.5 rounded-full shrink-0 disabled:opacity-40 font-medium"
                    style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
                    {asking ? "…" : "提问"}
                  </button>
                </div>

                {/* 历史记录下拉 */}
                {historyOpen && (
                  <div className="history-dropdown absolute right-0 top-full mt-2 w-full max-w-sm rounded-2xl p-3 z-30"
                    style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", backdropFilter: "blur(20px)" }}>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-medium" style={{ color: "var(--text)" }}>搜索历史</span>
                      {searchHistory.length > 0 && (
                        <button onClick={clearHistory} className="text-[11px]"
                          style={{ color: "var(--text-secondary)" }}>清空</button>
                      )}
                    </div>
                    {searchHistory.length === 0 ? (
                      <div className="text-xs py-2" style={{ color: "var(--text-secondary)" }}>暂无搜索记录</div>
                    ) : (
                      <ul className="space-y-0.5">
                        {searchHistory.map((h, i) => (
                          <li key={i}>
                            <button onClick={() => handleHistoryClick(h)}
                              className="w-full flex items-center gap-2 text-left px-2 py-1.5 rounded-lg text-sm hover:opacity-80"
                              style={{ color: "var(--text)", backgroundColor: "rgba(255,255,255,0.04)" }}>
                              <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.8"
                                className="shrink-0" style={{ color: "var(--text-secondary)" }}>
                                <path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" />
                              </svg>
                              <span className="truncate">{h}</span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            </div>

            {askError && (
              <div className="text-sm mb-3 px-4 py-3 rounded-2xl"
                style={{ backgroundColor: "rgba(248,113,113,0.14)", color: "var(--danger)" }}>{askError}</div>
            )}
            {answerOpen && (answer || sources.length > 0 || fedResults.length > 0) ? (
              <div className="flex-1 overflow-y-auto space-y-3">
                {fedResults.length > 0 && (
                  <div className="desk-answer-card rounded-2xl p-4"
                    style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", backdropFilter: "blur(14px)" }}>
                    <div className="text-[11px] mb-2 tracking-wider" style={{ color: "var(--accent)" }}>外部检索</div>
                    {fedResults.slice(0, 4).map((r, i) => (
                      <div key={i} className="flex items-center justify-between py-1.5 text-sm">
                        <div className="flex items-center min-w-0">
                          <span className="mr-2 truncate" style={{ color: "var(--text)" }}>{r.title}</span>
                          <span className="text-[11px] px-1.5 py-0.5 rounded-full shrink-0"
                            style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>{r.source}</span>
                        </div>
                        <button onClick={() => handleSave(r)} className="text-xs shrink-0 ml-2"
                          style={{ color: "var(--accent)" }}>收藏</button>
                      </div>
                    ))}
                  </div>
                )}
                {sources.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {sources.map((s, i) => (
                      <span key={i} className="text-[11px] px-2.5 py-1 rounded-full"
                        style={{ backgroundColor: "var(--tag-bg)", color: "var(--tag-text)" }}>
                        {s.item_title} · {s.score.toFixed(2)}
                      </span>
                    ))}
                  </div>
                )}
                {answer && (
                  <div className="desk-answer-card rounded-2xl p-4"
                    style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", backdropFilter: "blur(14px)" }}>
                    <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed"
                      style={{ color: "var(--text)" }}>{answer}</pre>
                  </div>
                )}
              </div>
            ) : null}
          </div>
        )}

        {section === "inspector" && (
          <div className="max-w-3xl mx-auto mt-6">
            <InspectorPanel />
          </div>
        )}

        {section === "settings" && (
          <div className="max-w-2xl mx-auto mt-6">
            {/* 分类 tab 在最上方 */}
            <div className="flex gap-1 mb-4 p-1 rounded-2xl"
              style={{ backgroundColor: "rgba(255,255,255,0.06)", border: "1px solid var(--panel-border)" }}>
              {settingsTabList.map((t) => (
                <button key={t.key} onClick={() => setSettingsTab(t.key)}
                  className="flex-1 px-3 py-1.5 rounded-xl text-sm"
                  style={{ color: settingsTab === t.key ? "#fff" : "var(--text-secondary)",
                    backgroundColor: settingsTab === t.key ? "var(--accent)" : "transparent" }}>
                  {t.label}
                </button>
              ))}
            </div>

            {/* 外观：主题 + 背景 */}
            {settingsTab === "appearance" && (
              <div className="space-y-4">
                <div className="desk-askbar rounded-2xl p-5"
                  style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", backdropFilter: "blur(16px)" }}>
                  <h3 className="text-sm font-medium mb-3">主题</h3>
                  <div className="flex flex-wrap gap-2">
                    {["spring", "summer", "violet-obsidian", "default"].map((k) => (
                      <button key={k} onClick={() => setTheme(k)}
                        className="px-3 py-1.5 rounded-xl text-sm"
                        style={{ backgroundColor: theme === k ? "var(--accent)" : "var(--accent-soft)",
                          color: theme === k ? "#fff" : "var(--accent)" }}>
                        {k === "spring" ? "春樱" : k === "summer" ? "夏空" : k === "violet-obsidian" ? "夜紫" : "默认"}
                      </button>
                    ))}
                  </div>
                  <p className="text-xs mt-2" style={{ color: "var(--text-secondary)" }}>
                    当前主题随选择即时切换，保存于本地浏览器。
                  </p>
                </div>

                <div className="desk-askbar rounded-2xl p-5"
                  style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", backdropFilter: "blur(16px)" }}>
                  <h3 className="text-sm font-medium mb-3">背景</h3>
                  <div className="flex flex-col gap-3 text-sm">
                    <div className="flex items-center gap-3">
                      <button onClick={() => bgFileRef.current?.click()}
                        className="px-3 py-1.5 rounded-xl text-sm font-medium"
                        style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
                        {bg?.image ? "更换背景图" : "选择背景图"}
                      </button>
                      <input ref={bgFileRef} type="file" accept="image/*"
                        onChange={handleBgFile} className="hidden" />
                      {bg?.image && (
                        <button onClick={() => { updateBg({ image: null }); setConnMsg("背景图已清除"); }}
                          className="px-3 py-1.5 rounded-xl text-sm"
                          style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>清除背景</button>
                      )}
                    </div>
                    <label className="flex items-center gap-2">
                      <span className="text-xs w-16" style={{ color: "var(--text-secondary)" }}>透明度</span>
                      <input type="range" min="0.05" max="0.95" step="0.05"
                        value={bg?.opacity ?? 0.5}
                        onChange={(e) => updateBg({ opacity: Number(e.target.value) })} className="flex-1" />
                      <span className="text-xs w-8 text-right" style={{ color: "var(--text-secondary)" }}>
                        {Math.round((bg?.opacity ?? 0.5) * 100)}%</span>
                    </label>
                    <label className="flex items-center gap-2">
                      <span className="text-xs w-16" style={{ color: "var(--text-secondary)" }}>模糊</span>
                      <input type="range" min="0" max="40" step="1"
                        value={bg?.blur ?? 20}
                        onChange={(e) => updateBg({ blur: Number(e.target.value) })} className="flex-1" />
                      <span className="text-xs w-8 text-right" style={{ color: "var(--text-secondary)" }}>
                        {bg?.blur ?? 20}px</span>
                    </label>
                  </div>
                </div>

                {/* 文字涂鸦（自定义位置） */}
                <div className="desk-askbar rounded-2xl p-5"
                  style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", backdropFilter: "blur(16px)" }}>
                  <h3 className="text-sm font-medium mb-3">文字涂鸦</h3>
                  <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
                    在界面上添加自定义文字（如标题、标语），可自由拖动位置、调整大小与颜色。
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <button onClick={() => { setOverlayEditMode(true); setSettingsTab("appearance"); }}
                      className="px-3 py-1.5 rounded-xl text-sm font-medium"
                      style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
                      {overlayEditMode ? "编辑中…" : "编辑文字涂鸦"}
                    </button>
                    {textOverlays.length > 0 && (
                      <button onClick={() => updateTextOverlays([])}
                        className="px-3 py-1.5 rounded-xl text-sm"
                        style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
                        全部清除（{textOverlays.length}）
                      </button>
                    )}
                  </div>
                  {overlayEditMode && (
                    <p className="text-xs mt-2" style={{ color: "var(--accent)" }}>
                      蒙版已开启：拖动文字调整位置，点 ✕ 删除；点「完成」退出。
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* 导航栏：排序（除 settings 外的按键） */}
            {settingsTab === "nav" && (
              <div className="desk-askbar rounded-2xl p-5"
                style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", backdropFilter: "blur(16px)" }}>
                <h3 className="text-sm font-medium mb-1">导航栏排列</h3>
                <p className="text-xs mb-4" style={{ color: "var(--text-secondary)" }}>
                  调整左侧功能按钮顺序（问答固定首位、设置固定底部）。保存于本地浏览器。
                </p>
                <ul className="space-y-2">
                  {navOrder.map((k) => (
                    <li key={k} className="flex items-center gap-3 rounded-xl px-3 py-2 text-sm"
                      style={{ backgroundColor: "rgba(255,255,255,0.05)" }}>
                      <span className="flex-1 flex items-center gap-2">
                        <span style={{ color: "var(--accent)" }}>{NAV[k].icon}</span>
                        <span style={{ color: "var(--text)" }}>{NAV[k].label}</span>
                        {k === "ask" && <span className="text-[10px] px-1.5 py-0.5 rounded-full"
                          style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>固定</span>}
                      </span>
                      <span className="flex gap-1">
                        <button onClick={() => moveNav(k, -1)} disabled={k === "ask" || k === navOrder[0]}
                          className="px-2 py-0.5 rounded-lg text-xs disabled:opacity-30"
                          style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>↑</button>
                        <button onClick={() => moveNav(k, 1)} disabled={k === "ask" || k === navOrder[navOrder.length - 1]}
                          className="px-2 py-0.5 rounded-lg text-xs disabled:opacity-30"
                          style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>↓</button>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* 数据源 */}
            {settingsTab === "sources" && (
              <div className="desk-askbar rounded-2xl p-5"
                style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", backdropFilter: "blur(16px)" }}>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-medium">数据源管理</h3>
                  <button onClick={() => setShowConnForm((v) => !v)}
                    className="px-3 py-1 rounded-xl text-xs font-medium"
                    style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
                    {showConnForm ? "收起" : "+ 新建数据源"}
                  </button>
                </div>
                {showConnForm && (
                  <form onSubmit={handleCreateConnector} className="mb-4 grid grid-cols-2 gap-2 text-sm">
                    <input placeholder="名称（唯一）*" value={connForm.name}
                      onChange={(e) => setConnForm({ ...connForm, name: e.target.value })}
                      className="tsm-input border rounded px-2 py-1.5" />
                    <input placeholder="显示名" value={connForm.display_name}
                      onChange={(e) => setConnForm({ ...connForm, display_name: e.target.value })}
                      className="tsm-input border rounded px-2 py-1.5" />
                    <input placeholder="Base URL *" value={connForm.base_url}
                      onChange={(e) => setConnForm({ ...connForm, base_url: e.target.value })}
                      className="tsm-input border rounded px-2 py-1.5" />
                    <input placeholder="搜索端点，如 /search?q={query} *" value={connForm.search_endpoint}
                      onChange={(e) => setConnForm({ ...connForm, search_endpoint: e.target.value })}
                      className="tsm-input border rounded px-2 py-1.5" />
                    <input placeholder="结果数组路径（如 data.items）" value={connForm.result_path}
                      onChange={(e) => setConnForm({ ...connForm, result_path: e.target.value })}
                      className="tsm-input border rounded px-2 py-1.5" />
                    <input placeholder="标题字段 *" value={connForm.field_map_title}
                      onChange={(e) => setConnForm({ ...connForm, field_map_title: e.target.value })}
                      className="tsm-input border rounded px-2 py-1.5" />
                    <input placeholder="ID 字段 *" value={connForm.field_map_external_id}
                      onChange={(e) => setConnForm({ ...connForm, field_map_external_id: e.target.value })}
                      className="tsm-input border rounded px-2 py-1.5" />
                    <input placeholder="简介字段" value={connForm.field_map_description}
                      onChange={(e) => setConnForm({ ...connForm, field_map_description: e.target.value })}
                      className="tsm-input border rounded px-2 py-1.5" />
                    <button type="submit" className="px-3 py-1.5 rounded-xl text-sm font-medium col-span-2 justify-self-start"
                      style={{ backgroundColor: "var(--accent)", color: "#fff" }}>创建</button>
                  </form>
                )}
                {connMsg && <p className="mb-2 text-xs" style={{ color: "var(--text-secondary)" }}>{connMsg}</p>}
                {connectors.length === 0 ? (
                  <p className="text-sm" style={{ color: "var(--text-secondary)" }}>暂无数据源。</p>
                ) : (
                  <ul className="divide-y">
                    {connectors.map((c) => (
                      <li key={c.name} className="py-2 flex items-center justify-between text-sm">
                        <div>
                          <span className="font-medium">{c.display_name}</span>
                          <span className="ml-2 text-xs px-1.5 py-0.5 rounded-full"
                            style={{ backgroundColor: "var(--tag-bg)", color: "var(--tag-text)" }}>{c.name}</span>
                          <span className="ml-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                            {c.capabilities.join(", ")}</span>
                          <span className={`ml-2 text-xs ${c.enabled ? "" : "opacity-50"}`}
                            style={{ color: c.enabled ? "var(--ok)" : "var(--text-secondary)" }}>
                            {c.enabled ? "已启用" : "已停用"}</span>
                        </div>
                        <button onClick={() => handleDeleteConnector(c.name)}
                          className="text-xs" style={{ color: "var(--danger)" }}>删除</button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 设置页：左下角固定保存按钮 */}
      {section === "settings" && (
        <>
          {savedToast && (
            <div className="fixed bottom-6 left-6 z-40 px-4 py-2 rounded-full text-sm"
              style={{ backgroundColor: "var(--ok)", color: "#fff", boxShadow: "0 8px 30px rgba(0,0,0,0.25)" }}>
              设置已保存 ✓
            </div>
          )}
          <button onClick={handleSaveSettings}
            className="fixed bottom-6 left-6 z-40 px-5 py-2 rounded-full text-sm font-medium transition-transform hover:scale-105"
            style={{ backgroundColor: "var(--accent)", color: "#fff", boxShadow: "0 8px 30px rgba(0,0,0,0.25)" }}>
            保存设置
          </button>
        </>
      )}

      {/* 更换封面隐藏文件输入 */}
      <input ref={coverFileRef} type="file" accept="image/*" className="hidden"
        onChange={handleCoverFile} />

      {/* 新建分组浮层 */}
      {showGroupModal && (
        <div className="fixed inset-0 z-40 flex items-center justify-center p-4"
          style={{ backgroundColor: "rgba(10,12,20,0.45)" }}
          onClick={() => setShowGroupModal(false)}>
          <div className="desk-askbar rounded-2xl p-5 w-full max-w-sm"
            onClick={(e) => e.stopPropagation()}
            style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", backdropFilter: "blur(20px)" }}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium">新建分组</h3>
              <button onClick={() => setShowGroupModal(false)}
                className="text-xs px-2 py-0.5 rounded-lg"
                style={{ color: "var(--text-secondary)" }}>✕</button>
            </div>
            <input value={groupName} onChange={(e) => setGroupName(e.target.value)}
              placeholder="分组名称" autoFocus
              className="tsm-input w-full border rounded px-2.5 py-2 text-sm mb-3" />
            <div className="text-xs mb-2" style={{ color: "var(--text-secondary)" }}>按标签筛选（可选）</div>
            <div className="flex flex-wrap gap-1.5 mb-4 max-h-32 overflow-y-auto">
              {sortedTags.length === 0 && (
                <div className="text-xs" style={{ color: "var(--text-secondary)" }}>暂无标签</div>
              )}
              {sortedTags.map((t) => {
                const sel = groupTagSelection.includes(t.name);
                return (
                  <button key={t.id} onClick={() => toggleGroupTag(t.name)}
                    className="px-2 py-1 rounded-full text-xs transition-colors"
                    style={{ color: sel ? "#fff" : "var(--text-secondary)",
                      backgroundColor: sel ? "var(--accent)" : "rgba(255,255,255,0.06)",
                      border: "1px solid rgba(255,255,255,0.08)" }}>
                    #{t.name}
                  </button>
                );
              })}
            </div>
            <button onClick={addCustomGroup} disabled={!groupName.trim()}
              className="w-full px-3 py-2 rounded-xl text-sm font-medium disabled:opacity-40"
              style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
              创建
            </button>
          </div>
        </div>
      )}

      {/* 导入浮层（图标点击展开） */}
      {showImport && (
        <div className="fixed inset-0 z-40 flex items-center justify-center p-4"
          style={{ backgroundColor: "rgba(10,12,20,0.45)" }}
          onClick={() => setShowImport(false)}>
          <div className="desk-askbar rounded-2xl p-5 w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
            style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", backdropFilter: "blur(20px)" }}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium">导入资料</h3>
              <button onClick={() => setShowImport(false)}
                className="text-xs px-2 py-0.5 rounded-lg"
                style={{ color: "var(--text-secondary)" }}>✕</button>
            </div>
            {/* tab：文件 / 笔记 */}
            <div className="flex gap-1 mb-4 p-1 rounded-xl"
              style={{ backgroundColor: "rgba(255,255,255,0.06)" }}>
              {[["file", "上传文件"], ["note", "创建笔记"]].map(([k, label]) => (
                <button key={k} onClick={() => setImportTab(k)}
                  className="flex-1 px-3 py-1.5 rounded-lg text-xs"
                  style={{ color: importTab === k ? "#fff" : "var(--text-secondary)",
                    backgroundColor: importTab === k ? "var(--accent)" : "transparent" }}>
                  {label}
                </button>
              ))}
            </div>

            {importTab === "file" && (
              <form onSubmit={handleImport} className="flex flex-col gap-3">
                <input type="file" onChange={(e) => setFile(e.target.files[0] || null)}
                  className="text-sm" />
                <input placeholder="标签（逗号分隔，可选）" value={importTags}
                  onChange={(e) => setImportTags(e.target.value)}
                  className="tsm-input border rounded px-2 py-1.5 text-sm" />
                <button type="submit" disabled={uploading}
                  className="px-3 py-1.5 rounded-xl text-sm font-medium disabled:opacity-40 self-start"
                  style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
                  {uploading ? "导入中…" : "上传"}
                </button>
              </form>
            )}
            {importTab === "note" && (
              <form onSubmit={handleCreateNote} className="flex flex-col gap-3">
                <input placeholder="标题" value={noteTitle}
                  onChange={(e) => setNoteTitle(e.target.value)}
                  className="tsm-input border rounded px-2 py-1.5 text-sm" />
                <textarea placeholder="内容（Markdown 或纯文本）" value={noteContent}
                  onChange={(e) => setNoteContent(e.target.value)} rows={4}
                  className="tsm-input border rounded px-2 py-1.5 text-sm" />
                <input placeholder="标签（逗号分隔，可选）" value={noteTags}
                  onChange={(e) => setNoteTags(e.target.value)}
                  className="tsm-input border rounded px-2 py-1.5 text-sm" />
                <button type="submit" disabled={creatingNote}
                  className="px-3 py-1.5 rounded-xl text-sm font-medium disabled:opacity-40 self-start"
                  style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
                  {creatingNote ? "创建中…" : "创建笔记"}
                </button>
              </form>
            )}
            {importMsg && <p className="mt-3 text-xs" style={{ color: "var(--text-secondary)" }}>{importMsg}</p>}
          </div>
        </div>
      )}
    </div>
  );
}
