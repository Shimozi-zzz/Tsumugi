import logging
import os
import shlex
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger("tsumugi.os_adapter")


class BaseOSAdapter(ABC):
    """跨平台系统能力抽象基类"""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        pass

    @abstractmethod
    def launch_executable(
        self,
        exe_path: str,
        launch_mode: str = "direct",
        launch_args: str = "",
        le_exe_path: str = "",
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    def open_local_folder(self, folder_path: str) -> bool:
        pass


class MockLinuxAdapter(BaseOSAdapter):
    """Linux 云端开发专用模拟器：无需真实 .exe 即可完整测试业务闭环"""

    @property
    def platform_name(self) -> str:
        return "Linux-Dev-Mock"

    def launch_executable(
        self,
        exe_path: str,
        launch_mode: str = "direct",
        launch_args: str = "",
        le_exe_path: str = "",
    ) -> dict[str, Any]:
        target_display = exe_path.strip() if exe_path else "/mock/path/game.exe"
        logger.info(
            "[MockLinuxAdapter] 模拟启动游戏: target=%s mode=%s args=%s",
            target_display,
            launch_mode,
            launch_args,
        )
        return {
            "status": "mock_started",
            "mode": launch_mode,
            "target": target_display,
            "pid": 99999,
            "message": "Linux 开发环境模拟启动成功，已开启虚拟计时器",
        }

    def open_local_folder(self, folder_path: str) -> bool:
        target = Path(folder_path)
        logger.info(
            "[MockLinuxAdapter] 模拟打开文件夹: %s (存在状态: %s)",
            target,
            target.exists(),
        )
        return True


class WindowsOSAdapter(BaseOSAdapter):
    """Windows 本地生产环境执行器"""

    @property
    def platform_name(self) -> str:
        return "Windows-Native"

    @staticmethod
    def _is_uri(value: str) -> bool:
        lower = value.strip().lower()
        return any(lower.startswith(prefix) for prefix in ("steam://", "http://", "https://", "com.epicgames.launcher://"))

    def launch_executable(
        self,
        exe_path: str,
        launch_mode: str = "direct",
        launch_args: str = "",
        le_exe_path: str = "",
    ) -> dict[str, Any]:
        raw_exe = (exe_path or "").strip()
        raw_args = (launch_args or "").strip()

        # 支持 Steam URI 或自定义协议拉起
        if self._is_uri(raw_exe) or (launch_mode == "cli" and not raw_exe and self._is_uri(raw_args)):
            uri = raw_exe if self._is_uri(raw_exe) else raw_args
            os.startfile(uri)  # type: ignore[attr-defined]
            return {
                "status": "started",
                "mode": "uri",
                "target": uri,
                "pid": 0,
                "message": f"已通过系统协议唤起: {uri}",
            }

        if not raw_exe:
            if launch_mode == "cli" and raw_args:
                proc = subprocess.Popen(raw_args, shell=True)
                return {
                    "status": "started",
                    "mode": "cli",
                    "target": raw_args,
                    "pid": proc.pid,
                    "message": "Windows 自定义命令行拉起成功",
                }
            raise FileNotFoundError("尚未配置游戏启动程序路径（exe_path）")

        target = Path(raw_exe)
        if not target.exists():
            raise FileNotFoundError(f"找不到指定的游戏启动文件: {raw_exe}")

        work_dir = str(target.parent)
        cmd: list[str] | str
        use_shell = False

        if launch_mode == "le":
            le_target = Path(le_exe_path.strip()) if le_exe_path else None
            if not le_target or not le_target.exists():
                raise FileNotFoundError(
                    "已选择 Locale Emulator 转区模式，但未找到有效的 LEProc.exe，请在全局设置中配置路径"
                )
            cmd = [str(le_target), str(target)]
            if raw_args:
                cmd.extend(shlex.split(raw_args, posix=False))
        elif launch_mode == "cli" and raw_args:
            cmd = f'"{target}" {raw_args}'
            use_shell = True
        elif target.suffix.lower() == ".lnk":
            os.startfile(str(target))  # type: ignore[attr-defined]
            return {
                "status": "started",
                "mode": launch_mode,
                "target": str(target),
                "pid": 0,
                "message": "Windows 快捷方式拉起成功",
            }
        else:
            cmd = [str(target)]
            if raw_args:
                cmd.extend(shlex.split(raw_args, posix=False))

        proc = subprocess.Popen(cmd, cwd=work_dir, shell=use_shell)
        return {
            "status": "started",
            "mode": launch_mode,
            "target": str(target),
            "pid": proc.pid,
            "message": "Windows 进程拉起成功",
        }

    def open_local_folder(self, folder_path: str) -> bool:
        target = Path(folder_path)
        if not target.exists():
            return False
        os.startfile(str(target))  # type: ignore[attr-defined]
        return True


def get_os_adapter() -> BaseOSAdapter:
    if sys.platform == "win32":
        return WindowsOSAdapter()
    return MockLinuxAdapter()


os_adapter: BaseOSAdapter = get_os_adapter()
