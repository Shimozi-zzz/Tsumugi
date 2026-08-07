"""声明式 Connector 的 SSRF 防护

风险：用户可配置任意 base_url/search_endpoint，后端发起请求。若不校验目标
地址，可能被用来探测内网/云元数据服务（SSRF）。

防护级别（当前实现）：
1. 仅允许 http/https 协议；
2. 解析 host 得到 IP，拒绝回环/私网/链路本地/保留地址；
3. 解析后再校验（防 DNS rebinding：校验用的解析结果与请求用的同一 IP）。

已知局限（如实标注，见 ADR 0011）：
- 仅单层防护，无"解析+固定 IP 请求"的绑定；攻击者可通过极短 TTL 的 DNS
  切换达成 rebinding（本实现解析一次校验一次，属"校验后即请求"）；
- 未做重定向跟随次数限制的地址复查（httpx 默认 follow_redirects=False）；
- 若未来做成多用户/公网服务，需升级为：二次解析绑定 / allowlist / 网络
  命名空间隔离。
"""
import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse

# 禁止访问的 IP 范围
PRIVATE_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),      # 回环
    ipaddress.ip_network("10.0.0.0/8"),       # 私网 A
    ipaddress.ip_network("172.16.0.0/12"),    # 私网 B
    ipaddress.ip_network("192.168.0.0/16"),   # 私网 C
    ipaddress.ip_network("169.254.0.0/16"),   # 链路本地（云元数据）
    ipaddress.ip_network("0.0.0.0/8"),        # 保留
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT
    ipaddress.ip_network("224.0.0.0/4"),      # 组播
    ipaddress.ip_network("240.0.0.0/4"),      # 保留
    ipaddress.ip_network("::1/128"),          # IPv6 回环
    ipaddress.ip_network("fc00::/7"),         # IPv6 唯一本地
    ipaddress.ip_network("fe80::/10"),        # IPv6 链路本地
]


class SSRFError(ValueError):
    """目标地址被 SSRF 防护拒绝。"""


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    for net in PRIVATE_NETS:
        if ip in net:
            return True
    return False


def check_ssrf_target(
    url: str,
    resolve: bool = True,
    allow_loopback: bool = False,
) -> None:
    """校验目标 URL 是否允许访问；违规抛 SSRFError。

    - resolve=True：解析 host 为 IP 并校验（防 DNS rebinding 的"再校验"）；
    - resolve=False：仅校验协议 + host 是否为 IP 字面量（创建配置时轻校验）；
    - allow_loopback=True：放行回环地址（127.0.0.1 / ::1 / localhost）。
      用于 LLM Provider 的 Ollama 场景——localhost 是本机预期内的合法服务，
      不该被当成攻击拦截；但**其它私网/链路本地等仍拦截**。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"仅允许 http/https 协议，收到：{parsed.scheme or '（空）'}")

    host = parsed.hostname
    if not host:
        raise SSRFError("目标 URL 缺少 host")

    # 先尝试把 host 当 IP 字面量处理（含 IPv6 [::1] 形式）
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        ip = None

    if ip is not None:
        if _is_blocked_ip(ip):
            if allow_loopback and _is_loopback(ip):
                return  # 显式放行回环（Ollama 场景）
            raise SSRFError(f"目标地址 {host} 属于内网/回环/保留地址，已拒绝")
        return

    # 本机主机名（含变体）即使不解析也直接拒绝
    if host.lower() in ("localhost", "localhost.localdomain", "::1"):
        if allow_loopback:
            return  # 显式放行 localhost（Ollama 场景）
        raise SSRFError(f"目标地址 {host} 指向本机回环，已拒绝")

    # host 是域名：若要求解析，则解析后校验（DNS rebinding 缓解）
    if resolve:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as e:
            raise SSRFError(f"无法解析域名 {host}：{e}") from e
        for info in infos:
            raw_ip = info[4][0]
            try:
                ip = ipaddress.ip_address(raw_ip)
            except ValueError:
                continue
            if _is_blocked_ip(ip):
                if allow_loopback and _is_loopback(ip):
                    continue  # 显式放行回环（Ollama 场景）
                raise SSRFError(f"域名 {host} 解析到内网/回环地址 {raw_ip}，已拒绝")
        if not infos:
            raise SSRFError(f"域名 {host} 无解析结果")


def _is_loopback(ip) -> bool:
    """是否回环地址（127.0.0.0/8 或 ::1）。"""
    return ip.is_loopback


def check_ssrf_url_or_none(url: Optional[str], resolve: bool = True) -> None:
    """对可能为 None 的 URL 调用；None 直接通过。"""
    if url:
        check_ssrf_target(url, resolve=resolve)
