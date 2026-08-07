# 0013 · LLM Provider 可插拔化（AI 问答改为可选插件）

日期：2026-08-06
状态：已接受

## 背景

当前"AI 生成回答"硬编码走 DeepSeek API（需付费 key），但导入/检索/标签/
书评/联合搜索等其余功能本就不需要外部 API。边界不透明，易让用户误以为
"整个图书馆都要收费"。本轮把 AI 问答做成可自由开关、可自选后端的插件，
并支持零成本本地方案（Ollama）。

## 决策

### 1. Provider 抽象（`app/providers.py`）

```python
class LLMProvider(Protocol):
    name: str
    provider_type: str  # "openai_compatible" | "ollama"
    def build_request(self, messages, stream) -> (url, headers, body)
```

- **只负责"给定 messages 构造请求"**（返回 url/headers/body），不重写流式
  解析/超时/重试/错误映射——这些保留在 rag.py 已验证稳定的逻辑里；
- 统一走 OpenAI 兼容 **`chat.completions`** 接口（不用 Responses API，
  吸取之前 opencode"Responses 流式失败"教训：部分网关不支持 Responses）。
- 内置实现：
  - `OpenAICompatibleProvider`：base_url + api_key(可空) + model_id 可配。
    DeepSeek 作为它的一个预设（DEEPSEEK_PRESET），不再硬编码专属逻辑。
  - `OllamaProvider`：base_url 默认 `http://localhost:11434/v1`（Ollama
    自带 OpenAI 兼容端点），**无需 api_key**，model_id 用户选。
- `provider_from_config(config)`：从持久化配置构造 Provider，api_key 支持
  环境变量占位符（`{DEEPSEEK_API_KEY}`）解析。

### 2. 配置存储（复用 Phase 4 Connector 模式）

- 新表 `llm_providers`（`app/models.py`）：name(唯一) / provider_type /
  base_url / model_id / **api_key_ref**（环境变量占位符，不落明文）/
  enabled（同一时间仅一个启用）。
- `app/provider_store.py`：`save_provider`（启用时先清其它 enabled）/
  `set_enabled` / `delete_provider` / `get_enabled_provider`。
- 复用了 `app/connectors/persistence.py` 的"结构化列 + 密钥占位符 +
  `_session()` 函数体内 import"模式，未另起新机制。

### 3. 总开关 + 优雅降级

- "启用哪个 Provider"就是总开关：`get_enabled_provider()` 为 None 时，
  检索/标签/书评/联合搜索**完全不受影响**（它们不经过 Provider）；
- 仅"AI 生成回答"抛 `AIAnswerDisabled`（LLMError 子类）：
  - 非流式 `/api/rag/query` → 返回 200 + "⚠️ AI 问答未启用…去设置开启"；
  - 流式 SSE → 发送 `error` 事件带同样引导文案；
  - 是"可选项提示"而非故障/500。

### 4. API

- `GET /api/llm/providers`（列表 + 当前启用名）
- `POST /api/llm/providers`（保存，name 唯一覆盖）
- `PATCH /api/llm/providers/{name}/enable`
- `DELETE /api/llm/providers/{name}`
- `POST /api/llm/test`（测试连接：极简 chat 请求验证配置可用）
- `GET /api/llm/ollama-status`（检测本机 Ollama 服务 + 已拉取模型）

### 5. 前端

- 设置页新增"模型"tab（`components/ProviderSettings.jsx`）：预设选择
  （DeepSeek/OpenAI兼容/Ollama）+ 表单 + **测试连接按钮** + Ollama 引导
  （检测 localhost:11434，不可访问时给下载链接 + `ollama pull qwen2.5:3b`
  一键复制）+ 已保存配置列表（启用/停用/编辑/删除）。

## 权衡

- Provider 只暴露 `build_request` 而非完整 `stream_chat`：最大化复用 rag.py
  已验证的流式重试/超时/错误处理，避免重复实现。
- 配置存独立表而非扩展现有表：语义清晰（Provider ≠ 数据源 Connector）。
- 测试连接用极简 chat 请求（max_tokens=5）：验证连通性 + 鉴权，不打真实
  问答，快且安全。
- ~~未对 Provider 的 base_url 做 SSRF 拦截~~（**已由 ADR 0014 更正**）：
  Provider 复用 ssrf.py 完整校验，Ollama 场景放行回环、通用 Provider 完整
  拦截。见 ADR 0014-provider-ssrf.md。

## 验证

- pytest **168 passed**（+13 provider 用例，覆盖率 81.35%）；
- **Ollama 实测全链路**：本机已装 Ollama + qwen2.5:7b，创建 provider →
  ollama-status 检测到服务与模型 → 测试连接成功 → 流式问答逐块输出完整
  中文回答（sources→chunk*→done）；
- 降级实测：删除 provider 后 `/api/rag/query` 返回"⚠️ AI 问答未启用…"，
  检索/标签/items 仍 200 正常；
- 前端 build/vitest 9/Electron 冒烟通过。
