// 命令面板动作注册表（ADR 0031）
// 集中的命令定义：内容搜索（条目）+ 动作 + 主题切换 + 标签跳转。
// 后续新功能（声优图谱/年度热力图等）直接在 buildCommands 里追加一个命令项即可，
// 面板的过滤/分组/键盘导航逻辑无需改动。
import { THEMES } from "./themes.js";

// 分组展示顺序（面板按此顺序渲染分组标题）
export const GROUP_ORDER = ["条目", "动作", "主题", "标签"];

function norm(s) {
  return String(s || "").toLowerCase().replace(/\s+/g, "");
}

/** 判断命令是否命中查询：query（去空格小写）是 title 或任一 keyword 的子串。 */
export function matchCommand(cmd, query) {
  const q = norm(query);
  if (!q) return true; // 空查询 = 全部候选（由面板按组截断展示）
  if (norm(cmd.title).includes(q)) return true;
  return (cmd.keywords || []).some((k) => norm(k).includes(q));
}

/**
 * 构建命令列表。ctx 为运行时上下文（由 DesktopView 提供已绑定的可执行回调）：
 * { items, tags, openItem, openImport, section, ask, setTheme, openTag,
 *   shareCard, reviewStudio }
 */
export function buildCommands(ctx) {
  const commands = [];

  // 内容搜索：已收藏条目标题模糊匹配 → 跳转主从详情
  for (const it of ctx.items || []) {
    commands.push({
      id: `item-${it.id}`,
      group: "条目",
      title: it.title,
      keywords: [it.title, it.source || "", it.type],
      icon: it.type === "note" ? "✎" : it.type === "image" ? "🖼" : it.source,
      run: () => ctx.openItem(it),
    });
  }

  // 预定义动作
  commands.push(
    { id: "note-new", group: "动作", title: "新建笔记", icon: "＋", keywords: ["新建笔记", "创建笔记", "笔记", "导入", "添加"],
      run: () => ctx.openImport() },
    { id: "open-library", group: "动作", title: "打开资料库", icon: "▦", keywords: ["资料库", "图书馆", "library", "书架", "收藏"],
      run: () => ctx.section("library") },
    { id: "open-ask", group: "动作", title: "打开问答", icon: "⌕", keywords: ["问答", "搜索", "提问", "ask", "聊天"],
      run: () => ctx.ask() },
    { id: "open-characters", group: "动作", title: "打开角色墙", icon: "◉", keywords: ["角色墙", "角色", "characters", "图鉴"],
      run: () => ctx.section("characters") },
    { id: "open-voice-graph", group: "动作", title: "打开声优图谱", icon: "◉", keywords: ["声优", "图谱", "声优图谱", "voice", "配音", "关系图"],
      run: () => ctx.openVoiceGraph ? ctx.openVoiceGraph() : ctx.section("voice") },
    { id: "open-inspector", group: "动作", title: "打开分析", icon: "▤", keywords: ["分析", "统计", "inspector", "检查器"],
      run: () => ctx.section("inspector") },
    { id: "open-settings", group: "动作", title: "打开设置", icon: "⚙", keywords: ["设置", "settings", "配置"],
      run: () => ctx.section("settings") },
    { id: "review-studio", group: "动作", title: "写读后感", icon: "✎", keywords: ["读后感", "书评", "review", "评论"],
      run: () => ctx.reviewStudio() },
    { id: "share-card", group: "动作", title: "生成安利卡", icon: "♡", keywords: ["安利卡", "分享", "share", "卡片"],
      run: () => ctx.shareCard() },
  );

  // 主题切换：输入"主题"或具体主题名
  for (const t of THEMES) {
    commands.push({
      id: `theme-${t.key}`,
      group: "主题",
      title: `切换主题：${t.label}`,
      keywords: ["主题", "theme", "切换", t.label, t.key],
      icon: "◐",
      run: () => ctx.setTheme(t.key),
    });
  }

  // 标签跳转
  for (const t of ctx.tags || []) {
    const name = typeof t === "string" ? t : t.name;
    if (!name) continue;
    commands.push({
      id: `tag-${name}`,
      group: "标签",
      title: `标签：#${name}`,
      keywords: ["标签", "tag", name],
      icon: "#",
      run: () => ctx.openTag(name),
    });
  }

  return commands;
}
