"""Connector 注册/发现机制（Phase 3 + Phase 4）

注册方式：
- 内置：实现 Connector 的实例 register() 注册，或 discover() 自动扫描；
- 声明式（Phase 4）：用户通过 HTTP 端点+字段映射配置接入，无需写代码，
  由 register_declarative(config) 创建 DeclarativeConnector 注册。
"""
from typing import Dict, List, Optional

from app.connectors.base import Connector, ConnectorManifest, DeclarativeConnector

_registry: Dict[str, Connector] = {}
_enabled: Dict[str, bool] = {}


def register(connector: Connector, enabled: bool = True) -> None:
    """注册一个 Connector 实例。同名重复注册会覆盖。"""
    _registry[connector.name] = connector
    _enabled[connector.name] = enabled


def register_declarative(config: dict, enabled: bool = True) -> DeclarativeConnector:
    """按声明式配置注册自定义数据源（Phase 4）。配置非法时抛 ValueError。"""
    connector = DeclarativeConnector(config)
    register(connector, enabled=enabled)
    return connector


def unregister(name: str) -> None:
    _registry.pop(name, None)
    _enabled.pop(name, None)


def get_connector(name: str) -> Optional[Connector]:
    return _registry.get(name)


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
