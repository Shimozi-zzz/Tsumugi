# 0014 · LLM Provider base_url 的 SSRF 边界澄清与加固

日期：2026-08-06
状态：已接受

## 背景与当初遗漏的真实原因

上一轮（ADR 0013）的 LLM Provider 抽象层里，坑位 #29 写了"Provider base_url
不做 SSRF 拦截"，但没说清原因。如实说明当时的经过：

- 最初 `OpenAICompatibleProvider.build_request` **确实接入了**
  `check_ssrf_target(url, resolve=False)`（SSRF 检查）；
- 实测发现它把 Ollama 的默认 `localhost:11434` 也拦掉了（`ssrf.py` 拒绝
  localhost），导致 Ollama 方案无法"测试连接"；
- 我当时为了尽快让 Ollama 跑通，**直接把整段 SSRF 检查删了**——把一个
  "Ollama 需要 localhost 例外"的局部问题，误处理成了"Provider 整体不做
  SSRF"。

结论：这是**有意但错误的过度放宽**。Connector 和 Provider 本质是同一类
风险（用户填 URL → 后端发起 HTTP 请求），不应因组件类型区别对待。正确的
做法是按 provider_type 区分例外，而非整体放弃。

## 加固方案

### 1. 复用 ssrf.py，按场景区分

`app/connectors/ssrf.py` 的 `check_ssrf_target` 新增参数
`allow_loopback: bool = False`：

- **OllamaProvider**（`provider_type="ollama"`）：`allow_loopback=True`，
  放行 `localhost` / `127.0.0.1` / `::1`（本机预期内的合法服务）；
  但**其它私网（10.0.0.0/8、172.16/12、192.168/16）和链路本地
  （169.254/16、云元数据）等仍拦截**——只有回环被例外，不整体放宽。
- **OpenAICompatibleProvider**（通用）：`allow_loopback=False`，与 Connector
  完全一致的完整校验（协议白名单 + 私网/回环/链路本地/CGNAT/组播拒绝 +
  DNS rebinding 缓解）。

### 2. 校验时机

- **配置期**（保存 provider 时）：`provider_from_config(config, validate=True)`
  对 base_url 做 `resolve=False` 轻校验（协议 + IP 字面量 + localhost）；
  内网地址保存时即被拒绝（HTTP 400）。
- **请求期**：`build_request` 每次调用 `validate_target(url, resolve=True)`
  完整校验（含 DNS rebinding 缓解）。
- **测试连接**：`test_connection` 走同一 `provider_from_config` +
  `build_request`，不绕过校验。

### 3. 实现位置

- `app/providers.py`：两个 Provider 类各加 `validate_target(url, resolve)`；
  `provider_from_config(config, validate=True)` 构造后做配置期校验。
- `app/connectors/ssrf.py`：`check_ssrf_target` 加 `allow_loopback` 参数
  （默认 False，不影响 Connector 原有行为）。
- `app/api/routes.py`：`save_llm_provider` 保存前调用
  `provider_from_config(validate=True)` 校验，违规返回 400。

## 权衡

- `allow_loopback` 只放行**回环**而非"所有内网"：Ollama 场景唯一合法内网
  地址就是本机，其它私网地址（如用户误填 10.x）仍有风险，不放宽。
- 配置期用 `resolve=False`（不做 DNS）：保存配置不阻塞（域名类型在请求
  时才解析校验），同时 IP 字面量和 localhost 在保存时就能拦。
- 与 Connector 行为一致性：`ssrf.py` 默认参数不变，Connector 的调用不受
  影响（ADR 0011 边界不变）。

## 测试

- `tests/test_providers.py` 新增 9 用例：
  - Ollama localhost/127.0.0.1 放行；
  - Ollama 仍拦 10.0.0.0/8 私网；
  - 通用 Provider 拦 localhost、拦 192.168.1.10；
  - 通用 Provider 公网 IP/域名放行；
  - `provider_from_config(validate=True)` 拒内网、放行 Ollama localhost；
  - DNS rebinding（解析到 169.254.169.254）在请求期被拒；
  - Ollama build_request 正常。
- 实测（本机 Ollama）：
  - Ollama localhost 配置保存 + 测试连接成功；
  - 内网通用 Provider（192.168.1.10 / 169.254.169.254）保存被拒（400）；
  - 公网 deepseek 配置保存成功。

## api_key 落地流程（补充说明）

用户在前端"模型"设置表单填的 `api_key`，落库的是 **`api_key_ref`
环境变量占位符**（如 `{DEEPSEEK_API_KEY}`），不落明文：

```
前端表单 api_key 输入（提示填 {ENV_VAR} 占位符）
  → POST /api/llm/providers { api_key_ref: "{DEEPSEEK_API_KEY}" }
  → 存入 llm_providers.api_key_ref 列（明文 key 不落库）
  → 运行时 provider_from_config：_resolve_env_placeholder 把 {ENV_VAR}
    解析为 os.environ.get("ENV_VAR")
  → OpenAICompatibleProvider.api_key = 真实 key（仅内存，用于请求头）
```

真实 key 在 `.env` 或系统环境变量里。若用户直接填明文而非占位符，会被
当作字面值使用（也支持），但推荐占位符方式（不落库）。

## 已知局限

- `allow_loopback` 是全局开关（针对 provider 类型），未做"用户明确确认
  才放行"的交互；当前个人本地项目可接受。
- 若未来做多用户/公网服务，应把 Provider 出站也纳入网络命名空间隔离
  （同 ADR 0011 建议）。
