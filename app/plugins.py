"""第三方代码级插件加载（ADR 0027：本地文件信任模型）

信任模型（本轮最重要的设计约束，详见 docs/decisions/0027-code-plugins.md）：
- 允许：用户把插件子目录（manifest.json + connector.py）手动放进 `plugins/`，
  重启应用后被加载；
- 禁止：应用内置"插件市场/一键远程安装并自动运行"；
- 不做沙盒隔离：插件代码运行时拥有与后端完全相同的权限，风险以用户可见的
  方式暴露（设置页插件面板醒目标识 + 首次检测到插件时的一次性确认提示 +
  插件开发文档安全声明），而非假装做了隔离。

插件目录约定（与内置 Bangumi/萌娘百科/VNDB 同构，见 plugins/README.md）：
```
plugins/
├── README.md
├── _template/            # 参考示例（名字以 _ 开头，不会自动加载）
└── my_connector/
    ├── manifest.json     # name/display_name/version/auth_type/base_url/rate_limit/capabilities
    └── connector.py      # 暴露 build_connector() 工厂函数
```

加载机制：
- 扫描 settings.plugins_dir 下的一级子目录（跳过以 _ 或 . 开头的目录）；
- 每个目录必须含 manifest.json + connector.py；
- connector.py 通过 importlib 以独立模块名加载（可用绝对导入 `from app...`）；
- build_connector() 返回的实例：name/manifest 以 manifest.json 为准（覆盖），
  必须有可调用 search()，若声明 get_detail 能力则必须有可调用 get_detail()；
- 任何单个插件失败（代码错误/语法错误/接口不符合/名字冲突）都**优雅跳过**、
  记录清晰错误日志与 failures 列表，不影响其它插件与应用启动。
"""
import importlib.util
import json
import logging
from pathlib import Path
from typing import List, Optional

from app.config import settings
from app.connectors.base import ConnectorManifest
from app.connectors import registry

logger = logging.getLogger("tsumugi.plugins")

# 上次加载的状态（供 /plugins 端点展示）
_loaded: List[dict] = []
_failures: List[dict] = []


def _plugin_entry(entry: Path) -> bool:
    """只处理含 manifest.json + connector.py 的一级子目录；_ / . 开头跳过。"""
    return (
        entry.is_dir()
        and not entry.name.startswith(("_", "."))
        and (entry / "manifest.json").exists()
        and (entry / "connector.py").exists()
    )


def _load_module(path: Path, module_name: str):
    """以独立模块名加载任意路径的 .py（每次 exec，不依赖 sys.path）。"""
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"无法创建模块 spec：{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_connector(entry: Path, manifest: ConnectorManifest):
    """加载 connector.py 并构造 Connector 实例，校验接口约定。"""
    mod = _load_module(entry / "connector.py", f"tsumugi_plugin_{manifest.name}")
    build = getattr(mod, "build_connector", None)
    if not callable(build):
        raise TypeError("connector.py 必须暴露可调用的 build_connector() 工厂函数")
    connector = build()
    if connector is None:
        raise TypeError("build_connector() 返回了 None")
    # manifest.json 是身份/能力唯一权威（简化插件作者：无需在代码里再造 manifest）
    connector.name = manifest.name
    connector.manifest = manifest
    if not callable(getattr(connector, "search", None)):
        raise TypeError("插件必须实现 search(query, **filters) -> list[SearchResult]")
    if "get_detail" in (manifest.capabilities or []) and not callable(
        getattr(connector, "get_detail", None)
    ):
        raise TypeError("manifest 声明了 get_detail 能力，但插件未实现 get_detail()")
    return connector


def load_plugins() -> dict:
    """扫描并加载 plugins/ 目录下的代码级插件。

    幂等：每次调用重新扫描（启动时调用一次即可）。单个插件失败不阻塞其它，
    失败信息记录进 failures。返回 {"loaded": [...], "failures": [...]}。
    """
    global _loaded, _failures
    _loaded = []
    _failures = []

    plugins_dir = Path(settings.plugins_dir)
    if not plugins_dir.is_dir():
        return {"loaded": _loaded, "failures": _failures}

    for entry in sorted(plugins_dir.iterdir()):
        if not _plugin_entry(entry):
            continue
        try:
            manifest = ConnectorManifest.from_dict(
                json.loads((entry / "manifest.json").read_text(encoding="utf-8"))
            )
            if not manifest.name:
                raise ValueError("manifest 缺少 name")
            if registry.get_connector(manifest.name) is not None:
                raise ValueError(f"数据源名 '{manifest.name}' 已被占用")
            connector = _build_connector(entry, manifest)
            registry.register_plugin(connector, enabled=True)
            _loaded.append({
                "name": manifest.name,
                "display_name": manifest.display_name,
                "version": manifest.version,
                "capabilities": manifest.capabilities,
                "path": str(entry),
                "enabled": True,
            })
            logger.info("[plugin] 已加载 %s (%s)", manifest.name, entry.name)
        except Exception as e:  # noqa: BLE001 - 单个插件失败不阻塞其它
            msg = str(e) or type(e).__name__
            _failures.append({"dir": entry.name, "error": msg})
            logger.error("[plugin] 加载 %s 失败：%s", entry.name, msg)

    return {"loaded": _loaded, "failures": _failures}


def get_plugin_status() -> dict:
    """当前已加载插件 / 加载失败 / 插件目录，供设置页展示。"""
    return {
        "plugin_dir": settings.plugins_dir,
        "plugins": list(_loaded),
        "failures": list(_failures),
    }


def plugin_notice_needed() -> bool:
    """首次检测到插件且用户尚未确认风险提示时返回 True（一次性，ADR 0027）。"""
    if not _loaded:
        return False
    from app.connectors import persistence
    return not persistence.get_plugin_notice_acknowledged()


def acknowledge_plugins() -> None:
    """用户点击"我已了解"后持久化确认标记。"""
    from app.connectors import persistence
    persistence.set_plugin_notice_acknowledged()
