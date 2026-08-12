// Tsumugi 桌面图书馆（三栏布局）
// 布局：图标导航栏(ask固定顶 + 可排序区 + settings固定底) + 侧栏(搜索/分组标签) + 中央工作区
// 设置页分类：外观 / 导航栏 / 数据源（分类筛选在最上方）
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchItems, fetchTags, fetchAllReviews, fetchCollections, streamRag, federatedSearch, searchMy, deleteItem, saveExternal,
  filePathToUrl, createItem, uploadItem, uploadItemCover,
  fetchConnectors, createDeclarativeConnector, deleteConnector,
  saveConnectorProxy, testConnectorProxy,
  fetchCharacters, fetchItemDetail, fetchExternalDetail,
  refreshExternalItem, fetchPlugins, acknowledgePlugins,
  batchTagItems, batchDeleteItems, setItemTags,
  fetchLLMProviders, exportBackup, importBackup, fetchImportStatus,
} from "../api.js";
import InspectorPanel from "./InspectorPanel.jsx";
import ReviewStudio from "./ReviewStudio.jsx";
import ProviderSettings from "./ProviderSettings.jsx";
import CharacterWall from "./CharacterWall.jsx";
import VoiceGraphView from "./VoiceGraphView.jsx";
import YearlySummary from "./YearlySummary.jsx";
import ShareCardModal from "./ShareCardModal.jsx";
import Bookshelf from "./Bookshelf.jsx";
import StatusGroupedList from "./StatusGroupedList.jsx";
import ItemDetailPanel from "./ItemDetailPanel.jsx";
import ToastHost from "./ToastHost.jsx";
import ContextMenu from "./ContextMenu.jsx";
import CommandPalette from "./CommandPalette.jsx";
import CoverAmbient from "./CoverAmbient.jsx";
import HomeShrine from "./HomeShrine.jsx";
import MemoryGallery from "./MemoryGallery.jsx";
import MemoryReviewModal from "./MemoryReviewModal.jsx";
import ArchiveCard from "./ArchiveCard.jsx";
import { ShellC, ShellSwitcher, parseShell } from "./AppShells.jsx";
import { WORK_TYPES, WORK_TYPE_LABEL, PageHeader } from "./ui.jsx";
import ShortcutsModal from "./ShortcutsModal.jsx";
import TagEditModal from "./TagEditModal.jsx";
import BangumiPanel from "./BangumiPanel.jsx";
import { toast } from "../toast.js";
import { THEMES, STYLE_THEMES, ACCENT_HUE_RANGE, RADIUS_RANGE } from "../themes.js";

// 检索来源角标（ADR 0025）：区分用户自己写的内容与外部下载的百科资料
function sourceTypeLabel(s) {
  if (s.source_type === "external_reference") {
    return s.connector ? `百科·${s.connector}` : "百科";
  }
  if (s.source_type === "review") return "我的书评";
  if (s.source_type === "note") return "我的笔记";
  if (s.source_type === "memory") return "我的记忆"; // P7 / ADR 0051
  return "知识库";
}

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
  characters: { key: "characters", label: "角色", icon: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="9" cy="8" r="3.2" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><circle cx="17.5" cy="9" r="2.5" /><path d="M16 20a4.5 4.5 0 0 1 5.5-4.4" />
    </svg>
  ) },
  voice: { key: "voice", label: "声优图谱", icon: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="5" cy="6" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="12" cy="18" r="2.4" />
      <path d="M6.6 7.4 11 16M17.4 7.4 13 16M7 6h10M11.6 16.6l-.5-4.1M12.4 16.6l.5-4.1" />
    </svg>
  ) },
  summary: { key: "summary", label: "年度总结", icon: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  ) },
  memories: { key: "memories", label: "记忆回廊", icon: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 4v16M20 4v16" /><path d="M4 7h4v4H4zM10 7h4v4h-4zM16 7h4v4h-4z" />
      <path d="M4 14h16" /><path d="M4 17h4v3H4zM10 17h4v3h-4zM16 17h4v3h-4z" />
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
const SORTABLE_KEYS = ["ask", "library", "inspector", "characters", "voice", "summary", "memories"];

// 馆内导览（ADR 0066）：UI 房间 → 内部 section 映射（不重命名内部键/路由/数据结构）
const ROOM_META = {
  ask: { room: "检索台", en: "Desk", no: "05" },
  library: { room: "书库", en: "Library", no: "01" },
  memories: { room: "记忆回廊", en: "Gallery", no: "02" },
  summary: { room: "时光轴", en: "Timeline", no: "03" },
  characters: { room: "人物档案", en: "Archive", no: "04" },
  settings: { room: "管理室", en: "Office", no: "06" },
};
const TOOL_META = { inspector: { label: "分析" }, voice: { label: "声优图谱" } };
// 移动端底部房间导航顺序
const ROOMS_ALL = ["ask", "library", "memories", "summary", "characters", "settings"];

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

export default function DesktopView({ items, total, allTags, refresh, theme, setTheme, custom, updateCustom, styleTheme, setStyleTheme, textOverlays, updateTextOverlays }) {
  const [section, setSection] = useState("ask"); // 默认打开问答
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [activeTag, setActiveTag] = useState(null);
  const [activeGroup, setActiveGroup] = useState("all");
  const [navOrder, setNavOrder] = useState(() => loadNavOrder());

  // 文字涂鸦编辑模式（蒙版）
  const [overlayEditMode, setOverlayEditMode] = useState(false);
  // 长按导航调整模式
  const [navRearrangeMode, setNavRearrangeMode] = useState(false);
  // 平板/移动：馆内导览抽屉（ADR 0066）
  const [navDrawer, setNavDrawer] = useState(false);
  // 设置保存提示
  const [savedToast, setSavedToast] = useState(false);
  // 书评面板：当前打开 review 面板的 item（null=关闭）
  const [reviewItem, setReviewItem] = useState(null);
  // 作品详情弹层：{detail, saved}；null=关闭（角色图鉴）
  const [detailView, setDetailView] = useState(null); // { itemId, externalDetail, saved }
  const [detailRefreshKey, setDetailRefreshKey] = useState(0); // 刷新资料后重取详情
  // 安利卡弹层：当前生成安利卡的 item id（null=关闭）
  const [shareItem, setShareItem] = useState(null);
  // 图书馆视图模式：网格 / 书架 / 分组列表（localStorage 记忆，复用主题持久化模式）
  const [libView, setLibView] = useState(() => {
    try { return localStorage.getItem("tsumugi-lib-view") || "grid"; } catch { return "grid"; }
  });
  useEffect(() => {
    try { localStorage.setItem("tsumugi-lib-view", libView); } catch { /* ignore */ }
  }, [libView]);
  // 主从视图（ADR 0029 分组列表模式）：当前选中浏览的条目 id
  const [detailBrowseId, setDetailBrowseId] = useState(null);
  // 条目 → 追番状态 映射（P2 / ADR 0046：收藏状态源改为 collections 表，不再取书评状态）
  const [statusMap, setStatusMap] = useState({});
  // 最近书评（首页"最近供奉"的文案，ADR 0039）；reviewCount 供猫娘台词里程碑判定
  const [recentReviews, setRecentReviews] = useState([]);
  const [reviewCount, setReviewCount] = useState(null);
  useEffect(() => {
    fetchAllReviews()
      .then((reviews) => {
        setRecentReviews(reviews.slice(0, 3));
        setReviewCount(reviews.length);
      })
      .catch(() => {});
    fetchCollections()
      .then((rows) => {
        const map = {};
        for (const c of rows) if (c.status) map[c.item_id] = c.status;
        setStatusMap(map);
      })
      .catch(() => {});
  }, []);
  // 角色墙刷新计数（收藏新作品后 +1）
  const [charRefreshKey, setCharRefreshKey] = useState(0);
  // AI 问答状态灯：当前启用的 Provider（null=加载中）
  const [aiStatus, setAiStatus] = useState(null);
  const loadAiStatus = () => fetchLLMProviders()
    .then((d) => setAiStatus({ enabled: !!d.enabled_name, name: d.enabled_name }))
    .catch(() => setAiStatus({ enabled: false, name: null }));
  useEffect(() => { loadAiStatus(); }, []);
  useEffect(() => {
    if (section === "ask") loadAiStatus(); // 进问答区时刷新
  }, [section]);
  // 批量选择模式
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  // 右键菜单：{x, y, item}
  const [ctxMenu, setCtxMenu] = useState(null);
  // 标签编辑弹层：{itemIds, title}
  const [tagEdit, setTagEdit] = useState(null);
  // 快捷键说明
  const [showShortcuts, setShowShortcuts] = useState(false);
  // 命令面板（ADR 0031：Ctrl/Cmd+K）
  const [commandOpen, setCommandOpen] = useState(false);
  // 声优图谱聚焦（ADR 0032/0036：角色墙/命令入口传入声优名，图谱自动选中）
  const [voiceFocus, setVoiceFocus] = useState(null);
  // 离开声优图谱时清空聚焦（否则再次进入会重新聚焦上次的声优，而非搜索入口）
  useEffect(() => { if (section !== "voice") setVoiceFocus(null); }, [section]);

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
  // P6 检索台（ADR 0050）：个人全文检索结果 + 只读记忆弹层
  const [mySearch, setMySearch] = useState(null); // {q, loading, works, reviews, memories}
  const [openMem, setOpenMem] = useState(null);   // {itemId, sourceRef, memory}|null
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
  // 第三方插件（ADR 0027：本地文件信任模型，设置页「插件」面板）
  const [pluginsData, setPluginsData] = useState({ plugins: [], failures: [], notice_needed: false, plugin_dir: "" });
  // 出站代理编辑
  const [proxyEditName, setProxyEditName] = useState(null); // 正在编辑代理的数据源名
  const [proxyDraft, setProxyDraft] = useState("");
  const [proxyTesting, setProxyTesting] = useState(false);
  const [proxyTestMsg, setProxyTestMsg] = useState(null); // {ok, message}

  // 设置页分类 tab
  const [settingsTab, setSettingsTab] = useState("appearance"); // appearance | nav | sources

  const sortedTags = [...allTags].sort((a, b) => b.count - a.count);

  // 资料库网格：走后端筛选
  const [gridItems, setGridItems] = useState([]);
  const [gridTotal, setGridTotal] = useState(0);
  const [gridLoading, setGridLoading] = useState(false);
  const [groupCounts, setGroupCounts] = useState({ all: total, note: 0, image: 0, external: 0 });
  const [statsLoaded, setStatsLoaded] = useState(false);
  // 最近一次外部收藏时间（猫娘台词"新收藏"判定，ADR 0040）：
  // 与 collectionCount 同一批请求返回，避免依赖 App 的 items 异步到达导致台词选错场景
  const [newestCollectionAt, setNewestCollectionAt] = useState(null);

  useEffect(() => {
    Promise.all([
      fetchItems({ type: "note", limit: 1 }),
      fetchItems({ type: "image", limit: 1 }),
      fetchItems({ type: "external_ref", limit: 1 }),
    ])
      .then(([n, im, ex]) => {
        setGroupCounts({ all: total, note: n.total, image: im.total, external: ex.total });
        setNewestCollectionAt(ex.items && ex.items.length ? (ex.items[0].created_at || null) : null);
      })
      .catch(() => {})
      .finally(() => setStatsLoaded(true)); // 失败也视为已加载（用 0 兜底），供猫娘台词判定
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
    // P6 检索台（ADR 0050）：个人全文检索（作品/书评/记忆）
    setMySearch({ q, loading: true, works: [], reviews: [], memories: [] });
    searchMy(q)
      .then((r) => setMySearch({ q, loading: false, works: r.works || [], reviews: r.reviews || [], memories: r.memories || [] }))
      .catch(() => setMySearch({ q, loading: false, works: [], reviews: [], memories: [] }));
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
    // P6 检索台（ADR 0050）：个人全文检索
    setMySearch({ q, loading: true, works: [], reviews: [], memories: [] });
    searchMy(q)
      .then((r) => setMySearch({ q, loading: false, works: r.works || [], reviews: r.reviews || [], memories: r.memories || [] }))
      .catch(() => setMySearch({ q, loading: false, works: [], reviews: [], memories: [] }));
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
      setCharRefreshKey((k) => k + 1);
      toast.success(`已收藏「${r.title}」`);
    } catch (err) {
      toast.error(err.message);
    }
  }

  // ---- 角色图鉴：详情弹层（Phase 3-1 / ADR 0075：统一 Work Detail 内容系统）
  // detailView = { itemId:number|null, externalDetail:ExternalDetailOut|null, saved:bool }
  async function openExternalDetail(r) {
    try {
      const d = await fetchExternalDetail(r.source, r.external_id);
      setDetailView({ itemId: null, externalDetail: d, saved: false });
    } catch (err) {
      setAskError(err.message);
    }
  }

  function openItemDetail(it) {
    setDetailView({ itemId: it.id, externalDetail: null, saved: true });
  }

  // 手动刷新外部条目资料：重新拉取最新简介/角色小传（受限流约束，非阻塞 UI）
  async function handleRefreshExternal() {
    if (!detailView || !detailView.saved || detailView.itemId == null) return;
    const itemId = detailView.itemId;
    try {
      await refreshExternalItem(itemId);
      const fresh = await fetchItemDetail(itemId);
      setDetailRefreshKey((k) => k + 1);
      refresh();
      setCharRefreshKey((k) => k + 1);
      toast.success(`已刷新「${fresh.title}」的完整资料`);
    } catch (err) {
      toast.error(err.message);
    }
  }

  function openWorkDetail(w) {
    openItemDetail({ id: w.item_id });
  }

  async function detailSave() {
    if (!detailView || detailView.saved) return;
    const d = detailView.externalDetail;
    if (!d) return;
    try {
      const res = await saveExternal({
        source: d.source, external_id: d.external_id, title: d.title,
        description: d.description, image_url: d.image_url, tags: d.tags,
      });
      // 收藏入库后切换为已收藏模式（统一详情自取）
      setDetailView({ itemId: res.item_id, externalDetail: null, saved: true });
      refresh();
      setCharRefreshKey((k) => k + 1);
      toast.success(`已收藏「${d.title}」`);
    } catch (err) {
      toast.error(err.message);
    }
  }

  // ---- 批量选择 ----
  function toggleSelect(id) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function exitSelectMode() {
    setSelectMode(false);
    setSelectedIds(new Set());
  }

  async function handleBatchDelete() {
    const ids = [...selectedIds];
    if (ids.length === 0) return;
    if (!window.confirm(`确认删除选中的 ${ids.length} 项？该操作不可撤销。`)) return;
    try {
      const r = await batchDeleteItems(ids);
      toast.success(`已删除 ${r.deleted} 项`);
      refresh();
      setCharRefreshKey((k) => k + 1);
      exitSelectMode();
    } catch (err) {
      toast.error(err.message);
    }
  }

  async function applyTags(tags, mode) {
    if (!tagEdit) return;
    const ids = tagEdit.itemIds;
    try {
      if (ids.length === 1) {
        await setItemTags(ids[0], tags, mode);
      } else {
        await batchTagItems(ids, tags, mode);
      }
      const action = mode === "remove" ? "移除" : mode === "set" ? "替换为" : "添加";
      toast.success(`已${action}标签 ${tags.length} 个 · ${ids.length} 项`);
      refresh();
    } catch (err) {
      toast.error(err.message);
    }
  }

  // ---- 右键菜单 ----
  function openCtxMenu(e, it) {
    e.preventDefault();
    if (selectMode) return; // 选择模式下右键不干扰
    setCtxMenu({ x: e.clientX, y: e.clientY, item: it });
  }

  function ctxItems() {
    if (!ctxMenu) return [];
    const it = ctxMenu.item;
    return [
      { label: "查看详情", onClick: () => openItemDetail(it) },
      { label: "编辑标签", onClick: () => setTagEdit({ itemIds: [it.id], title: `编辑「${it.title.slice(0, 12)}」标签` }) },
      { label: "写读后感", onClick: () => setReviewItem(it) },
      { label: "生成安利卡", onClick: () => setShareItem(it.id) },
      { divider: true },
      {
        label: "删除", danger: true,
        onClick: async () => {
          if (!window.confirm(`确认删除「${it.title}」？`)) return;
          try {
            await deleteItem(it.id);
            toast.success("已删除");
            refresh();
          } catch (err) {
            toast.error(err.message);
          }
        },
      },
    ];
  }

  // ---- 键盘快捷键（ADR 0031：Ctrl/Cmd+K=命令面板；/ 聚焦问答；? 快捷键说明；Esc 关闭）----
  useEffect(() => {
    const onKey = (e) => {
      const tag = (e.target && e.target.tagName) || "";
      const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        // Ctrl+K 呼出命令面板（行业惯例；/ 仍保留为聚焦问答搜索，能力未丢失）
        setCommandOpen((v) => !v);
        return;
      }
      if (e.key === "/" && !typing) {
        e.preventDefault();
        setSection("ask");
        setTimeout(() => askInputRef.current?.focus?.(), 30);
        return;
      }
      if (e.key === "?" && !typing) {
        e.preventDefault();
        setShowShortcuts((v) => !v);
        return;
      }
      if (e.key === "Escape") {
        if (commandOpen) { setCommandOpen(false); return; }
        if (ctxMenu) { setCtxMenu(null); return; }
        if (tagEdit) { setTagEdit(null); return; }
        if (showShortcuts) { setShowShortcuts(false); return; }
        if (selectMode) { exitSelectMode(); return; }
        if (detailView) { setDetailView(null); return; }
        if (shareItem != null) { setShareItem(null); return; }
        if (reviewItem) { setReviewItem(null); return; }
        if (showImport) { setShowImport(false); return; }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  async function handleImport(e) {
    e.preventDefault();
    if (!file) return toast.info("请先选择文件");
    setUploading(true);
    setImportMsg("");
    try {
      const result = await uploadItem(file, null, importTags);
      if (result.duplicated) toast.info("内容已存在，跳过导入");
      else toast.success(`已导入「${result.title}」`);
      setFile(null);
      setImportTags("");
      refresh();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setUploading(false);
    }
  }

  async function handleCreateNote(e) {
    e.preventDefault();
    if (!noteTitle.trim() || !noteContent.trim()) {
      return toast.info("笔记需要标题和内容");
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
      if (result.duplicated) toast.info("内容已存在，跳过导入");
      else toast.success(`已创建笔记「${result.title}」`);
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
    // 优先本地缓存的封面（同源可读、可靠），与详情面板/安利卡一致；远程 image_url 兜底
    if (it.file_path) {
      const local = filePathToUrl(it.file_path);
      if (local) return local;
    }
    if (it.image_url) return it.image_url;
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

  // 插件状态（设置页「插件」面板）：进入设置页时刷新
  const loadPlugins = () => fetchPlugins().then(setPluginsData).catch(() => {});
  useEffect(() => { if (section === "settings") loadPlugins(); }, [section]);

  async function handleAcknowledgePlugins() {
    try {
      await acknowledgePlugins();
      setPluginsData((p) => ({ ...p, notice_needed: false }));
      toast.success("已确认，不再提示");
    } catch (err) { toast.error(err.message); }
  }

  // ---- 数据备份/导出/导入（ADR 0038） ----
  const [backupState, setBackupState] = useState({ exporting: false, importing: false, progress: null });
  const backupFileRef = useRef(null);

  async function handleExportBackup() {
    setBackupState((s) => ({ ...s, exporting: true }));
    try {
      const data = await exportBackup();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const ts = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      a.href = url;
      a.download = `tsumugi-backup-${ts}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`已导出 ${(data.data?.items || []).length} 个条目`);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBackupState((s) => ({ ...s, exporting: false }));
    }
  }

  async function handleImportFile(file) {
    if (!file) return;
    setBackupState({ exporting: false, importing: true, progress: null });
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const { job_id } = await importBackup(data);
      // 轮询导入任务进度（后台线程重建向量，可能较慢）
      for (let i = 0; i < 600; i++) {
        await new Promise((r) => setTimeout(r, 500));
        const st = await fetchImportStatus(job_id);
        if (st.state === "done") {
          setBackupState({ exporting: false, importing: false, progress: null });
          toast.success(st.message || "导入完成");
          refresh();
          setCharRefreshKey((k) => k + 1);
          return;
        }
        if (st.state === "error") { throw new Error(st.message || "导入失败"); }
        setBackupState((s) => ({
          exporting: false, importing: true,
          progress: st.total ? Math.min(100, Math.round((st.current / st.total) * 100)) : null,
        }));
      }
      throw new Error("导入超时");
    } catch (err) {
      setBackupState({ exporting: false, importing: false, progress: null });
      toast.error(err.message || "导入失败（文件格式是否正确？）");
    }
  }

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

  function openProxyEditor(c) {
    setProxyEditName(c.name);
    setProxyDraft(c.proxy_url || "");
    setProxyTestMsg(null);
  }

  async function handleSaveProxy(name) {
    try {
      await saveConnectorProxy(name, proxyDraft.trim());
      setConnMsg(`已保存「${name}」出站代理`);
      setProxyEditName(null);
      setProxyTestMsg(null);
      loadConnectors();
    } catch (err) {
      setConnMsg(err.message);
    }
  }

  async function handleTestProxy(name) {
    setProxyTesting(true);
    setProxyTestMsg(null);
    try {
      const r = await testConnectorProxy(name, proxyDraft.trim());
      setProxyTestMsg({ ok: r.ok, message: r.message || r.detail });
    } catch (err) {
      setProxyTestMsg({ ok: false, message: err.message });
    } finally {
      setProxyTesting(false);
    }
  }

  function handleSaveSettings() {
    // 所有设置均实时持久化到 localStorage，此按钮仅作确认反馈
    setSavedToast(true);
    setTimeout(() => setSavedToast(false), 1500);
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
    { key: "model", label: "模型" },
    { key: "bangumi", label: "Bangumi" },
    { key: "nav", label: "导航栏" },
    { key: "sources", label: "数据源" },
    { key: "plugins", label: "插件" },
    { key: "backup", label: "备份" },
  ];
  // 是否已有问答内容（决定搜索框居中/置顶；P6 检索台：只要提交过检索就切换到内容分支）
  const hasContent = !!(answer || sources.length > 0 || fedResults.length > 0
    || (mySearch && (mySearch.q || mySearch.works.length || mySearch.reviews.length || mySearch.memories.length)));
  // P1（ADR 0045）：图书馆按作品类型筛选（work_type）
  const [activeWorkType, setActiveWorkType] = useState(null);
  const workTypeOptions = WORK_TYPES.filter((t) => (gridItems || []).some((it) => it.work_type === t));
  // 外壳空间结构探索（ADR 0057）：?shell=a|b|c|classic 或 localStorage，临时探索用
  const [shellConcept, setShellConcept] = useState(() => parseShell(localStorage.getItem("tsumugi-shell-concept")) || "classic");
  useEffect(() => {
    const fromUrl = parseShell(new URLSearchParams(window.location.search).get("shell"));
    if (fromUrl) setShellConcept(fromUrl);
  }, []);
  const changeShellConcept = (k) => {
    setShellConcept(k);
    try { localStorage.setItem("tsumugi-shell-concept", k); } catch { /* ignore */ }
  };
  // 图书馆网格：按 work_type + libQuery 本地过滤（标题/内容）
  const libFiltered = gridItems.filter((it) => {
    if (activeWorkType && it.work_type !== activeWorkType) return false;
    if (!libQuery.trim()) return true;
    const q = libQuery.trim().toLowerCase();
    return (it.title || "").toLowerCase().includes(q) || (it.content || "").toLowerCase().includes(q);
  });

  // 命令面板上下文（ADR 0031）：命令注册表只依赖这一组可执行回调
  const paletteItems = useMemo(() => {
    const seen = new Map();
    for (const it of [...(items || []), ...(gridItems || [])]) {
      if (it && it.id != null && !seen.has(it.id)) seen.set(it.id, it);
    }
    return [...seen.values()];
  }, [items, gridItems]);
  const cmdCtx = useMemo(() => ({
    items: paletteItems,
    tags: allTags,
    openItem: (it) => { setSection("library"); setLibView("list"); setDetailBrowseId(it.id); },
    openImport: () => setShowImport(true),
    section: (k) => setSection(k),
    ask: () => { setSection("ask"); setTimeout(() => askInputRef.current?.focus?.(), 30); },
    setTheme,
    openTag: (name) => { setSection("library"); setActiveGroup("all"); setCustomActive(null); setActiveTag(name); },
    shareCard: () => {
      if (detailBrowseId != null) setShareItem(detailBrowseId);
      else toast.info("先在资料库分组列表中选中一条资料");
    },
    reviewStudio: () => {
      const it = paletteItems.find((x) => x.id === detailBrowseId);
      if (it) setReviewItem(it);
      else toast.info("先在资料库分组列表中选中一条资料");
    },
    openVoiceGraph: () => { setVoiceFocus(null); setSection("voice"); },
    openSummary: () => setSection("summary"),
    openMemories: () => setSection("memories"),
  }), [paletteItems, allTags, setTheme, detailBrowseId]);

  // 神殿首页（ADR 0039）：代表封面 = 最近的外部收藏（有封面）的封面，驱动首页环境光
  const recentExternalItems = (items || []).filter((it) => it.source !== "local" && cardCover(it)).slice(0, 6);
  const representativeCover = recentExternalItems.length ? cardCover(recentExternalItems[0]) : null;
  // 猫娘台词数据（ADR 0040）：最近书评时间 + 收藏数/书评数
  const newestReviewAt = recentReviews.length ? (recentReviews[0].created_at || null) : null;

  // 问答搜索栏（空态时放入神殿首页作为"祭坛"焦点，有内容时置顶）
  const askSearchBar = (
    <div className="relative w-full max-w-2xl">
      <div
        className="w-full desk-searchbar flex items-center gap-3 px-5 py-3"
        style={{
          backgroundColor: "var(--input-bg)",
          border: "1px solid var(--input-border)",
          borderRadius: "var(--radius-control)",
          transition: "border-color 0.2s ease, box-shadow 0.2s ease",
          boxShadow: "0 1px 4px rgba(0,0,0,0.04)",
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
        <button onClick={() => setHistoryOpen((v) => !v)} title="搜索历史"
          className="shrink-0 p-1.5 transition-colors"
          style={{ color: "var(--text-secondary)", backgroundColor: historyOpen ? "var(--accent-soft)" : "transparent", borderRadius: "var(--radius-control)" }}>
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /><path d="M12 7v5l3 2" />
          </svg>
        </button>
        <button onClick={handleAsk} disabled={asking || !query.trim()}
          className="text-sm px-4 py-1.5 shrink-0 disabled:opacity-40 font-medium"
          style={{ backgroundColor: "var(--accent)", color: "#fff", borderRadius: "var(--radius-control)" }}>
          {asking ? "思考中…" : "提问"}
        </button>
        <button onClick={loadAiStatus} title="AI 问答状态（点击刷新）"
          className="shrink-0 flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px]"
          style={{
            backgroundColor: aiStatus?.enabled ? "var(--tag-bg)" : "rgba(245,158,11,0.14)",
            color: aiStatus?.enabled ? "var(--tag-text)" : "#b45309",
          }}>
          <span className="w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: aiStatus?.enabled ? "var(--ok)" : "#f59e0b" }} />
          {aiStatus === null ? "AI…" : aiStatus.enabled ? `AI: ${aiStatus.name}` : "AI 未启用"}
        </button>
      </div>
      {historyOpen && (
        <div className="history-dropdown absolute right-0 top-full mt-2 w-full max-w-sm rounded-2xl p-3 z-30"
          style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)" }}>
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
  );

  // 馆内导览导航项（ADR 0066）：馆室 serif+编号，工具 sans；保留长按/拖拽排序
  const renderNavItem = (k, opts = {}) => {
    const meta = ROOM_META[k];
    const tool = TOOL_META[k];
    const isRoom = !!meta;
    const label = isRoom ? meta.room : (tool ? tool.label : (NAV[k]?.label || k));
    return (
      <button key={k}
        onClick={() => { if (!navRearrangeMode) { handleSection(k); opts.onClick?.(); } }}
        onMouseDown={() => { if (k !== "settings" && k !== "ask") startLongPress(); }}
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
        title={navRearrangeMode ? "拖动调整位置" : label}
        className="flex items-center gap-2 px-2 py-1.5 rounded text-left transition-colors shrink-0 w-full"
        style={{
          color: section === k ? "var(--accent)" : "var(--text-secondary)",
          backgroundColor: section === k ? "var(--accent-soft)" : "transparent",
          cursor: navRearrangeMode ? "grab" : "pointer",
          outline: navRearrangeMode ? "1px dashed var(--accent)" : "none",
          ...opts.style,
        }}>
        <span className="text-[9px] w-4 shrink-0 text-center"
          style={{ fontFamily: "var(--font-mono)", color: section === k ? "var(--accent)" : "var(--ink-2)" }}>
          {isRoom ? meta.no : "·"}
        </span>
        <span className="text-[12px] truncate"
          style={{ fontFamily: isRoom ? "var(--font-heading)" : "var(--font-body)", letterSpacing: isRoom ? "0.06em" : "0", fontWeight: isRoom ? 500 : 400 }}>
          {label}
        </span>
      </button>
    );
  };

  return (
    <>
      {shellConcept === "classic" ? (
    <div className="desktop-view flex relative flex-1 min-h-0 overflow-hidden"
      data-testid="app-shell">

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

      {/* 1. 馆内导览（ADR 0066）：纸感馆室列表，serif 馆室 + mono 编号（lg 以上显示） */}
      <nav className="desk-nav flex-col py-4 px-2.5 gap-1 z-10 shrink-0 hidden lg:flex"
        style={{ width: 176, backgroundColor: "var(--rail-bg)", borderRight: "1px solid var(--panel-border)" }}
        data-testid="left-nav">
        <div className="px-2 mb-4">
          <div className="tsm-heading text-lg leading-none" style={{ color: "var(--accent)" }}>紬</div>
          <div className="text-[9px] tracking-[0.3em] mt-1" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>TSUMUGI</div>
        </div>
        {renderNavItem("ask")}
        <div className="px-2 mt-2 mb-1 text-[9px] tracking-[0.2em]" style={{ color: "var(--ink-2)", fontFamily: "var(--font-mono)" }}>馆室 ROOMS</div>
        {sortedNavKeys.filter((k) => ROOM_META[k]).map((k) => renderNavItem(k))}
        <div className="px-2 mt-3 mb-1 text-[9px] tracking-[0.2em]" style={{ color: "var(--ink-2)", fontFamily: "var(--font-mono)" }}>工具 TOOLS</div>
        {sortedNavKeys.filter((k) => TOOL_META[k]).map((k) => renderNavItem(k))}
        <div className="flex-1" />
        {renderNavItem("settings")}
        <button onClick={() => setShowShortcuts(true)} title="快捷键 (?)"
          className="flex items-center gap-2 px-2 py-1.5 rounded text-[12px] transition-colors"
          style={{ color: "var(--text-secondary)" }}>
          <span className="text-[9px] w-4 shrink-0 text-center" style={{ fontFamily: "var(--font-mono)" }}>?</span>
          <span>快捷键</span>
        </button>
      </nav>

      {/* 平板/移动：馆内导览抽屉（点击汉堡呼出） */}
      {navDrawer && (
        <div className="desk-drawer-mask" onClick={() => setNavDrawer(false)}>
          <div className="desk-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 pt-4 pb-2.5 border-b"
              style={{ borderColor: "var(--panel-border)" }}>
              <div>
                <div className="tsm-heading text-base leading-none" style={{ color: "var(--accent)" }}>紬</div>
                <div className="text-[9px] tracking-[0.3em] mt-1" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>TSUMUGI</div>
              </div>
              <button onClick={() => setNavDrawer(false)} title="关闭" className="text-sm px-1"
                style={{ color: "var(--text-secondary)" }}>✕</button>
            </div>
            <div className="p-2.5 flex flex-col gap-1 overflow-y-auto h-full">
              {renderNavItem("ask", { onClick: () => setNavDrawer(false) })}
              <div className="px-2 mt-2 mb-1 text-[9px] tracking-[0.2em]" style={{ color: "var(--ink-2)", fontFamily: "var(--font-mono)" }}>馆室 ROOMS</div>
              {sortedNavKeys.filter((k) => ROOM_META[k]).map((k) => renderNavItem(k, { onClick: () => setNavDrawer(false) }))}
              <div className="px-2 mt-3 mb-1 text-[9px] tracking-[0.2em]" style={{ color: "var(--ink-2)", fontFamily: "var(--font-mono)" }}>工具 TOOLS</div>
              {sortedNavKeys.filter((k) => TOOL_META[k]).map((k) => renderNavItem(k, { onClick: () => setNavDrawer(false) }))}
              {renderNavItem("settings", { onClick: () => setNavDrawer(false) })}
            </div>
          </div>
        </div>
      )}

      {/* 2. 半透明侧栏（可拖拽调宽 + 中心收缩按钮）；独立于主内容，不随其滚动 */}
      <aside ref={sidebarRef} className="relative flex flex-col z-10 shrink-0"
        style={{
          width: sidebarOpen ? sidebarWidth : 36,
          backgroundColor: "var(--rail-bg)",
          borderRight: "1px solid var(--panel-border)",
          transition: "width 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
        }}
        data-testid="left-sidebar">
        {/* 拖拽手柄（收缩时隐藏并禁用交互） */}
        <div ref={dragRef}
          className="absolute right-0 top-0 bottom-0 z-20"
          style={{ width: 5, cursor: "col-resize", opacity: sidebarOpen ? 1 : 0, pointerEvents: sidebarOpen ? "auto" : "none" }} />
        {/* 侧栏内容（淡入淡出；收缩时裁剪到细条，实现完全收缩） */}
        <div className="flex-1 min-h-0 overflow-hidden"
          style={{
            opacity: sidebarOpen ? 1 : 0,
            transition: "opacity 0.18s ease",
            transitionDelay: sidebarOpen ? "0.12s" : "0s",
            pointerEvents: sidebarOpen ? "auto" : "none",
          }}>
          <div className="h-full flex flex-col min-h-0">
            {/* 图书馆侧栏内容（分组 + 标签）或 问答提示；独立内部滚动 */}
            <div className="flex-1 min-h-0 overflow-y-auto px-2.5 pb-2 pt-3">
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
                      {/* Phase 2-4（ADR 0071）：数量降权为 mono 微字 */}
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.08em", color: "var(--ink-2)" }}>{c}</span>
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
                          <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.08em", color: "var(--ink-2)" }}>{t.count}</span>
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
          </div>
        {/* 展开/收缩按钮：垂直居中于侧栏边缘；收缩时滑到细条中央 */}
        <button onClick={() => setSidebarOpen((v) => !v)}
          title={sidebarOpen ? "收起侧栏" : "展开侧栏"}
          aria-label={sidebarOpen ? "收起侧栏" : "展开侧栏"}
          className="absolute z-30 flex items-center justify-center"
          style={{
            top: "50%",
            transform: "translateY(-50%)",
            width: 22, height: 22,
            borderRadius: "9999px",
            backgroundColor: "var(--rail-bg)",
            border: "1px solid var(--panel-border)",
            boxShadow: "0 2px 10px rgba(0,0,0,0.18)",
            color: "var(--text-secondary)",
            cursor: "pointer",
            transition: "right 0.3s cubic-bezier(0.4, 0, 0.2, 1), background-color 0.2s, color 0.2s",
            right: sidebarOpen ? -11 : 7,  // 展开=跨骑右边缘；收缩=细条(36px)居中
          }}>
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2.2"
            strokeLinecap="round" strokeLinejoin="round"
            style={{ transform: sidebarOpen ? "rotate(0deg)" : "rotate(180deg)", transition: "transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)" }}>
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
      </aside>

      {/* 3. 中央工作区：唯一的主内容滚动容器（ADR 0028），其余固定 */}
      {/* 3. 主工作区 + 顶部栏（ADR 0066：面包屑 + 全局检索入口 + Ctrl+K） */}
      <div className="flex-1 min-h-0 relative overflow-y-auto p-6 z-10" data-testid="main-content">
        {/* 顶栏：mono 面包屑（房间 / 英文） + 全局检索 + 命令面板入口；移动端含汉堡 */}
        <div className="sticky top-0 z-20 flex items-center gap-3 mb-5 -mt-6 -mx-6 px-6 py-3 border-b"
          style={{ backgroundColor: "var(--bg)", borderColor: "var(--panel-border)" }}>
          <button className="lg:hidden p-1.5 rounded" onClick={() => setNavDrawer(true)} title="馆内导览"
            style={{ color: "var(--text-secondary)" }}>
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </button>
          <span className="text-[10px] tracking-[0.2em] truncate"
            style={{ color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
            {ROOM_META[section] ? `${ROOM_META[section].room} / ${ROOM_META[section].en}` : (NAV[section]?.label || section)}
          </span>
          <div className="flex-1" />
          <button onClick={() => handleSection("ask")} title="全局检索"
            className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] transition-colors"
            style={{ color: "var(--text-secondary)" }}>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.35-4.35" /></svg>
            检索台
          </button>
          <button onClick={() => setCommandOpen(true)} title="命令面板 (Ctrl+K)"
            className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] transition-colors"
            style={{ color: "var(--text-secondary)" }}>
            <span className="text-[9px] px-1 py-px rounded" style={{ backgroundColor: "var(--surface-2)" }}>Ctrl K</span>
            命令
          </button>
        </div>

        {section === "library" && (
          <div className="lib-space h-full flex flex-col min-h-0">
            <PageHeader room="书库" path="LIBRARY" />
            {/* 工具栏（Phase 2-3 / ADR 0070）：「整理书架」三级层级——
                Level1 搜索（主入口）/ Level2 视图切换 / Level3 批量选择（默认安静） */}
            <div className="flex items-center justify-between gap-3 mb-4 shrink-0 flex-wrap">
              <div className="flex items-center gap-2 px-3.5 py-2 w-full sm:w-72"
                style={{ backgroundColor: "var(--input-bg)", border: "1px solid var(--input-border)", borderRadius: "var(--radius-control)" }}>
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5"
                  strokeLinecap="round" className="shrink-0" style={{ color: "var(--text-secondary)" }}>
                  <circle cx="11" cy="11" r="7" /><path d="M21 21l-4.35-4.35" />
                </svg>
                <input value={libQuery}
                  onChange={(e) => setLibQuery(e.target.value)}
                  placeholder="查找存储的内容…"
                  className="flex-1 bg-transparent outline-none text-sm min-w-0"
                  style={{ color: "var(--text)" }} />
                {libQuery && (
                  <button onClick={() => setLibQuery("")} title="清除搜索" className="text-[11px] shrink-0"
                    style={{ color: "var(--text-secondary)" }}>✕</button>
                )}
              </div>
              <div className="flex items-center gap-2">
                {/* 视图切换：紧凑安静（Control 圆角，非胶囊） */}
                <div className="flex items-center gap-0.5 px-1 py-0.5"
                  style={{ backgroundColor: "var(--input-bg)", border: "1px solid var(--input-border)", borderRadius: "var(--radius-control)" }}>
                  <button onClick={() => setLibView("grid")} title="网格视图"
                    className="px-2.5 py-1.5 text-[11px]"
                    style={{ borderRadius: "var(--radius-control)", backgroundColor: libView === "grid" ? "var(--accent-soft)" : "transparent",
                      color: libView === "grid" ? "var(--accent)" : "var(--text-secondary)" }}>▦</button>
                  <button onClick={() => setLibView("shelf")} title="书架视图"
                    className="px-2.5 py-1.5 text-[11px]"
                    style={{ borderRadius: "var(--radius-control)", backgroundColor: libView === "shelf" ? "var(--accent-soft)" : "transparent",
                      color: libView === "shelf" ? "var(--accent)" : "var(--text-secondary)" }}>▤</button>
                  <button onClick={() => setLibView("list")} title="分组列表（主从视图）"
                    className="px-2.5 py-1.5 text-[11px]"
                    style={{ borderRadius: "var(--radius-control)", backgroundColor: libView === "list" ? "var(--accent-soft)" : "transparent",
                      color: libView === "list" ? "var(--accent)" : "var(--text-secondary)" }}>☰</button>
                </div>
                {/* 批量选择入口（Level3：默认安静，进入 Selection Mode 才获得权重） */}
                <button onClick={() => { setSelectMode((v) => !v); setSelectedIds(new Set()); }}
                  title="批量选择"
                  className="px-2.5 py-1.5 text-[11px]"
                  style={{ borderRadius: "var(--radius-control)", color: selectMode ? "var(--accent)" : "var(--text-secondary)",
                    backgroundColor: selectMode ? "var(--accent-soft)" : "transparent" }}>
                  选择
                </button>
              </div>
            </div>

            {/* 书架范围（Phase 2-3）：当前筛选状态一目了然，克制、可清除 */}
            <div className="flex items-center gap-1.5 mb-4 flex-wrap shrink-0"
              style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.04em", color: "var(--ink-2)" }}>
              <span>共 {gridTotal} 册</span>
              <span style={{ opacity: 0.4 }}>·</span>
              <button onClick={() => setActiveWorkType(null)} title="全部类型"
                className="px-2 py-0.5 rounded-full"
                style={{ color: activeWorkType === null ? "var(--accent)" : "var(--ink-2)",
                  backgroundColor: activeWorkType === null ? "var(--accent-soft)" : "transparent" }}>全部类型</button>
              {workTypeOptions.map((t) => (
                <button key={t} onClick={() => setActiveWorkType(activeWorkType === t ? null : t)}
                  className="px-2 py-0.5 rounded-full"
                  style={{ color: activeWorkType === t ? "var(--accent)" : "var(--ink-2)",
                    backgroundColor: activeWorkType === t ? "var(--accent-soft)" : "transparent" }}>
                  {WORK_TYPE_LABEL[t]}
                </button>
              ))}
              {activeTag && (
                <button onClick={() => setActiveTag(null)} title="清除标签"
                  className="px-2 py-0.5 rounded-full"
                  style={{ color: "var(--accent)", backgroundColor: "var(--accent-soft)" }}># {activeTag} ✕</button>
              )}
              {activeGroup !== "all" && (
                <button onClick={() => setActiveGroup("all")} title="清除分组"
                  className="px-2 py-0.5 rounded-full"
                  style={{ color: "var(--accent)", backgroundColor: "var(--accent-soft)" }}>
                  {({ all: "全部", note: "笔记", image: "图片", external: "外部收藏" })[activeGroup] || activeGroup} ✕
                </button>
              )}
              {libQuery.trim() && (
                <button onClick={() => setLibQuery("")} title="清除搜索条件"
                  className="px-2 py-0.5 rounded-full"
                  style={{ color: "var(--accent)", backgroundColor: "var(--accent-soft)" }}>「{libQuery.trim()}」 ✕</button>
              )}
              {(activeTag || activeGroup !== "all" || activeWorkType || libQuery.trim()) && (
                <button onClick={() => { setActiveTag(null); setActiveGroup("all"); setActiveWorkType(null); setLibQuery(""); }}
                  title="清除筛选" className="px-1" style={{ color: "var(--text-secondary)" }}>清除筛选</button>
              )}
            </div>

            {gridLoading ? (
              <div className="flex-1 min-h-0 flex items-center justify-center text-sm"
                style={{ color: "var(--text-secondary)" }}>加载中…</div>
            ) : libFiltered.length === 0 ? (
              <div className="flex-1 min-h-0 flex items-center justify-center text-sm"
                style={{ color: "var(--text-secondary)" }}>
                {gridItems.length === 0 ? "暂无资料，在左侧「导入」添加吧。" : "没有匹配的存储内容。"}
              </div>
            ) : libView === "list" ? (
              <>
              {/* 主从视图（ADR 0029/0030；Phase 2-6 移动端适配）：桌面左右主从，窄屏列表全宽 + 全屏详情 */}
              <div className="flex-1 min-h-0 flex flex-col lg:flex-row gap-4">
                <div className="w-full lg:w-[300px] shrink-0 min-h-0 flex flex-col border overflow-hidden"
                  style={{ backgroundColor: "var(--surface-1)", borderColor: "var(--panel-border)", borderRadius: "var(--radius-surface)" }}>
                  <StatusGroupedList
                    className="flex-1 min-h-0 overflow-y-auto p-2"
                    items={libFiltered} statusOf={statusMap}
                    selectedId={detailBrowseId} onSelect={setDetailBrowseId}
                  />
                </div>
                <div className="flex-1 min-h-0 border overflow-hidden hidden lg:flex"
                  style={{ backgroundColor: "var(--surface-1)", borderColor: "var(--panel-border)", borderRadius: "var(--radius-surface)" }}>
                  <div className="h-full overflow-y-auto p-5">
                    <ItemDetailPanel itemId={detailBrowseId} onOpenReview={(it) => setReviewItem(it)} />
                  </div>
                </div>
              </div>
              {/* Phase 2-6（ADR 0073）：移动端全屏 Detail Scene（<1024，选中行时）——
                  复用 ItemDetailPanel 与 detailBrowseId，不新增第二套详情系统。
                  JS 视口守卫与 CSS lg:hidden 双保险（jsdom 无 CSS 时守卫生效）。 */}
              {detailBrowseId != null && window.innerWidth < 1024 && (
                <div className="fixed inset-0 z-50 overflow-y-auto lg:hidden"
                  style={{ backgroundColor: "var(--bg)" }}>
                  <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0"
                    style={{ backgroundColor: "var(--bg)", borderColor: "var(--panel-border)" }}>
                    <span className="tsm-heading text-sm" style={{ color: "var(--text)" }}>作品档案</span>
                    <button onClick={() => setDetailBrowseId(null)} title="关闭"
                      className="px-2 py-1 text-sm" style={{ color: "var(--text-secondary)", borderRadius: "var(--radius-control)" }}>✕</button>
                  </div>
                  <div className="p-5">
                    <ItemDetailPanel itemId={detailBrowseId} onOpenReview={(it) => setReviewItem(it)} />
                  </div>
                </div>
              )}
              </>
            ) : libView === "shelf" ? (
              <div className="flex-1 min-h-0 overflow-y-auto">
                <Bookshelf items={libFiltered} coverOf={cardCover} onOpenItem={(it) => openItemDetail(it)}
                  selectMode={selectMode} selectedIds={selectedIds} onToggleSelect={toggleSelect}
                  onContextMenu={openCtxMenu} />
              </div>
            ) : (
              <div className="flex-1 min-h-0 overflow-y-auto">
              {/* 视觉方向定案（ADR 0060）：仅保留编目抽屉（经典档案卡，ADR 0054/0056） */}
              <div className="grid" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(var(--d-grid-min), 1fr))`, gap: "var(--d-card-gap)" }}>
                {libFiltered.map((it) => {
                  const selected = selectedIds.has(it.id);
                  return (
                  <CoverAmbient key={it.id} src={cardCover(it)} alphaFactor={0.6}>
                  <ArchiveCard
                    it={it} cover={cardCover(it)}
                    onOpen={() => { if (it.source !== "local") openItemDetail(it); }}
                    onContextMenu={(e) => openCtxMenu(e, it)}
                    onReview={() => setReviewItem(it)}
                    onDelete={async () => { if (window.confirm(`确认删除「${it.title}」？`)) { try { await deleteItem(it.id); toast.success("已删除"); refresh(); } catch (err) { toast.error(err.message); } } }}
                    selected={selected} selectMode={selectMode}
                    onToggleSelect={() => toggleSelect(it.id)}
                    onReplaceCover={() => { coverTargetRef.current = it.id; coverFileRef.current?.click(); }} />
                  </CoverAmbient>
                  );
                })}
              </div>
              </div>
            )}
          </div>
        )}

        {/* 批量操作栏：选择模式下固定底部居中 */}
        {selectMode && (
          <div className="fixed bottom-5 left-1/2 -translate-x-1/2 z-40 flex items-center gap-3 px-4 py-2"
            data-testid="batch-bar"
            style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)",
              borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-md)" }}>
            <span className="text-sm" style={{ color: "var(--text)" }}>已选中 {selectedIds.size} 项</span>
            <button onClick={() => setTagEdit({ itemIds: [...selectedIds], title: `为 ${selectedIds.size} 项打标签` })}
              disabled={selectedIds.size === 0}
              className="px-3 py-1.5 rounded-xl text-xs font-medium disabled:opacity-40"
              style={{ backgroundColor: "var(--accent)", color: "#fff" }}>打标签</button>
            <button onClick={handleBatchDelete} disabled={selectedIds.size === 0}
              className="px-3 py-1.5 rounded-xl text-xs disabled:opacity-40"
              style={{ backgroundColor: "var(--accent-soft)", color: "var(--danger)" }}>删除</button>
            <button onClick={exitSelectMode}
              className="px-3 py-1.5 rounded-xl text-xs"
              style={{ color: "var(--text-secondary)" }}>取消</button>
          </div>
        )}

        {section === "ask" && !hasContent ? (
          /* 神殿首页（ADR 0039）：空态 = 空间隐喻的"参拜"入口 */
          <HomeShrine representativeCover={representativeCover} recentItems={recentExternalItems}
            recentReviews={recentReviews} onOpenWork={(it) => openItemDetail(it)}
            collectionCount={statsLoaded ? groupCounts.external : null}
            reviewCount={reviewCount}
            newestCollectionAt={newestCollectionAt} newestReviewAt={newestReviewAt}>
            {askSearchBar}
          </HomeShrine>
        ) : section === "ask" ? (
          <div className="max-w-3xl mx-auto flex flex-col h-full">
            {/* 搜索栏（有内容时置顶） */}
            <div className="flex justify-center transition-all duration-500 ease-in-out"
              style={{ alignItems: "flex-start", paddingTop: "1rem", paddingBottom: "1rem" }}>
              {askSearchBar}
            </div>

            {askError && (
              <div className="ask-error" aria-live="polite">{askError}</div>
            )}
            {/* Phase 7-1：文献式检索台——我的检索 / 外部检索 / 来源脚注 / 综合回答 */}
            {mySearch && mySearch.q && (
              <section className="ask-section">
                <div className="ask-section-head">
                  <h3 className="wd-chapter-title">我的检索</h3>
                  <span className="wd-meta" style={{ fontSize: 10, letterSpacing: "0.2em" }}>「{mySearch.q}」</span>
                </div>
                <div className="ask-section-rule" />
                {mySearch.loading ? (
                  <div className="ask-hint">正在翻找馆藏…</div>
                ) : (mySearch.works.length + mySearch.reviews.length + mySearch.memories.length) === 0 ? (
                  <div className="ask-hint">没有匹配的我的记录</div>
                ) : (
                  <div className="ask-list">
                    {mySearch.works.map((w) => (
                      <button key={"w" + w.id} onClick={() => openItemDetail(w)} className="ask-row">
                        <span className="ask-type">作品</span>
                        <span className="ask-row-title">{w.title}</span>
                      </button>
                    ))}
                    {mySearch.reviews.map((r) => (
                      <button key={"r" + r.id} onClick={() => setOpenMem({ itemId: r.item_id, sourceRef: r.id, memory: null })} className="ask-row">
                        <span className="ask-type">书评</span>
                        <span className="ask-row-title">{r.title || r.content}</span>
                        <span className="ask-row-meta">{r.item_title}</span>
                      </button>
                    ))}
                    {mySearch.memories.map((m) => (
                      <button key={"m" + m.id} onClick={() => setOpenMem({ itemId: m.item_id, sourceRef: m.source_ref, memory: m })} className="ask-row">
                        <span className="ask-type">记忆</span>
                        <span className="ask-row-title">{m.summary}</span>
                        <span className="ask-row-meta">{m.item_title}</span>
                      </button>
                    ))}
                  </div>
                )}
              </section>
            )}
            {answerOpen && (answer || sources.length > 0 || fedResults.length > 0) ? (
              <div className="flex-1 overflow-y-auto space-y-6">
                {fedResults.length > 0 && (
                  <section className="ask-section">
                    <div className="ask-section-head">
                      <h3 className="wd-chapter-title">外部检索</h3>
                    </div>
                    <div className="ask-section-rule" />
                    <div className="ask-list">
                      {fedResults.slice(0, 4).map((r, i) => (
                        <div key={i} className="ask-external-row">
                          <button onClick={() => openExternalDetail(r)} className="ask-external-main">
                            <span className="ask-type">{r.source}</span>
                            <span className="ask-row-title">{r.title}</span>
                          </button>
                          <div className="flex items-center gap-1 shrink-0">
                            <button onClick={() => openExternalDetail(r)} className="ask-action">详情</button>
                            <button onClick={() => handleSave(r)} className="ask-action accent">收藏</button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
                {sources.length > 0 && (
                  <section className="ask-section">
                    <div className="ask-section-head">
                      <h3 className="wd-chapter-title">来源</h3>
                    </div>
                    <div className="ask-section-rule" />
                    <div className="ask-sources">
                      {sources.map((s, i) => (
                        <div key={i} className="ask-source-row">
                          <span className="ask-source-label">{sourceTypeLabel(s)}</span>
                          <span className="ask-source-title">{s.item_title}</span>
                          <span className="ask-source-score">{s.score.toFixed(2)}</span>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
                {answer && (
                  <section className="ask-section">
                    <div className="ask-section-head">
                      <h3 className="wd-chapter-title">综合回答</h3>
                    </div>
                    <div className="ask-section-rule" />
                    <div className="ask-answer">{answer}</div>
                  </section>
                )}
              </div>
            ) : null}
          </div>
        ) : null}

        {section === "inspector" && (
          <div className="max-w-3xl mx-auto mt-6">
            <PageHeader room="分析" path="INSPECTOR" />
            <InspectorPanel />
          </div>
        )}

        {section === "characters" && (
          <div className="max-w-4xl mx-auto mt-6">
            <PageHeader room="人物档案" path="ARCHIVE">
              <div className="flex items-center gap-2">
                <button onClick={() => { setVoiceFocus(null); setSection("voice"); }}
                  className="px-3 py-1.5 rounded-xl text-xs"
                  style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
                  声优关系
                </button>
                <button onClick={() => setCharRefreshKey((k) => k + 1)}
                  className="px-3 py-1.5 rounded-xl text-xs"
                  style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>刷新</button>
              </div>
            </PageHeader>
            <CharacterWall refreshKey={charRefreshKey} onOpenWork={openWorkDetail}
              onOpenVoice={(a) => { setVoiceFocus(a); setSection("voice"); }} />
          </div>
        )}

        {section === "voice" && (
          <div className="max-w-5xl mx-auto mt-6">
            <PageHeader room="声优关系图谱" path="人物档案 ▸ 声优图谱" />
            <VoiceGraphView focusActor={voiceFocus}
              onOpenWork={(itemId) => { setSection("library"); setLibView("list"); setDetailBrowseId(itemId); }} />
          </div>
        )}

        {section === "summary" && (
          <div className="max-w-4xl mx-auto mt-6">
            <PageHeader room="时光轴" path="TIMELINE · 年度总结" />
            <YearlySummary />
          </div>
        )}

        {section === "memories" && (
          <div className="max-w-3xl mx-auto mt-6">
            <PageHeader room="记忆回廊" path="GALLERY" />
            <MemoryGallery showHeader={false}
              onOpenWork={(itemId) => { setSection("library"); setLibView("list"); setDetailBrowseId(itemId); }} />
          </div>
        )}

        {section === "settings" && (
          <div className="max-w-2xl mx-auto mt-6">
            <PageHeader room="管理室" path="OFFICE" />
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

            {/* 外观：大风格主题 + 主题 + 有约束的自定义（强调色/密度/圆角） */}
            {settingsTab === "appearance" && (
              <div className="space-y-4">
                <div className="desk-askbar p-5">
                  <h3 className="text-sm font-medium mb-1">应用外壳</h3>
                  <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
                    图书馆的空间结构（经典三栏 / C 非对称档案室）
                  </p>
                  <ShellSwitcher value={shellConcept} onChange={changeShellConcept} />
                </div>

                <div className="desk-askbar p-5">
                  <h3 className="text-sm font-medium mb-1">大风格主题</h3>
                  <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
                    整体视觉语言（版式/材质/信息呈现）。当前注册「编目抽屉·索书卡」，
                    后续可在此与其他大风格主题切换。
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {STYLE_THEMES.map((s) => (
                      <button key={s.key} onClick={() => setStyleTheme(s.key)}
                        className="px-3 py-1.5 rounded-xl text-sm"
                        style={{ backgroundColor: styleTheme === s.key ? "var(--accent)" : "var(--accent-soft)",
                          color: styleTheme === s.key ? "#fff" : "var(--accent)" }}>
                        {s.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="desk-askbar p-5">
                  <h3 className="text-sm font-medium mb-1">主题</h3>
                  <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
                    三套主题共享同一套间距/圆角/阴影/密度规则，只切换色彩。
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {THEMES.map((t) => (
                      <button key={t.key} onClick={() => setTheme(t.key)}
                        className="px-3 py-1.5 rounded-xl text-sm"
                        style={{ backgroundColor: theme === t.key ? "var(--accent)" : "var(--accent-soft)",
                          color: theme === t.key ? "#fff" : "var(--accent)" }}>
                        {t.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="desk-askbar p-5">
                  <h3 className="text-sm font-medium mb-3">自定义</h3>

                  <label className="flex flex-col gap-2 mb-4">
                    <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                      强调色色相（{ACCENT_HUE_RANGE.min}° ~ +{ACCENT_HUE_RANGE.max}°）
                    </span>
                    <input type="range" min={ACCENT_HUE_RANGE.min} max={ACCENT_HUE_RANGE.max} step="1"
                      value={custom.accentHue}
                      onChange={(e) => updateCustom({ accentHue: Number(e.target.value) })}
                      className="w-full" />
                    <span className="text-xs" style={{ color: "var(--accent)" }}>
                      预览：{custom.accentHue > 0 ? `+${custom.accentHue}°` : `${custom.accentHue}°`}</span>
                  </label>

                  <div className="mb-4">
                    <span className="text-xs block mb-2" style={{ color: "var(--text-secondary)" }}>信息密度</span>
                    <div className="flex gap-2">
                      {["comfortable", "compact"].map((d) => (
                        <button key={d} onClick={() => updateCustom({ density: d })}
                          className="px-3 py-1.5 rounded-xl text-sm"
                          style={{ backgroundColor: custom.density === d ? "var(--accent)" : "var(--accent-soft)",
                            color: custom.density === d ? "#fff" : "var(--accent)" }}>
                          {d === "comfortable" ? "舒适" : "紧凑"}
                        </button>
                      ))}
                    </div>
                  </div>

                  <label className="flex flex-col gap-2">
                    <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                      圆角大小（{RADIUS_RANGE.min}~{RADIUS_RANGE.max}px）
                    </span>
                    <input type="range" min={RADIUS_RANGE.min} max={RADIUS_RANGE.max} step="1"
                      value={custom.radius}
                      onChange={(e) => updateCustom({ radius: Number(e.target.value) })}
                      className="w-full" />
                    <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                      当前 {custom.radius}px</span>
                  </label>

                  <p className="text-xs mt-3" style={{ color: "var(--text-secondary)" }}>
                    自定义仅在预设范围内微调，避免调出不协调效果；实时生效并保存在本地。
                  </p>
                </div>

                {/* 文字涂鸦（自定义位置） */}
                <div className="desk-askbar p-5">
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

            {/* 模型 Provider */}
            {settingsTab === "model" && (
              <ProviderSettings />
            )}

            {/* Bangumi 连接 + 批量导入 */}
            {settingsTab === "bangumi" && (
              <BangumiPanel />
            )}

            {/* 导航栏：排序（除 settings 外的按键） */}
            {settingsTab === "nav" && (
              <div className="desk-askbar rounded-2xl p-5"
                style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)" }}>
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
                style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)" }}>
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
                      <li key={c.name} className="py-2 text-sm">
                        <div className="flex items-center justify-between">
                          <div>
                            <span className="font-medium">{c.display_name}</span>
                            <span className="ml-2 text-xs px-1.5 py-0.5 rounded-full"
                              style={{ backgroundColor: "var(--tag-bg)", color: "var(--tag-text)" }}>{c.name}</span>
                            <span className="ml-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                              {c.capabilities.join(", ")}</span>
                            <span className={`ml-2 text-xs ${c.enabled ? "" : "opacity-50"}`}
                              style={{ color: c.enabled ? "var(--ok)" : "var(--text-secondary)" }}>
                              {c.enabled ? "已启用" : "已停用"}</span>
                            {c.proxy_url && (
                              <span className="ml-2 text-xs px-1.5 py-0.5 rounded-full"
                                style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
                                代理
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <button onClick={() => openProxyEditor(c)}
                              className="text-xs" style={{ color: "var(--text-secondary)" }}>
                              {c.proxy_url ? "改代理" : "设代理"}
                            </button>
                            <button onClick={() => handleDeleteConnector(c.name)}
                              className="text-xs" style={{ color: "var(--danger)" }}>删除</button>
                          </div>
                        </div>
                        {proxyEditName === c.name && (
                          <div className="mt-2 pl-2 flex flex-col gap-1.5">
                            <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
                              出站代理（留空=直连），如 http://127.0.0.1:7890</div>
                            <div className="flex items-center gap-2">
                              <input placeholder="http://host:port" value={proxyDraft}
                                onChange={(e) => { setProxyDraft(e.target.value); setProxyTestMsg(null); }}
                                className="tsm-input border rounded px-2 py-1.5 text-xs flex-1" />
                              <button onClick={() => handleTestProxy(c.name)} disabled={proxyTesting}
                                className="px-2 py-1 rounded-lg text-xs disabled:opacity-40"
                                style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
                                {proxyTesting ? "测试中…" : "测试连接"}
                              </button>
                              <button onClick={() => handleSaveProxy(c.name)}
                                className="px-2 py-1 rounded-lg text-xs font-medium"
                                style={{ backgroundColor: "var(--accent)", color: "#fff" }}>保存</button>
                              <button onClick={() => setProxyEditName(null)}
                                className="px-2 py-1 rounded-lg text-xs"
                                style={{ color: "var(--text-secondary)" }}>取消</button>
                            </div>
                            {proxyTestMsg && (
                              <p className="text-xs" style={{ color: proxyTestMsg.ok ? "var(--ok)" : "var(--danger)" }}>
                                {proxyTestMsg.message}
                              </p>
                            )}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {/* 插件（ADR 0027：本地文件信任模型 + 风险提示） */}
            {settingsTab === "plugins" && (
              <div className="space-y-4">
                {/* 一次性风险确认（首次检测到插件时显示） */}
                {pluginsData.notice_needed && (
                  <div className="rounded-2xl p-4"
                    style={{ backgroundColor: "rgba(248,113,113,0.14)", border: "1px solid var(--danger)" }}>
                    <div className="text-sm font-medium mb-1" style={{ color: "var(--danger)" }}>
                      ⚠️ 检测到第三方插件
                    </div>
                    <p className="text-xs leading-relaxed mb-3" style={{ color: "var(--text)" }}>
                      插件是放在 <code>{pluginsData.plugin_dir}</code> 目录下的第三方 Python
                      代码，运行时拥有与 Tsumugi 后端<b>完全相同的系统权限</b>（可读写你的
                      资料库、访问网络）。Tsumugi 不做沙盒隔离，也不会联网下载运行插件——
                      请仅安装你信任来源的插件，安装前建议审查其代码。
                    </p>
                    <button onClick={handleAcknowledgePlugins}
                      className="px-3 py-1.5 rounded-xl text-xs font-medium"
                      style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
                      我已了解，不再提示
                    </button>
                  </div>
                )}

                {/* 插件列表 */}
                <div className="desk-askbar rounded-2xl p-5"
                  style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)" }}>
                  <div className="flex items-center justify-between mb-1">
                    <h3 className="text-sm font-medium">插件管理</h3>
                    <span className="text-[11px] px-2 py-0.5 rounded-full"
                      style={{ backgroundColor: "var(--tag-bg)", color: "var(--tag-text)" }}>
                      {pluginsData.plugins.length} 已加载
                    </span>
                  </div>
                  <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
                    把插件子目录放进 <code>{pluginsData.plugin_dir || "plugins/"}</code> 并重启应用生效
                    （详见项目 plugins/README.md）。
                  </p>
                  {pluginsData.plugins.length === 0 ? (
                    <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                      暂无已加载插件。
                    </p>
                  ) : (
                    <ul className="divide-y">
                      {pluginsData.plugins.map((p) => (
                        <li key={p.name} className="py-2.5 text-sm">
                          <div className="flex items-center gap-2">
                            <span className="font-medium">{p.display_name}</span>
                            <span className="text-xs px-1.5 py-0.5 rounded-full"
                              style={{ backgroundColor: "var(--tag-bg)", color: "var(--tag-text)" }}>
                              {p.name}
                            </span>
                            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                              v{p.version} · {p.capabilities.join(", ")}
                            </span>
                          </div>
                          <div className="text-[11px] mt-1" style={{ color: "var(--danger)" }}>
                            ⚠️ 第三方插件拥有与本应用相同的系统权限，请仅安装你信任的来源。
                          </div>
                          <div className="text-[11px] mt-0.5" style={{ color: "var(--text-secondary)" }}>
                            来源：{p.path}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {/* 加载失败（不阻塞应用，可在此排查） */}
                {pluginsData.failures.length > 0 && (
                  <div className="desk-askbar rounded-2xl p-5"
                    style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)" }}>
                    <h3 className="text-sm font-medium mb-2">加载失败的插件</h3>
                    <ul className="space-y-1.5 text-xs">
                      {pluginsData.failures.map((f, i) => (
                        <li key={i} style={{ color: "var(--danger)" }}>
                          <b>{f.dir}</b>：{f.error}
                        </li>
                      ))}
                    </ul>
                    <p className="text-[11px] mt-2" style={{ color: "var(--text-secondary)" }}>
                      单个插件失败会被跳过，不影响应用启动；错误详情也会写入启动日志（[plugin] 前缀）。
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* 备份（ADR 0038：导出/导入图书馆数据） */}
            {settingsTab === "backup" && (
              <div className="space-y-4">
                <div className="desk-askbar rounded-2xl p-5"
                  style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)" }}>
                  <h3 className="text-sm font-medium mb-2">导出图书馆数据</h3>
                  <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
                    生成一个 JSON 备份文件（含笔记 / 书评 / 条目元数据（含已下载的百科资料）/
                    标签 / 数据源配置（不含明文密钥））。向量库不导出，导入时从内容重建。
                  </p>
                  <button onClick={handleExportBackup} disabled={backupState.exporting}
                    className="px-4 py-2 rounded-xl text-xs font-medium disabled:opacity-40"
                    style={{ backgroundColor: "var(--accent)", color: "#fff" }}>
                    {backupState.exporting ? "正在生成…" : "导出图书馆数据"}
                  </button>
                </div>

                <div className="desk-askbar rounded-2xl p-5"
                  style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)" }}>
                  <h3 className="text-sm font-medium mb-2">导入图书馆数据</h3>
                  <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>
                    选择导出的 JSON 备份文件导入。幂等合并：外部条目按
                    (数据源, 外部ID)、本地笔记按内容指纹去重，命中则刷新元数据，
                    未命中则新建（并重建向量，首次导入可能需要加载嵌入模型）。
                  </p>
                  <input ref={backupFileRef} type="file" accept=".json,application/json" className="hidden"
                    onChange={(e) => { const f = e.target.files && e.target.files[0]; e.target.value = ""; handleImportFile(f); }} />
                  <button onClick={() => backupFileRef.current?.click()} disabled={backupState.importing}
                    className="px-4 py-2 rounded-xl text-xs font-medium disabled:opacity-40"
                    style={{ backgroundColor: backupState.importing ? "var(--surface-2)" : "var(--accent)",
                      color: backupState.importing ? "var(--text-secondary)" : "#fff" }}>
                    {backupState.importing ? "正在导入…" : "选择备份文件导入"}
                  </button>
                  {backupState.importing && (
                    <div className="mt-3 flex items-center gap-2">
                      <div className="flex-1 h-1.5 rounded-full overflow-hidden"
                        style={{ backgroundColor: "var(--surface-2)" }}>
                        <div className="h-full rounded-full" style={{ width: `${backupState.progress ?? 30}%`, backgroundColor: "var(--accent)" }} />
                      </div>
                      <span className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                        {backupState.progress != null ? `${backupState.progress}%` : "重建向量中…"}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 设置页：右下角固定保存按钮 */}
      {section === "settings" && (
        <>
          {savedToast && (
            <div className="fixed bottom-6 right-6 z-40 px-4 py-2 rounded-full text-sm"
              style={{ backgroundColor: "var(--ok)", color: "#fff", boxShadow: "0 8px 30px rgba(0,0,0,0.25)" }}>
              设置已保存 ✓
            </div>
          )}
          <button onClick={handleSaveSettings}
            className="fixed bottom-6 right-6 z-40 px-5 py-2 rounded-full text-sm font-medium transition-transform hover:scale-105"
            style={{ backgroundColor: "var(--accent)", color: "#fff", boxShadow: "0 8px 30px rgba(0,0,0,0.25)" }}>
            保存设置
          </button>
        </>
      )}

      {/* 更换封面隐藏文件输入 */}
      <input ref={coverFileRef} type="file" accept="image/*" className="hidden"
        onChange={handleCoverFile} />

      {/* 书评工作室 */}
      {reviewItem && (
        <ReviewStudio
          item={reviewItem}
          onClose={() => setReviewItem(null)}
          refreshItems={refresh}
        />
      )}

      {/* 作品详情弹层（Phase 3-1 / ADR 0075：统一 Work Detail——浮层容器 + ItemDetailPanel 内容基底） */}
      {detailView && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ backgroundColor: "rgba(20, 14, 8, 0.5)" }} onClick={() => setDetailView(null)}>
          <div className="desk-askbar p-5 w-full max-w-2xl max-h-[86vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
            style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)", borderRadius: "var(--radius-floating)" }}>
            <div className="flex items-center justify-between mb-4">
              <span className="tsm-heading text-sm" style={{ color: "var(--text)" }}>作品档案</span>
              <button onClick={() => setDetailView(null)} title="关闭" className="text-sm px-2 py-0.5"
                style={{ color: "var(--text-secondary)", borderRadius: "var(--radius-control)" }}>✕</button>
            </div>
            <ItemDetailPanel
              itemId={detailView.itemId}
              externalDetail={detailView.externalDetail}
              refreshKey={detailRefreshKey}
              onSaveDetail={detailView.saved ? null : detailSave}
              onShareDetail={detailView.saved ? () => setShareItem(detailView.itemId) : null}
              onRefreshDetail={detailView.saved ? handleRefreshExternal : null}
              onOpenReview={(it) => { setDetailView(null); setReviewItem(it); }}
            />
          </div>
        </div>
      )}

      {/* 安利卡弹层（分享卡片：封面 + 标题 + 我的评分 + 短评） */}
      {shareItem != null && (
        <ShareCardModal item={{ id: shareItem }} onClose={() => setShareItem(null)} />
      )}

      {/* 右键上下文菜单 */}
      {ctxMenu && (
        <ContextMenu x={ctxMenu.x} y={ctxMenu.y} items={ctxItems()} onClose={() => setCtxMenu(null)} />
      )}

      {/* 标签编辑弹层（单条 / 批量） */}
      {tagEdit && (
        <TagEditModal title={tagEdit.title} onApply={applyTags} onClose={() => setTagEdit(null)} />
      )}

      {/* P6 检索台：个人检索命中的书评/记忆 → 只读弹层 */}
      {openMem && (
        <MemoryReviewModal itemId={openMem.itemId} sourceRef={openMem.sourceRef}
          memory={openMem.memory} onClose={() => setOpenMem(null)} />
      )}

      {/* 快捷键说明 */}
      {showShortcuts && <ShortcutsModal onClose={() => setShowShortcuts(false)} />}

      {/* 命令面板（ADR 0031：Ctrl/Cmd+K） */}
      <CommandPalette open={commandOpen} onClose={() => setCommandOpen(false)} ctx={cmdCtx} />

      {/* 新建分组浮层 */}
      {showGroupModal && (
        <div className="fixed inset-0 z-40 flex items-center justify-center p-4"
          style={{ backgroundColor: "rgba(10,12,20,0.45)" }}
          onClick={() => setShowGroupModal(false)}>
          <div className="desk-askbar rounded-2xl p-5 w-full max-w-sm"
            onClick={(e) => e.stopPropagation()}
            style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)" }}>
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
            style={{ backgroundColor: "var(--panel)", border: "1px solid var(--panel-border)" }}>
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
                <input type="file" accept=".md,.markdown,.txt,.txt.md"
                  onChange={(e) => setFile(e.target.files[0] || null)}
                  className="text-sm" />
                <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                  支持 Markdown（.md / .markdown / .txt.md）与纯文本（.txt）；图片自动存为附件。
                </p>
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

      {/* 移动端：底部房间导航（≤768px 显示，ADR 0066） */}
      <nav className="room-bottom-bar" data-testid="room-bottom-bar">
        {ROOMS_ALL.map((k) => {
          const active = section === k;
          return (
            <button key={k} onClick={() => handleSection(k)}
              className="flex flex-col items-center gap-0.5 py-1.5 px-1"
              style={{ color: active ? "var(--accent)" : "var(--text-secondary)" }}>
              {NAV[k].icon}
              <span className="text-[9px]">{ROOM_META[k].room}</span>
            </button>
          );
        })}
      </nav>
    </div>
      ) : (
        <ShellC shellValue={shellConcept} onShellChange={changeShellConcept} setTheme={setTheme} />
      )}
      {/* 全局 toast（两外壳共用） */}
      <ToastHost />
    </>
  );
}
