"""
Tsumugi 轻量桌面端单进程入口（PyWebView 无边框沉浸窗口 + 内置 FastAPI）
- 兼容 PyInstaller --noconsole 无控制台模式（避免 sys.stdout/stderr 为 None 导致 .isatty() 崩溃）
- 自动申请空闲本地端口，守护线程拉起内置 Uvicorn 服务
- 本地健康检查绕过系统代理，轮询 /api/system/version 就绪后在主线程打开无边框 WebView2 窗口
- 暴露 DesktopWindowApi 供前端自定义标题栏控制最小化、最大化/还原、全屏与优雅关闭
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from typing import Any
import urllib.error
import urllib.request

from backend.core.config import DATA_DIR, FRONTEND_DIST_DIR, ensure_data_dirs


class _WinError10054Filter(logging.Filter):
    """过滤 Windows ProactorEventLoop 常见的无害 WinError 10054 远程连接重置日志噪声"""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "WinError 10054" in msg or ("10054" in msg and "ConnectionResetError" in msg):
            return False
        if record.exc_info and record.exc_info[1]:
            exc = record.exc_info[1]
            if isinstance(exc, ConnectionResetError) and getattr(exc, "winerror", None) == 10054:
                return False
        return True


def _setup_safe_io_and_logging() -> logging.Logger:
    """在 PyInstaller --noconsole 模式下重定向空标准流并将运行日志写入 DATA_DIR/tsumugi.log"""
    ensure_data_dirs()
    log_path = DATA_DIR / "tsumugi.log"

    if sys.stdout is None or sys.stderr is None:
        try:
            stream = open(log_path, "a", encoding="utf-8", buffering=1)
        except OSError:
            stream = open(os.devnull, "w", encoding="utf-8")
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream

    handlers: list[logging.Handler] = []
    try:
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    except OSError:
        pass
    if not getattr(sys, "frozen", False):
        handlers.append(logging.StreamHandler(sys.stderr))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers or None,
        force=True,
    )

    noise_filter = _WinError10054Filter()
    logging.getLogger("asyncio").addFilter(noise_filter)
    for h in logging.getLogger().handlers:
        h.addFilter(noise_filter)

    return logging.getLogger("tsumugi.desktop")


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_backend(port: int, timeout: float = 10.0) -> bool:
    """本地健康轮询强制绕过系统代理，防止代理拦截 127.0.0.1 导致超时"""
    url = f"http://127.0.0.1:{port}/api/system/version"
    no_proxy_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with no_proxy_opener.open(url, timeout=0.6) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.12)
    return False


def _resolve_lnk_target(lnk_path: Path) -> str:
    if sys.platform != "win32":
        return str(lnk_path)
    try:
        escaped = str(lnk_path).replace("'", "''")
        ps_cmd = (
            f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{escaped}');"
            "Write-Output $s.TargetPath"
        )
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).strip()
        if out and Path(out).exists():
            return out
    except Exception:
        pass
    return str(lnk_path)


def _apply_windows_dark_titlebar(window_title: str) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.user32.FindWindowW(None, window_title)
        if not hwnd:
            return
        value = ctypes.c_int(1)
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass


class DesktopWindowApi:
    """暴露给前端 window.pywebview.api 的桌面窗口控制与本地文件/目录选择桥接"""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._window: Any = None
        self._is_maximized: bool = False
        self._is_fullscreen: bool = False

    def attach(self, window: Any) -> None:
        self._window = window
        # 同步原生窗口事件，保证最大化状态在拖拽贴边后依然准确
        maximized_ev = getattr(window.events, "maximized", None)
        restored_ev = getattr(window.events, "restored", None)
        if maximized_ev is not None:
            maximized_ev += self._on_maximized
        if restored_ev is not None:
            restored_ev += self._on_restored

    def _on_maximized(self) -> None:
        self._is_maximized = True

    def _on_restored(self) -> None:
        self._is_maximized = False

    def minimize(self) -> bool:
        if not self._window:
            return False
        try:
            self._window.minimize()
            return True
        except Exception as exc:
            self._logger.debug("minimize failed: %s", exc)
            return False

    def toggle_maximize(self) -> bool:
        if not self._window:
            return self._is_maximized
        try:
            if self._is_fullscreen:
                self.exit_fullscreen()
            if self._is_maximized:
                self._window.restore()
                self._is_maximized = False
            else:
                self._window.maximize()
                self._is_maximized = True
        except Exception as exc:
            self._logger.debug("toggle_maximize failed: %s", exc)
        return self._is_maximized

    def toggle_fullscreen(self) -> bool:
        if not self._window:
            return self._is_fullscreen
        try:
            self._window.toggle_fullscreen()
            self._is_fullscreen = not self._is_fullscreen
        except Exception as exc:
            self._logger.debug("toggle_fullscreen failed: %s", exc)
        return self._is_fullscreen

    def exit_fullscreen(self) -> bool:
        if not self._window or not self._is_fullscreen:
            return False
        try:
            self._window.toggle_fullscreen()
            self._is_fullscreen = False
        except Exception as exc:
            self._logger.debug("exit_fullscreen failed: %s", exc)
        return self._is_fullscreen

    def close(self) -> bool:
        if not self._window:
            return False
        try:
            self._window.destroy()
            return True
        except Exception as exc:
            self._logger.debug("close window failed: %s", exc)
            return False

    def get_window_state(self) -> dict[str, bool]:
        return {
            "is_desktop": True,
            "is_fullscreen": self._is_fullscreen,
            "is_maximized": self._is_maximized,
        }

    def pick_file(
        self,
        title: str = "选择文件",
        file_types: list[str] | None = None,
    ) -> str:
        if not self._window:
            return ""
        try:
            import webview

            ft = (
                tuple(file_types)
                if file_types
                else ("Executable (*.exe;*.lnk;*.bat)", "All files (*.*)")
            )
            dialog_type = getattr(webview, "FileDialog", None)
            open_flag = dialog_type.OPEN if dialog_type else webview.OPEN_DIALOG
            result = self._window.create_file_dialog(
                open_flag,
                allow_multiple=False,
                file_types=ft,
            )
            if not result:
                return ""
            chosen = Path(result[0])
            if chosen.suffix.lower() == ".lnk":
                return _resolve_lnk_target(chosen)
            return str(chosen)
        except Exception as exc:
            self._logger.debug("pick_file failed: %s", exc)
            return ""

    def pick_folder(self, title: str = "选择文件夹") -> str:
        if not self._window:
            return ""
        try:
            import webview

            dialog_type = getattr(webview, "FileDialog", None)
            folder_flag = dialog_type.FOLDER if dialog_type else webview.FOLDER_DIALOG
            result = self._window.create_file_dialog(folder_flag)
            if not result:
                return ""
            return str(result[0])
        except Exception as exc:
            self._logger.debug("pick_folder failed: %s", exc)
            return ""


def main() -> None:
    logger = _setup_safe_io_and_logging()

    frontend_index = FRONTEND_DIST_DIR / "index.html"
    logger.info(
        "启动环境检查: frozen=%s, DATA_DIR=%s, FRONTEND_DIST_DIR=%s (exists=%s, index_ready=%s)",
        getattr(sys, "frozen", False),
        DATA_DIR,
        FRONTEND_DIST_DIR,
        FRONTEND_DIST_DIR.is_dir(),
        frontend_index.is_file(),
    )

    try:
        import uvicorn
        import webview
        from backend.main import app
        from backend.services.process_tracker import process_tracker
    except Exception as exc:
        logger.exception("桌面端依赖加载失败: %s", exc)
        sys.exit(1)

    port = _find_free_port()
    logger.info("启动内置服务: http://127.0.0.1:%d", port)

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_config=None,
        access_log=False,
    )
    server = uvicorn.Server(config)
    # 非主线程运行 Uvicorn 时跳过信号处理器注册，避免 ValueError
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]

    server_thread = threading.Thread(
        target=server.run,
        name="tsumugi-backend",
        daemon=True,
    )
    server_thread.start()

    if not _wait_for_backend(port, timeout=10.0):
        logger.error("内置服务在 10 秒内未能就绪，退出启动")
        server.should_exit = True
        sys.exit(1)

    window_api = DesktopWindowApi(logger)
    window = webview.create_window(
        title="Tsumugi",
        url=f"http://127.0.0.1:{port}",
        width=1360,
        height=840,
        min_size=(1080, 680),
        background_color="#0a0a0c",
        frameless=True,
        easy_drag=False,
        resizable=True,
        js_api=window_api,
    )
    window_api.attach(window)
    window.events.loaded += lambda: _apply_windows_dark_titlebar("Tsumugi")

    start_kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        start_kwargs["gui"] = "edgechromium"

    start_sig = inspect.signature(webview.start).parameters
    if "storage_path" in start_sig:
        webview_cache_dir = DATA_DIR / "webview_cache"
        webview_cache_dir.mkdir(parents=True, exist_ok=True)
        start_kwargs["storage_path"] = str(webview_cache_dir)
    if "private_mode" in start_sig:
        start_kwargs["private_mode"] = False

    def _log_runtime_renderer() -> None:
        renderer = getattr(webview, "renderer", None) or start_kwargs.get("gui", "default")
        logger.info(
            "WebView 启动就绪: renderer=%s, frameless=True, storage_path=%s",
            renderer,
            start_kwargs.get("storage_path", "default"),
        )

    window.events.loaded += _log_runtime_renderer
    logger.info("调用 webview.start 参数: %s", start_kwargs)

    try:
        webview.start(**start_kwargs)
    except Exception as exc:
        logger.exception("桌面窗口运行异常: %s", exc)
    finally:
        logger.info("窗口已关闭，正在落盘游玩记录并退出后台服务...")
        server.should_exit = True
        try:
            asyncio.run(process_tracker.shutdown_flush())
        except Exception:
            pass
        server_thread.join(timeout=3.0)
        os._exit(0)


if __name__ == "__main__":
    main()
