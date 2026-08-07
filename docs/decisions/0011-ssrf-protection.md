# 0011 · 声明式 Connector 的 SSRF 防护

日期：2026-08-06
状态：已接受（安全加固）

## 背景

Phase 4 的声明式 Connector 允许用户配置任意 `base_url`/`search_endpoint`，
后端直接发起 HTTP 请求，**没有目标地址校验**。攻击者可借此探测内网、
云元数据服务（如 169.254.169.254）、回环服务等（SSRF）。

## 决策

新增 `app/connectors/ssrf.py`，在**配置创建时**和**每次请求前**都做校验：

### 校验规则（`check_ssrf_target(url, resolve)`）

1. **协议白名单**：仅允许 `http`/`https`；拒绝 `file://`、`ftp://`、无协议
   等。
2. **IP 字面量拒绝**：host 若是 IP（含 IPv6 `[::1]`），落在以下范围即拒绝：
   - `127.0.0.0/8`（回环）、`0.0.0.0/8`（保留）、`224.0.0.0/4`（组播）、
     `240.0.0.0/4`（保留）；
   - `10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`（私网）；
   - `169.254.0.0/16`（链路本地/云元数据）、`100.64.0.0/10`（CGNAT）；
   - IPv6：`::1`、`fc00::/7`、`fe80::/10`。
3. **本机主机名拒绝**：`localhost`/`localhost.localdomain` 等即使不解析也
   直接拒绝。
4. **域名解析后校验（DNS rebinding 缓解）**：`resolve=True` 时用
   `socket.getaddrinfo` 解析域名，**任一解析结果落在私网/回环即拒绝**。

### 接入点

- `DeclarativeConnector._validate()`：创建配置时 `resolve=False` 轻校验
  （协议 + IP 字面量 + localhost），配置非法直接拒绝创建。
- `DeclarativeConnector.search()`：每次请求前 `resolve=True` 校验目标 URL。

### 测试

`tests/test_ssrf.py`（17 用例）：协议拒绝、各私网段/IP 拒绝、localhost
拒绝、创建校验、DNS 解析到内网拒绝、合法公网放行。

## 当前防护级别与已知局限（如实标注）

**这是"基础单层防护"，不是完整 SSRF 缓解。** 具体局限：

1. **DNS rebinding 不彻底**：本实现是"解析→校验→（校验通过后）请求"，
   攻击者可用极短 TTL 的 DNS 在两次解析之间切换到内网 IP（TOCTOU）。
   彻底方案需"解析后绑定该 IP 直连"（自写 socket 连接，禁用系统解析重试），
   或二次独立解析比对——本轮未实现。
2. **未做重定向跟随复查**：httpx 默认 `follow_redirects=False`，后端不会
   自动跟随重定向，但若未来开启 follow_redirects，需对重定向目标重新校验。
3. **未做请求体/SSRF 到文件（如 `file://`）的纵深防御**：协议白名单已挡，
   但域名可解析到公网 IP 的恶意服务（非本系统能防）。
4. **`resolve=False` 的创建校验只挡 IP 字面量与 localhost**：域名类型
   （如 `evil.example.com` 解析到内网）在创建时放行，请求时才解析拒绝——
   这是刻意的（创建时不该做阻塞性 DNS）。

### 未来做成多用户/公网服务需补

- 解析结果**固定 IP 直连**（防 rebinding）；
- 目标 allowlist / deny-IP 持久化；
- 出站网络命名空间隔离（如容器/独立进程 + 防火墙）；
- 重定向跟随时的二次校验。
