# Tsumugi（紬）— 个人知识图书馆

本地优先的个人知识管理系统：收藏你喜欢的作品，记录你与这些作品之间发生过的经历，并用 Ask（Personal RAG）在之后回想起来。

> 「紬」意为手工织出的绸缎——把零散的资料与经历，织成属于你自己的知识体系。

与普通作品管理器不同，它不只记录「我看过什么」，而是逐渐记录「我与这部作品发生过什么」。

---

## 特性

**作品库**
- 网格 / 实体书架 / 分组列表三种浏览方式
- 收藏 / 追番状态 / 评分 / 喜欢，均与作品本体分开记录
- Bangumi OAuth 批量导入收藏；单条外部结果一键收藏入库
- JSON 备份导出 / 导入

**作品详情**
- 作品档案（作品信息 / 角色 / 简介）
- 当前状态、态度、评分、书评
- 我的记忆：内联「记录此刻」composer + 作品记忆时间轴
- 相遇纪事：收藏 / 评分 / 状态变化的自动记录
- 往年今日 / 年度总结

**记忆 Memory**
- 直接记忆：在作品详情写下此刻的感想
- 可选情绪（怀念 / 感动 / 开心 …）与附图
- 里程碑：`完成了` / `重新打开`
- 每条记忆带时间（`occurred_at`）并向量化

**Ask（Personal RAG）**
- 我的检索（作品 / 书评 / 记忆）+ 外部检索（Bangumi / 萌娘百科 / VNDB）
- 综合回答基于检索结果 + LLM 流式生成，区分「你的记录中……」与「资料显示……」
- 个人记录权重优先，时间 / 情绪 / 里程碑信号辅助排序

> 这些信号用于检索排序，并不保证模型一定能回答任何个人问题。

---

## Memory → Ask 数据链路

```
作品 → Memory / Review / Note / External
  → metadata（occurred_at / emotion / milestone）
  → vector → retrieval（个人记录优先）
  → rerank → source-aware cap → provenance
  → Ask → 回答
```

- `occurred_at` 参与时间相关检索；`emotion` 参与情绪相关检索；`milestone` 参与里程碑相关检索
- Ask 来源可展示个人记忆的时间 / 情绪 / 里程碑（仅 Memory 来源；字段缺失时不显示）
- 历史向量缺少新 metadata 时仍可正常检索

---

## 快速开始

**Requirements：** Python 3.12 · Node.js 20+

```bash
copy .env.example .env        # Windows（配置环境变量）
python -m venv .venv
.venv\Scripts\activate        # Windows；Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cd frontend && npm install
```

**启动**

```bash
start.bat          # Web：后端(8001) + Vite(5173) + 打开浏览器
start.bat electron # 客户端模式（Electron）
```

手动启动：`.venv\Scripts\python.exe -m uvicorn app.main:app --port 8001`，另开终端 `cd frontend && npm run dev`。

> 首次使用 Ask 会下载 embedding 模型（可通过 `HF_ENDPOINT` 配置镜像）。

---

## 环境变量

以 `.env.example` 为准：

- **必填**：`DEEPSEEK_API_KEY`（仅 Ask 的 AI 回答需要）
- **可选**：`DEEPSEEK_API_BASE`、`DEEPSEEK_MODEL`、`HF_ENDPOINT`、`TSUMUGI_PORT`、`CHROMA_PERSIST_DIRECTORY`、`TOP_K`、`MAX_CONTEXT_LENGTH` 等

不要把你的真实 Key 提交进仓库。

---

## 测试

```bash
.venv\Scripts\python.exe -m pytest -q   # 后端（覆盖率门槛 70%）
cd frontend && npm test                 # Vitest
cd frontend && npm run build
```

最近一次完整验证基线：后端 **484 passed**（覆盖率 86.11%）、前端 **299 passed**、build 通过。

---

## 技术栈

- 后端：FastAPI + SQLAlchemy 2 + Pydantic 2
- 存储：SQLite（元数据）+ Chroma 1.0.x（向量）+ bge-small-zh-v1.5（embedding）
- LLM：DeepSeek API（OpenAI 兼容，SSE 流式）
- 前端：React 18 + Vite 6 + Tailwind CSS 4；客户端：Electron
- 外部数据源：Bangumi / 萌娘百科 / VNDB
- 测试：pytest + Vitest；CI：GitHub Actions

---

## 目录结构

```text
Tsumugi/
├── app/
│   ├── main.py / config.py / database.py / models.py / schemas.py
│   ├── ingest.py / retrieval.py / memories.py / rag.py
│   ├── connectors/          # bangumi / moegirl / vndb
│   └── api/routes.py
├── frontend/
│   └── src/                 # React 界面 + electron/ 客户端
├── tests/                   # pytest
├── requirements.txt
├── .env.example
└── start.bat
```

---

## 已知限制

- Memory 数据量取决于你主动记录——「代码支持」不等于「数据已经充分」
- 历史向量兼容：缺失新 metadata 时仍可正常检索；新写入的记忆会携带新 metadata
- metadata 是辅助排序信号；个人召回质量依赖实际积累的记忆；Ask 不保证能回答所有「为什么 / 什么时候 / 我喜欢什么」类问题

---

## 隐私与安全

- `.env` 不应提交，仓库只包含 `.env.example` 占位模板
- 本地数据库、向量库、上传与缩略图目录均属本地数据，已在 `.gitignore` 排除
- 你的个人 Memory 属于个人数据，请谨慎处理；本项目不做「绝对安全 / 完全隐私」的承诺

---

## License

当前仓库**未声明许可证**。
