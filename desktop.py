"""
Tsumugi 轻量桌面端单进程入口（PyWebView 无边框沉浸窗口 + 内置 FastAPI）
- 兼容 PyInstaller --noconsole 无控制台模式（避免 sys.stdout/stderr 为 None 导致 .isatty() 崩溃）
- 自动申请空闲本地端口，守护线程拉起内置 Uvicorn 服务
- 本地健康检查绕过系统代理，轮询 /api/system/version 就绪后在主线程打开无边框 WebView2 窗口
- 暴露 DesktopWindowApi 供前端自定义标题栏控制最小化、工作区最大化/还原、零白缝真全屏与优雅关闭
"""

from __future__ import annotations

import asyncio
import ctypes
import inspect
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Callable
import urllib.error
import urllib.request

from backend.core.config import DATA_DIR, FRONTEND_DIST_DIR, ensure_data_dirs

DARK_BG_HEX = "#0a0a0c"
DARK_BG_RGB = (10, 10, 12)
# Win32 COLORREF 格式为 0x00BBGGRR（对应 #0a0a0c）
DARK_BG_COLORREF = 0x000C0A0A
DWMWA_COLOR_NONE = 0xFFFFFFFE

# Win32 窗口样式与 DWM 常量
GWL_STYLE = -16
GWL_EXSTYLE = -20

WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_BORDER = 0x00800000
WS_DLGFRAME = 0x00400000
WS_SYSMENU = 0x00080000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_NONCLIENT_BORDER_MASK = (
    WS_CAPTION
    | WS_THICKFRAME
    | WS_BORDER
    | WS_DLGFRAME
    | WS_SYSMENU
    | WS_MINIMIZEBOX
    | WS_MAXIMIZEBOX
)

WS_EX_DLGMODALFRAME = 0x00000001
WS_EX_WINDOWEDGE = 0x00000100
WS_EX_CLIENTEDGE = 0x00000200
WS_EX_STATICEDGE = 0x00020000
WS_EX_NONCLIENT_EDGE_MASK = (
    WS_EX_DLGMODALFRAME
    | WS_EX_WINDOWEDGE
    | WS_EX_CLIENTEDGE
    | WS_EX_STATICEDGE
)

HWND_TOP = 0
HWND_NOTOPMOST = -2

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040

MONITOR_DEFAULTTONEAREST = 0x00000002

DWMWA_USE_IMMERSIVE_DARK_MODE_PRE20H1 = 19
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35

DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2


class _Win32Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _Win32Point(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


class _Win32MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("rcMonitor", _Win32Rect),
        ("rcWork", _Win32Rect),
        ("dwFlags", ctypes.c_uint),
    ]


class _Win32WindowHelper:
    """Windows 专属原生 Win32 / DWM 调用封装（仅在 win32 平台初始化，64 位指针安全）"""

    def __init__(self) -> None:
        self.available = False
        if sys.platform != "win32":
            return
        try:
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            dwmapi = ctypes.windll.dwmapi

            long_ptr = ctypes.c_ssize_t
            hwnd_t = ctypes.c_void_p

            user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            user32.FindWindowW.restype = hwnd_t

            user32.GetWindowRect.argtypes = [hwnd_t, ctypes.POINTER(_Win32Rect)]
            user32.GetWindowRect.restype = wintypes.BOOL

            user32.GetCursorPos.argtypes = [ctypes.POINTER(_Win32Point)]
            user32.GetCursorPos.restype = wintypes.BOOL

            user32.MonitorFromWindow.argtypes = [hwnd_t, wintypes.DWORD]
            user32.MonitorFromWindow.restype = hwnd_t

            user32.GetMonitorInfoW.argtypes = [hwnd_t, ctypes.POINTER(_Win32MonitorInfo)]
            user32.GetMonitorInfoW.restype = wintypes.BOOL

            user32.SetWindowPos.argtypes = [
                hwnd_t,
                hwnd_t,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL

            if hasattr(user32, "GetWindowLongPtrW"):
                self._get_window_long = user32.GetWindowLongPtrW
                self._set_window_long = user32.SetWindowLongPtrW
            else:
                self._get_window_long = user32.GetWindowLongW
                self._set_window_long = user32.SetWindowLongW

            self._get_window_long.argtypes = [hwnd_t, ctypes.c_int]
            self._get_window_long.restype = long_ptr
            self._set_window_long.argtypes = [hwnd_t, ctypes.c_int, long_ptr]
            self._set_window_long.restype = long_ptr

            dwmapi.DwmSetWindowAttribute.argtypes = [
                hwnd_t,
                ctypes.c_uint,
                ctypes.c_void_p,
                ctypes.c_uint,
            ]
            dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long

            self._user32 = user32
            self._dwmapi = dwmapi
            self.available = True
        except Exception:
            self.available = False

    def find_window(self, title: str) -> int:
        if not self.available or not title:
            return 0
        try:
            return int(self._user32.FindWindowW(None, title) or 0)
        except Exception:
            return 0

    def get_window_rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        if not self.available or not hwnd:
            return None
        rect = _Win32Rect()
        if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        w = int(rect.right - rect.left)
        h = int(rect.bottom - rect.top)
        if w <= 0 or h <= 0:
            return None
        return (int(rect.left), int(rect.top), w, h)

    def get_cursor_pos(self) -> tuple[int, int] | None:
        if not self.available:
            return None
        pt = _Win32Point()
        if not self._user32.GetCursorPos(ctypes.byref(pt)):
            return None
        return (int(pt.x), int(pt.y))

    def get_monitor_rects(
        self, hwnd: int
    ) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]] | None:
        """返回 (rcWork, rcMonitor)，每项为 (x, y, width, height)"""
        if not self.available or not hwnd:
            return None
        hmon = self._user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not hmon:
            return None
        info = _Win32MonitorInfo()
        info.cbSize = ctypes.sizeof(_Win32MonitorInfo)
        if not self._user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return None
        work = (
            int(info.rcWork.left),
            int(info.rcWork.top),
            int(info.rcWork.right - info.rcWork.left),
            int(info.rcWork.bottom - info.rcWork.top),
        )
        mon = (
            int(info.rcMonitor.left),
            int(info.rcMonitor.top),
            int(info.rcMonitor.right - info.rcMonitor.left),
            int(info.rcMonitor.bottom - info.rcMonitor.top),
        )
        return work, mon

    def get_styles(self, hwnd: int) -> tuple[int, int]:
        if not self.available or not hwnd:
            return (0, 0)
        style = int(self._get_window_long(hwnd, GWL_STYLE))
        exstyle = int(self._get_window_long(hwnd, GWL_EXSTYLE))
        return (style, exstyle)

    def set_styles(self, hwnd: int, style: int, exstyle: int) -> None:
        if not self.available or not hwnd:
            return
        self._set_window_long(hwnd, GWL_STYLE, int(style))
        self._set_window_long(hwnd, GWL_EXSTYLE, int(exstyle))

    def set_window_pos(
        self,
        hwnd: int,
        x: int,
        y: int,
        width: int,
        height: int,
        *,
        insert_after: int = HWND_TOP,
        flags: int = SWP_FRAMECHANGED | SWP_SHOWWINDOW,
    ) -> bool:
        if not self.available or not hwnd:
            return False
        return bool(
            self._user32.SetWindowPos(
                hwnd,
                insert_after,
                int(x),
                int(y),
                int(width),
                int(height),
                int(flags),
            )
        )

    def apply_dwm_attributes(
        self,
        hwnd: int,
        *,
        borderless: bool = False,
        disable_round_corners: bool = False,
    ) -> None:
        """设置深色 DWM、消除 Windows 11 默认亮色边框与全屏/最大化圆角缝隙"""
        if not self.available or not hwnd:
            return
        try:
            dark_val = ctypes.c_int(1)
            for attr in (DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_PRE20H1):
                self._dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(dark_val), ctypes.sizeof(dark_val)
                )

            border_val = ctypes.c_uint(DWMWA_COLOR_NONE if borderless else DARK_BG_COLORREF)
            self._dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_BORDER_COLOR, ctypes.byref(border_val), ctypes.sizeof(border_val)
            )

            caption_val = ctypes.c_uint(DARK_BG_COLORREF)
            self._dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(caption_val), ctypes.sizeof(caption_val)
            )

            corner_val = ctypes.c_int(DWMWCP_DONOTROUND if disable_round_corners else DWMWCP_ROUND)
            self._dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(corner_val),
                ctypes.sizeof(corner_val),
            )
        except Exception:
            pass


_WIN32 = _Win32WindowHelper()


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


def _run_on_winforms_ui_thread(form: Any, fn: Callable[[], None]) -> None:
    """将 WinForms UI 属性修改安全封送回主 UI 线程执行"""
    if form is None:
        fn()
        return
    try:
        if getattr(form, "IsDisposed", False):
            return
        if getattr(form, "InvokeRequired", False):
            import System  # type: ignore[import-not-found]

            form.Invoke(System.Action(fn))
            return
    except Exception:
        pass
    try:
        fn()
    except Exception:
        pass


class DesktopWindowApi:
    """暴露给前端 window.pywebview.api 的桌面窗口控制与本地文件/目录选择桥接"""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._window: Any = None
        self._is_maximized: bool = False
        self._is_fullscreen: bool = False
        self._restore_rect: tuple[int, int, int, int] | None = None
        self._maximized_rect: tuple[int, int, int, int] | None = None
        self._pre_fs_was_maximized: bool = False
        self._saved_style: int | None = None
        self._saved_exstyle: int | None = None
        self._ignore_move_until: float = 0.0

    def attach(self, window: Any) -> None:
        self._window = window
        shown_ev = getattr(window.events, "shown", None)
        loaded_ev = getattr(window.events, "loaded", None)
        moved_ev = getattr(window.events, "moved", None)
        maximized_ev = getattr(window.events, "maximized", None)
        restored_ev = getattr(window.events, "restored", None)

        if shown_ev is not None:
            shown_ev += self.on_window_ready
        if loaded_ev is not None:
            loaded_ev += self.on_window_ready
        if moved_ev is not None:
            moved_ev += self._on_window_moved
        if maximized_ev is not None and sys.platform != "win32":
            maximized_ev += self._on_native_maximized
        if restored_ev is not None and sys.platform != "win32":
            restored_ev += self._on_native_restored

    def on_window_ready(self) -> None:
        """窗口显示/加载完成后立即加固深色宿主背景、WebView2 默认底色与 DWM 属性"""
        self._apply_windows_dark_surface()
        self._notify_frontend_state()

    def _get_native_form(self) -> Any:
        if not self._window:
            return None
        native = getattr(self._window, "native", None)
        if native is not None:
            return native
        try:
            gui = getattr(self._window, "gui", None)
            browser_view = getattr(gui, "BrowserView", None)
            instances = getattr(browser_view, "instances", None)
            if isinstance(instances, dict):
                return instances.get(getattr(self._window, "uid", None))
        except Exception:
            pass
        return None

    def _get_hwnd(self) -> int:
        if sys.platform != "win32":
            return 0
        form = self._get_native_form()
        if form is not None:
            try:
                handle = getattr(form, "Handle", None)
                if handle is not None:
                    if hasattr(handle, "ToInt64"):
                        hwnd = int(handle.ToInt64())
                        if hwnd:
                            return hwnd
                    hwnd = int(handle)
                    if hwnd:
                        return hwnd
            except Exception:
                pass
        title = str(getattr(self._window, "title", "") or "Tsumugi")
        return _WIN32.find_window(title)

    def _apply_windows_dark_surface(
        self,
        *,
        fullscreen: bool | None = None,
        maximized: bool | None = None,
    ) -> None:
        """消除 Windows 无边框 Form / WebView2 / DWM 1px 白边、闪白与外边距缝隙"""
        if sys.platform != "win32":
            return
        is_fs = self._is_fullscreen if fullscreen is None else fullscreen
        is_max = self._is_maximized if maximized is None else maximized

        form = self._get_native_form()
        if form is not None:
            def _configure_form() -> None:
                try:
                    import System.Drawing as Drawing  # type: ignore[import-not-found]
                    import System.Windows.Forms as WinForms  # type: ignore[import-not-found]

                    dark_color = Drawing.Color.FromArgb(*DARK_BG_RGB)
                    zero_pad = WinForms.Padding(0)

                    border_none = getattr(WinForms.FormBorderStyle, "None")
                    form.BackColor = dark_color
                    form.Padding = zero_pad
                    form.Margin = zero_pad
                    if hasattr(form, "FormBorderStyle"):
                        form.FormBorderStyle = border_none

                    visited: set[int] = set()
                    queue: list[Any] = []
                    for attr in ("webview", "browser"):
                        wrapper = getattr(form, attr, None)
                        if wrapper is not None:
                            queue.append(wrapper)
                            inner = getattr(wrapper, "web_view", None)
                            if inner is not None:
                                queue.append(inner)
                    controls = getattr(form, "Controls", None)
                    if controls is not None:
                        for ctrl in list(controls):
                            queue.append(ctrl)

                    while queue:
                        ctrl = queue.pop(0)
                        if ctrl is None or id(ctrl) in visited:
                            continue
                        visited.add(id(ctrl))
                        try:
                            if hasattr(ctrl, "BackColor"):
                                ctrl.BackColor = dark_color
                            if hasattr(ctrl, "DefaultBackgroundColor"):
                                ctrl.DefaultBackgroundColor = dark_color
                            if hasattr(ctrl, "Padding"):
                                ctrl.Padding = zero_pad
                            if hasattr(ctrl, "Margin"):
                                ctrl.Margin = zero_pad
                            if hasattr(ctrl, "Dock"):
                                ctrl.Dock = WinForms.DockStyle.Fill
                        except Exception:
                            pass
                        inner_wv = getattr(ctrl, "web_view", None)
                        if inner_wv is not None:
                            queue.append(inner_wv)
                        sub_controls = getattr(ctrl, "Controls", None)
                        if sub_controls is not None:
                            try:
                                for sub in list(sub_controls):
                                    queue.append(sub)
                            except Exception:
                                pass
                except Exception as exc:
                    self._logger.debug("WinForms dark surface update skipped: %s", exc)

            _run_on_winforms_ui_thread(form, _configure_form)

        hwnd = self._get_hwnd()
        if hwnd:
            _WIN32.apply_dwm_attributes(
                hwnd,
                borderless=(is_fs or is_max),
                disable_round_corners=(is_fs or is_max),
            )

    def _ensure_normal_winforms_state(self) -> None:
        """确保 WinForms FormWindowState 保持 Normal，避免原生 Maximized 遮挡任务栏"""
        if sys.platform != "win32":
            return
        form = self._get_native_form()
        if form is None:
            return

        def _reset_state() -> None:
            try:
                import System.Windows.Forms as WinForms  # type: ignore[import-not-found]

                if getattr(form, "WindowState", None) != WinForms.FormWindowState.Normal:
                    form.WindowState = WinForms.FormWindowState.Normal
                if hasattr(form, "FormBorderStyle"):
                    form.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
            except Exception:
                pass

        _run_on_winforms_ui_thread(form, _reset_state)

    def _notify_frontend_state(self) -> None:
        if not self._window:
            return
        payload = json.dumps(self.get_window_state())
        js = (
            "try {"
            f"  window.dispatchEvent(new CustomEvent('tsumugi-window-state', {{ detail: {payload} }}));"
            "} catch (e) {}"
        )
        try:
            self._window.evaluate_js(js)
        except Exception:
            pass

    def _on_native_maximized(self) -> None:
        self._is_maximized = True
        self._notify_frontend_state()

    def _on_native_restored(self) -> None:
        self._is_maximized = False
        self._notify_frontend_state()

    def _on_window_moved(self, *_args: Any) -> None:
        """最大化状态下用户拖拽标题栏移动窗口时，自动还原常规尺寸并同步图标状态"""
        if sys.platform != "win32":
            return
        if time.monotonic() < self._ignore_move_until:
            return
        if not self._is_maximized or self._is_fullscreen:
            return
        hwnd = self._get_hwnd()
        if not hwnd or not self._maximized_rect:
            return
        cur = _WIN32.get_window_rect(hwnd)
        if not cur:
            return
        mx, my, _mw, _mh = self._maximized_rect
        if abs(cur[0] - mx) > 8 or abs(cur[1] - my) > 8:
            self.restore_for_drag(0.5)

    def _apply_win32_maximize_work_area(self) -> bool:
        hwnd = self._get_hwnd()
        if not hwnd or not _WIN32.available:
            return False
        rects = _WIN32.get_monitor_rects(hwnd)
        if not rects:
            return False
        work_x, work_y, work_w, work_h = rects[0]
        if work_w <= 0 or work_h <= 0:
            return False

        self._ensure_normal_winforms_state()
        if not self._is_maximized:
            cur = _WIN32.get_window_rect(hwnd)
            if cur:
                self._restore_rect = cur

        self._ignore_move_until = time.monotonic() + 0.45
        _WIN32.set_window_pos(
            hwnd,
            work_x,
            work_y,
            work_w,
            work_h,
            insert_after=HWND_TOP,
            flags=SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
        )
        self._maximized_rect = (work_x, work_y, work_w, work_h)
        self._is_maximized = True
        self._apply_windows_dark_surface(fullscreen=False, maximized=True)
        self._notify_frontend_state()
        return True

    def _apply_win32_restore_normal(self, target_rect: tuple[int, int, int, int] | None = None) -> bool:
        hwnd = self._get_hwnd()
        if not hwnd or not _WIN32.available:
            return False

        self._ensure_normal_winforms_state()
        rx, ry, rw, rh = target_rect or self._restore_rect or (120, 80, 1360, 840)
        if rw < 640 or rh < 420:
            rw, rh = 1360, 840

        self._ignore_move_until = time.monotonic() + 0.45
        _WIN32.set_window_pos(
            hwnd,
            rx,
            ry,
            rw,
            rh,
            insert_after=HWND_NOTOPMOST,
            flags=SWP_FRAMECHANGED | SWP_SHOWWINDOW,
        )
        self._is_maximized = False
        self._maximized_rect = None
        self._apply_windows_dark_surface(fullscreen=False, maximized=False)
        self._notify_frontend_state()
        return True

    def _enter_win32_fullscreen(self) -> bool:
        hwnd = self._get_hwnd()
        if not hwnd or not _WIN32.available:
            return False
        rects = _WIN32.get_monitor_rects(hwnd)
        if not rects:
            return False
        mon_x, mon_y, mon_w, mon_h = rects[1]
        if mon_w <= 0 or mon_h <= 0:
            return False

        self._pre_fs_was_maximized = self._is_maximized
        if not self._is_maximized:
            cur = _WIN32.get_window_rect(hwnd)
            if cur:
                self._restore_rect = cur

        self._ensure_normal_winforms_state()

        style, exstyle = _WIN32.get_styles(hwnd)
        if self._saved_style is None:
            self._saved_style = style
            self._saved_exstyle = exstyle

        new_style = (style & ~WS_NONCLIENT_BORDER_MASK) | WS_POPUP
        new_exstyle = exstyle & ~WS_EX_NONCLIENT_EDGE_MASK
        _WIN32.set_styles(hwnd, new_style, new_exstyle)

        _WIN32.apply_dwm_attributes(hwnd, borderless=True, disable_round_corners=True)

        self._ignore_move_until = time.monotonic() + 0.45
        _WIN32.set_window_pos(
            hwnd,
            mon_x,
            mon_y,
            mon_w,
            mon_h,
            insert_after=HWND_TOP,
            flags=SWP_FRAMECHANGED | SWP_SHOWWINDOW,
        )
        self._is_fullscreen = True
        self._apply_windows_dark_surface(fullscreen=True, maximized=False)
        self._notify_frontend_state()
        return True

    def _exit_win32_fullscreen(self) -> bool:
        hwnd = self._get_hwnd()
        if not hwnd or not _WIN32.available:
            return False

        if self._saved_style is not None and self._saved_exstyle is not None:
            _WIN32.set_styles(hwnd, self._saved_style, self._saved_exstyle)
            self._saved_style = None
            self._saved_exstyle = None

        self._is_fullscreen = False
        if self._pre_fs_was_maximized:
            self._pre_fs_was_maximized = False
            self._is_maximized = False  # 防止覆盖已保存的 _restore_rect
            ok = self._apply_win32_maximize_work_area()
            if ok:
                return True
        self._pre_fs_was_maximized = False
        return self._apply_win32_restore_normal()

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
                # 若当前为全屏，先退出全屏并直接进入工作区最大化态（保留任务栏）
                self._pre_fs_was_maximized = True
                self.exit_fullscreen()
                return self._is_maximized

            if sys.platform == "win32" and _WIN32.available:
                if self._is_maximized:
                    self._apply_win32_restore_normal()
                else:
                    self._apply_win32_maximize_work_area()
                return self._is_maximized

            if self._is_maximized:
                self._window.restore()
                self._is_maximized = False
            else:
                self._window.maximize()
                self._is_maximized = True
            self._notify_frontend_state()
        except Exception as exc:
            self._logger.debug("toggle_maximize failed: %s", exc)
        return self._is_maximized

    def restore_for_drag(self, ratio_x: float = 0.5) -> bool:
        """最大化状态下拖拽标题栏时，立即还原常规窗口并按鼠标水平比例贴合指针"""
        if not self._window or not self._is_maximized or self._is_fullscreen:
            return False
        clamped_ratio = max(0.15, min(0.85, float(ratio_x)))
        try:
            if sys.platform == "win32" and _WIN32.available:
                hwnd = self._get_hwnd()
                rw, rh = (1360, 840)
                if self._restore_rect:
                    rw, rh = self._restore_rect[2], self._restore_rect[3]
                cursor = _WIN32.get_cursor_pos()
                rects = _WIN32.get_monitor_rects(hwnd) if hwnd else None
                if cursor:
                    nx = int(cursor[0] - rw * clamped_ratio)
                    ny = int(cursor[1] - 16)
                    if rects:
                        wx, wy, ww, wh = rects[0]
                        ny = max(wy, min(ny, wy + max(0, wh - 80)))
                        nx = max(wx - rw + 160, min(nx, wx + ww - 160))
                    return self._apply_win32_restore_normal((nx, ny, rw, rh))
                return self._apply_win32_restore_normal()

            self._window.restore()
            self._is_maximized = False
            self._notify_frontend_state()
            return True
        except Exception as exc:
            self._logger.debug("restore_for_drag failed: %s", exc)
            return False

    def toggle_fullscreen(self) -> bool:
        if not self._window:
            return self._is_fullscreen
        try:
            if sys.platform == "win32" and _WIN32.available:
                if self._is_fullscreen:
                    self._exit_win32_fullscreen()
                else:
                    self._enter_win32_fullscreen()
                return self._is_fullscreen

            self._window.toggle_fullscreen()
            self._is_fullscreen = not self._is_fullscreen
            self._notify_frontend_state()
        except Exception as exc:
            self._logger.debug("toggle_fullscreen failed: %s", exc)
        return self._is_fullscreen

    def exit_fullscreen(self) -> bool:
        if not self._window or not self._is_fullscreen:
            return False
        try:
            if sys.platform == "win32" and _WIN32.available:
                self._exit_win32_fullscreen()
                return self._is_fullscreen

            self._window.toggle_fullscreen()
            self._is_fullscreen = False
            self._notify_frontend_state()
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
        background_color=DARK_BG_HEX,
        frameless=True,
        easy_drag=False,
        resizable=True,
        js_api=window_api,
    )
    window_api.attach(window)

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
