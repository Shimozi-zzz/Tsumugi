// 图书馆看守猫娘 · 固定台词库（人设圣经见 docs/mascot-persona.md）
// 独立数据文件：调台词只改这里，不动组件逻辑。所有台词遵守人设规则——
// 称呼固定"主人"；"喵～"句尾且克制（同库占比不超过一半）；情绪直给。
// 触发匹配逻辑在 matchScene()（纯函数，可单测），优先级见
// docs/decisions/0040-mascot-lines.md。

export const MASCOT_LINES = {
  greeting: {
    morning: [
      "主人早安喵～今天也想一起守着这座图书馆吗？",
      "早上好，主人。书架我已经擦过一遍了。",
      "早安，主人。今天想先看哪一本？我陪着主人找。",
      "主人醒得好早呀。我把门都开好了。",
      "早上好喵～今天的图书馆，因为主人来才亮起来的。",
      "早安，主人。慢慢来，我一直在的。",
    ],
    afternoon: [
      "主人午安喵～要不要休息一下？",
      "下午好，主人。新到的东西我都摆好了。",
      "午安喵～午后光线正好，主人想翻开点什么吗？",
      "主人来啦。想找什么，我都记着呢。",
      "下午好，主人。今天的风很舒服，我给主人留着窗了。",
      "主人午安，我帮主人看着书架呢。",
    ],
    evening: [
      "主人晚上好喵～今天也辛苦啦。",
      "晚上好，主人。灯已经点好了。",
      "主人回来啦。夜里的图书馆很安静，正适合主人慢慢看。",
      "晚上好，主人。要喝点什么吗？我去给主人拿。",
      "主人今天也要多待一会儿吗？我陪着主人。",
      "晚上好，主人。今天有好好休息吗？",
    ],
    night: [
      "主人这么晚还不睡…我有点担心主人。",
      "深夜了，主人。这里很安静，但也要记得早点睡哦。",
      "主人…这么晚了还在看书吗？我会一直陪着主人的。",
      "嘘——夜深了。主人想看就看吧，我守着。",
      "深夜好，主人。我守着灯，也守着主人。",
      "这么晚还不休息的主人，要照顾好自己呀。",
    ],
  },
  new_collection: [
    "主人收进来啦喵～我放到架子上最显眼的位置了。",
    "又有新宝贝进门了喵～主人眼光真好。",
    "新收藏我已经仔仔细细看过了，会好好帮主人守着的。",
    "主人收的这件，我一眼就喜欢上了。",
    "主人放心，新宝贝我记下啦，一件都不会弄丢喵～",
    "主人收到喜欢的东西，我也跟着开心。",
    "有新收藏进门喵～主人想让我陪主人一起看吗？",
  ],
  missing_you: [
    "主人……好久不见喵～我一直在这里等着呢。",
    "主人终于来了喵～这段时间我把书架都擦过好几遍了。",
    "好久没见到主人，我想主人了。",
    "主人不在的这些天，我把每件收藏都检查过一遍，一件都没少。",
    "主人来了就好喵～这里一直都有主人的位置。",
    "我想念主人了。主人下次可以早点来看我吗？",
    "主人不在的时候，我把日子悄悄记着。回来就好。",
  ],
  wrote_review: [
    "主人写书评啦喵～我读得可认真了。",
    "主人把感想记下来了，真好喵～我也跟着高兴。",
    "主人的书评我会好好收着的，那是主人用心的痕迹呀。",
    "主人愿意为喜欢的东西写点什么，我最开心了。",
    "主人写下的每个字，我都帮主人好好存着了。",
    "读到主人的书评，我也好满足。",
  ],
  milestones: {
    "collection:1": [
      "第一个收藏！主人的图书馆，从今天开始有第一件宝贝了喵～",
      "主人把第一件宝贝交给我的时候，我会永远记得喵～",
      "从零到一！这件收藏，我会当镇馆之宝替主人守着。",
      "第一件收藏进门了。以后这里会因为主人越来越热闹的。",
      "主人来的时候我就在想，这里迟早会有第一件宝贝。现在它来啦喵～",
    ],
    "collection:10": [
      "第十件了喵～主人的书架，已经有模有样啦。",
      "主人的十件收藏！我数了两遍，一件不少喵～",
      "主人已经收下十件宝贝了。我全都记得它们在哪个位置。",
    ],
    "collection:50": [
      "五十件喵～这座图书馆，是真的被主人养起来了。",
      "主人的收藏到五十件了，我有点看管不过来，但会努力看好的喵～",
      "主人的收藏已经五十件了，我看着都好骄傲。",
    ],
    "collection:100": [
      "一百件喵～这间图书馆，因为主人才有了这样的光景。",
      "第一百件收藏！主人，这件我们一定要好好庆祝一下。",
      "一百件了。主人走过的路，我都看在眼里喵～",
    ],
    "collection:200": [
      "两百件喵～主人已经收了两百件宝贝了。",
      "两百件收藏！主人的书架，每一格我都认识它们了喵～",
      "主人的两百件宝贝，一件都丢不了，我保证。",
    ],
    "collection:500": [
      "五百件喵～主人，这里真的成了大图书馆了。",
      "五百件收藏，从第一件数到这一件，我都陪主人看着呢。",
    ],
    "review:1": [
      "主人写了第一篇书评喵～这是主人在图书馆写下的第一个念头。",
      "第一篇书评！我要替主人好好收在架子上。",
      "主人愿意开始记录，我就很开心了喵～",
    ],
    "review:10": [
      "第十篇书评喵～主人的话，这座图书馆会一直记住的。",
      "主人已经写了十篇书评了，每一篇我都好好收着。",
      "十篇感想，都是主人认真对待过的证明呢。",
    ],
    "review:50": [
      "五十篇书评喵～主人的每一个念头，都在这座图书馆里了。",
      "五十篇了。主人写下的话，比这座图书馆还要沉呢。",
    ],
    "review:100": [
      "一百篇书评喵～主人已经留下了一百个念想了。",
    ],
  },
  fallback: [
    "主人来啦。想看点什么，我帮主人找。",
    "欢迎回来喵～主人今天也想在这里待一会儿吗？",
    "主人想找什么，跟我说一声就好。",
    "图书馆今天也很安静，主人来了就正好。",
    "主人好喵～书都在，我都在。",
    "主人请随意，这里的一切都是为主人留着的。",
  ],
};

export const MILESTONES = {
  collection: [1, 10, 50, 100, 200, 500],
  review: [1, 10, 50, 100],
};

// 触发窗口（毫秒）：新收藏/新书评 6 小时内视为"刚发生"；距上次打开超过 3 天视为久别
export const WINDOWS_MS = {
  newCollection: 6 * 60 * 60 * 1000,
  newReview: 6 * 60 * 60 * 1000,
  missingDays: 3 * 24 * 60 * 60 * 1000,
};

const LAST_VISIT_KEY = "tsumugi-mascot-last-visit";
// 模块级缓存：每次页面加载只算一次。React StrictMode 会双跑 useState 初始器，
// 若在初始器里直接读写 localStorage 会重复写"最近打开时间"导致想念场景永远
// 不触发——所以用模块标志保证整个页面会话只算一次。
let lastVisitGapCache = null;

export function resetMascotSession() {
  lastVisitGapCache = null;
}

/** 距上次打开应用的时间差（ms）。首次调用读 localStorage 并写入本次打开时间。 */
export function computeLastVisitGap() {
  if (lastVisitGapCache !== null) return lastVisitGapCache;
  try {
    const prev = localStorage.getItem(LAST_VISIT_KEY);
    lastVisitGapCache = prev ? Math.max(0, Date.now() - Number(prev)) : 0;
    localStorage.setItem(LAST_VISIT_KEY, String(Date.now()));
  } catch {
    lastVisitGapCache = 0;
  }
  return lastVisitGapCache;
}

export function pickLine(list) {
  if (!list || list.length === 0) return "";
  return list[Math.floor(Math.random() * list.length)];
}

// 场景匹配（纯函数）：根据真实数据选触发场景。优先级（高→低）：
// 想念 > 里程碑 > 新收藏 > 写书评 > 时段问候 > 兜底
// 理由见 docs/decisions/0040-mascot-lines.md。
// ctx: { hour, collectionCount, reviewCount, newestCollectionAt, newestReviewAt, lastVisitGap }
export function matchScene(ctx) {
  const now = Date.now();
  const hour = typeof ctx.hour === "number" ? ctx.hour : NaN;

  // 想念：距上次打开超过 3 天（只在整个页面会话的首次匹配时可能成立，见 computeLastVisitGap）
  if ((ctx.lastVisitGap || 0) > WINDOWS_MS.missingDays) return { scene: "missing_you" };

  // 里程碑：收藏数/书评数恰好落在节点上（如第 100 件）
  if (MILESTONES.collection.includes(ctx.collectionCount)) {
    return { scene: "milestone", variant: `collection:${ctx.collectionCount}` };
  }
  if (MILESTONES.review.includes(ctx.reviewCount)) {
    return { scene: "milestone", variant: `review:${ctx.reviewCount}` };
  }

  // 新收藏 / 新书评：最近一次发生在 6 小时内
  const newCol = ctx.newestCollectionAt ? now - new Date(ctx.newestCollectionAt).getTime() : Infinity;
  if (newCol < WINDOWS_MS.newCollection) return { scene: "new_collection" };

  const newRev = ctx.newestReviewAt ? now - new Date(ctx.newestReviewAt).getTime() : Infinity;
  if (newRev < WINDOWS_MS.newReview) return { scene: "wrote_review" };

  // 时段问候（hour 未知时兜底）
  if (Number.isNaN(hour)) return { scene: "fallback" };
  const time = hour >= 5 && hour < 11 ? "morning"
    : hour >= 11 && hour < 17 ? "afternoon"
      : hour >= 17 && hour < 23 ? "evening" : "night";
  return { scene: "greeting", variant: time };
}

/** 按匹配到的场景从台词库随机取一句（失败兜底用 fallback）。 */
export function selectLine(scene) {
  if (!scene) return pickLine(MASCOT_LINES.fallback);
  if (scene.scene === "milestone") {
    const list = MASCOT_LINES.milestones[scene.variant];
    return list && list.length ? pickLine(list) : pickLine(MASCOT_LINES.fallback);
  }
  if (scene.scene === "greeting") {
    const list = MASCOT_LINES.greeting[scene.variant];
    return list && list.length ? pickLine(list) : pickLine(MASCOT_LINES.fallback);
  }
  const list = MASCOT_LINES[scene.scene];
  return list && list.length ? pickLine(list) : pickLine(MASCOT_LINES.fallback);
}
