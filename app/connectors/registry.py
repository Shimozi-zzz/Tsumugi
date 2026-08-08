"""Connector 注册/发现机制（Phase 3 + Phase 4 + ADR 0027 插件）

注册方式：
- 内置：实现 Connector 的实例 register() 注册，或 discover() 自动扫描；
- 声明式（Phase 4）：用户通过 HTTP 端点+字段映射配置接入，无需写代码，
  由 register_declarative(config) 创建 DeclarativeConnector 注册；
- 代码级插件（ADR 0027）：用户手动放入 plugins/ 目录的第三方 Python 模块，
  由 app.plugins.load_plugins() 加载注册（origin="plugin"）。

origin 追踪：区分内置/声明式/插件，供设置页"插件管理"做风险提示。
"""
from typing import Dict, List, Optional

from app.connectors.base import Connector, ConnectorManifest, DeclarativeConnector

_registry: Dict[str, Connector] = {}
_enabled: Dict[str, bool] = {}
_origin: Dict[str, str] = {}  # name -> "builtin" | "declarative" | "plugin"


def register(connector: Connector, enabled: bool = True, origin: str = "builtin") -> None:
    """注册一个 Connector 实例。同名重复注册会覆盖。origin 记录注册来源。"""
    _registry[connector.name] = connector
    _enabled[connector.name] = enabled
    _origin[connector.name] = origin


def register_declarative(config: dict, enabled: bool = True) -> DeclarativeConnector:
    """按声明式配置注册自定义数据源（Phase 4）。配置非法时抛 ValueError。"""
    connector = DeclarativeConnector(config)
    register(connector, enabled=enabled, origin="declarative")
    return connector


def register_plugin(connector: Connector, enabled: bool = True) -> None:
    """注册代码级插件（ADR 0027），origin 标记为 plugin 供风险提示。"""
    register(connector, enabled=enabled, origin="plugin")


def unregister(name: str) -> None:
    _registry.pop(name, None)
    _enabled.pop(name, None)
    _origin.pop(name, None)


def get_connector(name: str) -> Optional[Connector]:
    return _registry.get(name)


def get_origin(name: str) -> Optional[str]:
    return _origin.get(name)


def list_plugin_connectors() -> List[Connector]:
    """返回全部已注册的代码级插件 Connector。"""
    return [c for n, c in _registry.items() if _origin.get(n) == "plugin"]


def get_enabled_connectors() -> List[Connector]:
    """返回已启用（且已注册）的 Connector 列表。"""
    return [c for n, c in _registry.items() if _enabled.get(n)]


def list_manifests() -> List[ConnectorManifest]:
    return [c.manifest for c in _registry.values()]


def set_enabled(name: str, enabled: bool) -> bool:
    if name not in _registry:
        return False
    _enabled[name] = enabled
    return True


def is_enabled(name: str) -> bool:
    return _enabled.get(name, False)


def apply_settings(settings: dict) -> None:
    """把持久化的 connector 设置（含出站代理）应用到已注册实例。

    约定：settings = {"<connector_name>": {"proxy_url": "..."}}，
    值为空串/None 表示直连（清除代理）。启动与保存代理时调用。
    """
    for name, conf in (settings or {}).items():
        conn = _registry.get(name)
        if conn is None:
            continue
        proxy = (conf or {}).get("proxy_url") or None
        conn.proxy_url = proxy


def set_proxy(name: str, proxy_url: Optional[str]) -> bool:
    """设置某 Connector 的出站代理（不持久化，持久化由调用方负责）。"""
    conn = _registry.get(name)
    if conn is None:
        return False
    conn.proxy_url = (proxy_url or "").strip() or None
    return True


def get_proxy(name: str) -> Optional[str]:
    conn = _registry.get(name)
    return getattr(conn, "proxy_url", None) if conn else None


def discover() -> List[str]:
    """扫描 app/connectors 子目录，自动发现并注册内置 Connector。

    约定：每个子目录含 manifest.json 与 connector.py，connector.py 暴露
    build_connector() 工厂函数。返回成功注册的名字列表。
    """
    import importlib
    import json
    from pathlib import Path

    base_dir = Path(__file__).parent
    registered = []
    for entry in sorted(base_dir.iterdir()):
        manifest_path = entry / "manifest.json"
        connector_py = entry / "connector.py"
        if not (entry.is_dir() and manifest_path.exists() and connector_py.exists()):
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = ConnectorManifest.from_dict(json.load(f))
            mod = importlib.import_module(f"app.connectors.{entry.name}.connector")
            build = getattr(mod, "build_connector", None)
            if not callable(build):
                continue
            connector = build()
            if not hasattr(connector, "name"):
                connector.name = manifest.name
            register(connector, enabled=True)
            registered.append(manifest.name)
        except Exception as e:  # noqa: BLE001 - 单个插件失败不影响其它
            print(f"[connector] 发现 {entry.name} 失败：{e}")
    return registered
