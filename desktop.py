"""
Tsumugi 轻量桌面端单进程入口（PyWebView 无边框沉浸窗口 + 内置 FastAPI）
- 兼容 PyInstaller --noconsole 无控制台模式（避免 sys.stdout/stderr 为 None 导致 .isatty() 崩溃）
- 自动申请空闲本地端口，守护线程拉起内置 Uvicorn 服务
- 本地健康检查绕过系统代理，轮询 /api/system/version 就绪后在主线程打开无边框 WebView2 窗口
- 暴露 DesktopWindowApi：
  - 单一权威三态状态机（normal / maximized / fullscreen），彻底消除 Windows 全屏与缩放冲突
  - 8 方向自由拉伸（WinForms 8ms 高响应定时器 + Win32 SetWindowPos，最小尺寸锚定防平移）
  - 窗口几何尺寸与最大化状态持久化至 DATA_DIR/settings.json（启动时自动校验多屏边界）
"""

from __future__ import annotations

import asyncio
import base64
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
from typing import Any, Callable, Literal, Sequence
import urllib.error
import urllib.request

from backend.core.config import (
    DATA_DIR,
    FRONTEND_DIST_DIR,
    SETTINGS_JSON_PATH,
    ensure_data_dirs,
)

WindowMode = Literal["normal", "maximized", "fullscreen"]
PreFullscreenMode = Literal["normal", "maximized"]
ResizeEdge = Literal[
    "left",
    "right",
    "top",
    "bottom",
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
]
RectTuple = tuple[int, int, int, int]

VALID_RESIZE_EDGES: frozenset[str] = frozenset(
    {
        "left",
        "right",
        "top",
        "bottom",
        "top-left",
        "top-right",
        "bottom-left",
        "bottom-right",
    }
)

DEFAULT_NORMAL_RECT: RectTuple = (120, 80, 1360, 840)
MIN_WINDOW_WIDTH = 960
MIN_WINDOW_HEIGHT = 620
RESIZE_TIMER_INTERVAL_MS = 8

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

SW_MINIMIZE = 6
VK_LBUTTON = 0x01

WM_NCLBUTTONDOWN = 0x00A1
HTCAPTION = 2

MONITOR_DEFAULTTONEAREST = 0x00000002

DWMWA_USE_IMMERSIVE_DARK_MODE_PRE20H1 = 19
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35

DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2

_SETTINGS_FILE_LOCK = threading.Lock()


def is_valid_normal_rect(
    rect: RectTuple | None,
    *,
    min_sanity_w: int = 320,
    min_sanity_h: int = 240,
) -> bool:
    """校验物理矩形是否有效（排除 None、异常极小尺寸与 Win32 最小化哨兵坐标 -32000）"""
    if rect is None or len(rect) != 4:
        return False
    try:
        x, y, w, h = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
    except (TypeError, ValueError):
        return False
    if w < min_sanity_w or h < min_sanity_h:
        return False
    if x <= -30000 or y <= -30000 or x >= 30000 or y >= 30000:
        return False
    return True


def compute_effective_min_size(
    dpi: int = 96,
    work_rect: RectTuple | None = None,
    *,
    base_min_w: int = MIN_WINDOW_WIDTH,
    base_min_h: int = MIN_WINDOW_HEIGHT,
) -> tuple[int, int]:
    """按 DPI 计算有效最小物理宽高，并在小屏工作区下安全封顶避免超出屏幕"""
    safe_dpi = dpi if isinstance(dpi, int) and dpi >= 96 else 96
    scale = safe_dpi / 96.0
    min_w = max(base_min_w, int(round(base_min_w * scale)))
    min_h = max(base_min_h, int(round(base_min_h * scale)))

    if work_rect is not None and len(work_rect) == 4:
        _, _, work_w, work_h = work_rect
        if work_w > 0:
            cap_w = max(640, work_w - 40) if work_w >= 640 else work_w
            min_w = min(min_w, cap_w)
        if work_h > 0:
            cap_h = max(420, work_h - 40) if work_h >= 420 else work_h
            min_h = min(min_h, cap_h)

    return (int(min_w), int(min_h))


def compute_resized_rect(
    orig_rect: RectTuple,
    dx: int,
    dy: int,
    edge: str,
    *,
    min_w: int = MIN_WINDOW_WIDTH,
    min_h: int = MIN_WINDOW_HEIGHT,
) -> RectTuple:
    """
    8 方向自由拉伸纯计算：
    - 强制 nw >= min_w, nh >= min_h
    - 拖拽 left / top（含四角组合）触达最小尺寸时，严格锚定对侧 right / bottom 边界不动，防止窗口反向平移
    """
    norm_edge = str(edge or "").strip().lower()
    if norm_edge not in VALID_RESIZE_EDGES:
        raise ValueError(f"Unsupported resize edge: {edge!r}")

    orig_x, orig_y, orig_w, orig_h = (
        int(orig_rect[0]),
        int(orig_rect[1]),
        int(orig_rect[2]),
        int(orig_rect[3]),
    )
    orig_right = orig_x + orig_w
    orig_bottom = orig_y + orig_h

    eff_min_w = max(1, int(min_w))
    eff_min_h = max(1, int(min_h))

    nx, ny, nw, nh = orig_x, orig_y, orig_w, orig_h

    if "right" in norm_edge:
        nw = max(eff_min_w, orig_w + int(dx))
        nx = orig_x
    elif "left" in norm_edge:
        nw = max(eff_min_w, orig_w - int(dx))
        nx = orig_right - nw

    if "bottom" in norm_edge:
        nh = max(eff_min_h, orig_h + int(dy))
        ny = orig_y
    elif "top" in norm_edge:
        nh = max(eff_min_h, orig_h - int(dy))
        ny = orig_bottom - nh

    return (int(nx), int(ny), int(nw), int(nh))


def validate_window_rect_for_monitors(
    rect: RectTuple | None,
    monitor_work_rects: Sequence[RectTuple],
    *,
    min_w: int = MIN_WINDOW_WIDTH,
    min_h: int = MIN_WINDOW_HEIGHT,
) -> RectTuple | None:
    """
    校验已保存的窗口物理矩形是否落在当前可用显示器范围内：
    - 防止拔掉外接副屏后窗口坐标落在屏幕外不可见区域；
    - 命中可用显示器时，适度夹紧宽高与顶栏可见位置后返回；
    - 无任何显示器与其有效相交时返回 None（由调用方回退默认居中位置）。
    """
    if not is_valid_normal_rect(rect):
        return None
    assert rect is not None
    x, y, w, h = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])

    valid_monitors = [
        (int(m[0]), int(m[1]), int(m[2]), int(m[3]))
        for m in monitor_work_rects
        if len(m) == 4 and int(m[2]) > 0 and int(m[3]) > 0
    ]
    if not valid_monitors:
        if -16000 <= x <= 16000 and -16000 <= y <= 16000:
            return (x, y, max(w, min_w), max(h, min_h))
        return None

    best_mon: RectTuple | None = None
    best_area = 0
    min_overlap_x = min(200, max(120, w // 3))
    min_overlap_y = min(80, max(60, h // 3))

    for mon in valid_monitors:
        mx, my, mw, mh = mon
        ox = max(0, min(x + w, mx + mw) - max(x, mx))
        oy = max(0, min(y + h, my + mh) - max(y, my))
        titlebar_visible = (my - 8) <= y <= (my + mh - 48)
        if ox >= min_overlap_x and oy >= min_overlap_y and titlebar_visible:
            area = ox * oy
            if area > best_area:
                best_area = area
                best_mon = mon

    if best_mon is None:
        return None

    mx, my, mw, mh = best_mon
    eff_min_w = min(min_w, mw)
    eff_min_h = min(min_h, mh)
    nw = max(eff_min_w, min(w, mw))
    nh = max(eff_min_h, min(h, mh))

    ny = max(my, min(y, my + max(0, mh - 48)))
    nx = max(mx - nw + min(160, nw), min(x, mx + mw - min(160, nw)))
    return (int(nx), int(ny), int(nw), int(nh))


def load_window_geometry(settings_path: Path | None = None) -> dict[str, Any] | None:
    """从 DATA_DIR/settings.json 读取窗口几何尺寸与最大化状态"""
    fp = settings_path if settings_path is not None else SETTINGS_JSON_PATH
    if not fp.is_file():
        return None
    try:
        raw = json.loads(fp.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        geom = raw.get("window_geometry")
        if not isinstance(geom, dict):
            return None
        rect = (
            int(geom["x"]),
            int(geom["y"]),
            int(geom["width"]),
            int(geom["height"]),
        )
        if not is_valid_normal_rect(rect):
            return None
        return {
            "rect": rect,
            "maximized": bool(geom.get("maximized", False)),
        }
    except Exception:
        return None


def save_window_geometry(
    rect: RectTuple,
    *,
    maximized: bool,
    settings_path: Path | None = None,
) -> bool:
    """将窗口 normal 矩形与是否最大化原子写入 DATA_DIR/settings.json（完整保留其它字段）"""
    if not is_valid_normal_rect(rect):
        return False
    fp = settings_path if settings_path is not None else SETTINGS_JSON_PATH
    x, y, w, h = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
    payload = {
        "x": x,
        "y": y,
        "width": w,
        "height": h,
        "maximized": bool(maximized),
    }

    with _SETTINGS_FILE_LOCK:
        try:
            full_doc: dict[str, Any] = {}
            if fp.is_file():
                try:
                    existing = json.loads(fp.read_text(encoding="utf-8"))
                    if isinstance(existing, dict):
                        full_doc = existing
                except Exception:
                    full_doc = {}

            full_doc["window_geometry"] = payload
            fp.parent.mkdir(parents=True, exist_ok=True)
            tmp = fp.with_name(f"{fp.name}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps(full_doc, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, fp)
            return True
        except Exception:
            return False


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

            user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            user32.GetAsyncKeyState.restype = ctypes.c_short

            user32.IsIconic.argtypes = [hwnd_t]
            user32.IsIconic.restype = wintypes.BOOL

            user32.ShowWindow.argtypes = [hwnd_t, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL

            user32.ReleaseCapture.argtypes = []
            user32.ReleaseCapture.restype = wintypes.BOOL

            user32.SendMessageW.argtypes = [
                hwnd_t,
                wintypes.UINT,
                ctypes.c_size_t,
                ctypes.c_ssize_t,
            ]
            user32.SendMessageW.restype = ctypes.c_ssize_t

            user32.MonitorFromWindow.argtypes = [hwnd_t, wintypes.DWORD]
            user32.MonitorFromWindow.restype = hwnd_t

            user32.GetMonitorInfoW.argtypes = [hwnd_t, ctypes.POINTER(_Win32MonitorInfo)]
            user32.GetMonitorInfoW.restype = wintypes.BOOL

            self._monitor_enum_proc = ctypes.WINFUNCTYPE(
                wintypes.BOOL,
                hwnd_t,
                hwnd_t,
                ctypes.POINTER(_Win32Rect),
                ctypes.c_ssize_t,
            )
            user32.EnumDisplayMonitors.argtypes = [
                hwnd_t,
                ctypes.c_void_p,
                self._monitor_enum_proc,
                ctypes.c_ssize_t,
            ]
            user32.EnumDisplayMonitors.restype = wintypes.BOOL

            if hasattr(user32, "GetDpiForWindow"):
                user32.GetDpiForWindow.argtypes = [hwnd_t]
                user32.GetDpiForWindow.restype = wintypes.UINT
                self._get_dpi_for_window = user32.GetDpiForWindow
            else:
                self._get_dpi_for_window = None

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

    def is_iconic(self, hwnd: int) -> bool:
        if not self.available or not hwnd:
            return False
        try:
            return bool(self._user32.IsIconic(hwnd))
        except Exception:
            return False

    def minimize_window(self, hwnd: int) -> bool:
        if not self.available or not hwnd:
            return False
        try:
            return bool(self._user32.ShowWindow(hwnd, SW_MINIMIZE))
        except Exception:
            return False

    def get_window_rect(self, hwnd: int) -> RectTuple | None:
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

    def is_left_mouse_down(self) -> bool:
        if not self.available:
            return False
        try:
            return bool(int(self._user32.GetAsyncKeyState(VK_LBUTTON)) & 0x8000)
        except Exception:
            return False

    def get_dpi_for_window(self, hwnd: int) -> int:
        if not self.available or not hwnd or self._get_dpi_for_window is None:
            return 96
        try:
            dpi = int(self._get_dpi_for_window(hwnd))
            return dpi if dpi >= 96 else 96
        except Exception:
            return 96

    def begin_native_drag(self, hwnd: int) -> bool:
        """移交 Windows 原生窗口拖拽（必须在 WinForms UI 线程中调用；松手后返回）"""
        if not self.available or not hwnd:
            return False
        try:
            self._user32.ReleaseCapture()
            self._user32.SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)
            return True
        except Exception:
            return False

    def get_monitor_rects(
        self, hwnd: int
    ) -> tuple[RectTuple, RectTuple] | None:
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

    def get_all_monitor_work_rects(self) -> list[RectTuple]:
        """枚举当前所有可用显示器的物理工作区 rcWork"""
        if not self.available:
            return []
        results: list[RectTuple] = []

        def _enum_cb(hmon: Any, _hdc: Any, _lprect: Any, _lparam: Any) -> int:
            try:
                info = _Win32MonitorInfo()
                info.cbSize = ctypes.sizeof(_Win32MonitorInfo)
                if self._user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                    w = int(info.rcWork.right - info.rcWork.left)
                    h = int(info.rcWork.bottom - info.rcWork.top)
                    if w > 0 and h > 0:
                        results.append(
                            (int(info.rcWork.left), int(info.rcWork.top), w, h)
                        )
            except Exception:
                pass
            return 1

        try:
            cb = self._monitor_enum_proc(_enum_cb)
            self._user32.EnumDisplayMonitors(None, None, cb, 0)
        except Exception:
            pass
        return results

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


def _begin_invoke_on_winforms_ui_thread(form: Any, fn: Callable[[], None]) -> bool:
    """将动作异步派发到 WinForms UI 线程（不阻塞 js_api 工作线程，防止与 WebView2 桥死锁）"""
    if sys.platform != "win32" or form is None:
        return False
    try:
        if getattr(form, "IsDisposed", False):
            return False
        if not getattr(form, "IsHandleCreated", True):
            return False
        import System  # type: ignore[import-not-found]

        form.BeginInvoke(System.Action(fn))
        return True
    except Exception:
        return False


def _create_winforms_timer() -> Any:
    """在 Windows WinForms UI 线程中创建高响应定时器"""
    import System.Windows.Forms as WinForms  # type: ignore[import-not-found]

    return WinForms.Timer()


class DesktopWindowApi:
    """暴露给前端 window.pywebview.api 的桌面窗口控制与本地文件/目录选择桥接"""

    def __init__(
        self,
        logger: logging.Logger,
        *,
        win32: Any | None = None,
        settings_path: Path | None = None,
        platform: str | None = None,
        ui_dispatch: Callable[[Any, Callable[[], None]], bool] | None = None,
        timer_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._logger = logger
        self._win32: Any = win32 if win32 is not None else _WIN32
        self._settings_path: Path = settings_path if settings_path is not None else SETTINGS_JSON_PATH
        self._platform: str = platform if platform is not None else sys.platform
        self._ui_dispatch: Callable[[Any, Callable[[], None]], bool] = (
            ui_dispatch if ui_dispatch is not None else _begin_invoke_on_winforms_ui_thread
        )
        self._timer_factory: Callable[[], Any] = (
            timer_factory if timer_factory is not None else _create_winforms_timer
        )

        self._window: Any = None
        self._state_lock = threading.RLock()

        # 单一权威三态状态机
        self._mode: WindowMode = "normal"
        self._normal_rect: RectTuple = DEFAULT_NORMAL_RECT
        self._pre_fullscreen_mode: PreFullscreenMode = "normal"

        # 内部控制标志
        self._transition_seq: int = 0
        self._was_minimized: bool = False
        self._initial_geometry_applied: bool = False
        self._startup_valid_rect: RectTuple | None = None
        self._startup_maximized: bool = False
        self._saved_style: int | None = None
        self._saved_exstyle: int | None = None
        self._ignore_move_until: float = 0.0
        self._resize_timer: Any = None
        self._resize_tick_handler: Any = None
        self._form_resize_hooked: bool = False
        self._form_resize_handler: Any = None

    @property
    def mode(self) -> WindowMode:
        with self._state_lock:
            return self._mode

    @property
    def is_maximized(self) -> bool:
        with self._state_lock:
            return self._mode == "maximized"

    @property
    def is_fullscreen(self) -> bool:
        with self._state_lock:
            return self._mode == "fullscreen"

    @property
    def normal_rect(self) -> RectTuple:
        with self._state_lock:
            return self._normal_rect

    @property
    def pre_fullscreen_mode(self) -> PreFullscreenMode:
        with self._state_lock:
            return self._pre_fullscreen_mode

    def _is_win32_native(self) -> bool:
        return self._platform == "win32" and bool(getattr(self._win32, "available", False))

    def load_startup_geometry(self) -> tuple[RectTuple | None, bool]:
        """启动前读取 DATA_DIR/settings.json 并校验窗口矩形是否位于当前可用显示器内"""
        saved = load_window_geometry(self._settings_path)
        if not saved:
            self._startup_valid_rect = None
            self._startup_maximized = False
            return (None, False)

        monitors: list[RectTuple] = []
        if self._is_win32_native():
            try:
                monitors = self._win32.get_all_monitor_work_rects()
            except Exception:
                monitors = []

        valid_rect = validate_window_rect_for_monitors(saved["rect"], monitors)
        with self._state_lock:
            self._startup_valid_rect = valid_rect
            self._startup_maximized = bool(saved["maximized"])
            if valid_rect is not None:
                self._normal_rect = valid_rect
        return (valid_rect, self._startup_maximized)

    def persist_window_geometry(self) -> bool:
        """将当前 _normal_rect 与是否最大化持久化至 DATA_DIR/settings.json"""
        with self._state_lock:
            rect = self._normal_rect
            maximized = (
                self._mode == "maximized"
                or (self._mode == "fullscreen" and self._pre_fullscreen_mode == "maximized")
            )
        return save_window_geometry(
            rect,
            maximized=maximized,
            settings_path=self._settings_path,
        )

    def attach(self, window: Any) -> None:
        self._window = window
        events = getattr(window, "events", None)
        if events is None:
            return
        shown_ev = getattr(events, "shown", None)
        loaded_ev = getattr(events, "loaded", None)
        moved_ev = getattr(events, "moved", None)
        closing_ev = getattr(events, "closing", None)
        maximized_ev = getattr(events, "maximized", None)
        restored_ev = getattr(events, "restored", None)

        if shown_ev is not None:
            shown_ev += self.on_window_ready
        if loaded_ev is not None:
            loaded_ev += self.on_window_ready
        if moved_ev is not None:
            moved_ev += self._on_window_moved
        if closing_ev is not None:
            closing_ev += self._on_window_closing
        if restored_ev is not None:
            if self._platform == "win32":
                restored_ev += self._on_win32_window_restored
            else:
                restored_ev += self._on_native_restored
        if maximized_ev is not None and self._platform != "win32":
            maximized_ev += self._on_native_maximized

    def on_window_ready(self) -> None:
        """窗口显示/加载完成后加固深色表面、挂接恢复监听并恢复上次保存的几何尺寸"""
        if self._is_win32_native():
            form = self._get_native_form()
            should_apply_initial = False
            with self._state_lock:
                if not self._initial_geometry_applied:
                    self._initial_geometry_applied = True
                    should_apply_initial = True

            def _init_on_ui() -> None:
                self._hook_winforms_resize_on_ui_thread(form)
                self._configure_winforms_dark_surface_on_ui_thread(form)
                hwnd = self._get_hwnd_from_form(form)

                if should_apply_initial and hwnd:
                    if self._startup_valid_rect is not None:
                        with self._state_lock:
                            self._normal_rect = self._startup_valid_rect
                            if self._startup_maximized:
                                self._mode = "maximized"
                            else:
                                self._mode = "normal"
                        self._apply_mode_geometry_on_ui_thread(form, self.mode)
                    else:
                        cur = self._capture_current_rect_safe(hwnd)
                        with self._state_lock:
                            if cur is not None and self._mode == "normal":
                                self._normal_rect = cur
                            if self._startup_maximized:
                                self._mode = "maximized"
                        if self.mode == "maximized":
                            self._apply_mode_geometry_on_ui_thread(form, "maximized")
                        else:
                            self._win32.apply_dwm_attributes(
                                hwnd,
                                borderless=False,
                                disable_round_corners=False,
                            )
                elif hwnd:
                    is_edge_to_edge = self.mode in ("maximized", "fullscreen")
                    self._win32.apply_dwm_attributes(
                        hwnd,
                        borderless=is_edge_to_edge,
                        disable_round_corners=is_edge_to_edge,
                    )

                self._notify_frontend_state_async()

            if form is not None:
                self._ui_dispatch(form, _init_on_ui)
            else:
                _init_on_ui()
            return

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

    def _get_hwnd_from_form(self, form: Any) -> int:
        if self._platform != "win32":
            return 0
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
        return int(self._win32.find_window(title) or 0)

    def _get_hwnd(self) -> int:
        return self._get_hwnd_from_form(self._get_native_form())

    def _capture_current_rect_safe(self, hwnd: int) -> RectTuple | None:
        if not hwnd or not self._is_win32_native():
            return None
        if self._win32.is_iconic(hwnd):
            return None
        cur = self._win32.get_window_rect(hwnd)
        if not is_valid_normal_rect(cur):
            return None
        return cur

    def _ensure_normal_winforms_chrome_on_ui_thread(self, form: Any) -> None:
        """强制保持 FormBorderStyle.None 与 FormWindowState.Normal（绝不使用 WinForms 原生 Maximized）"""
        if self._platform != "win32" or form is None:
            return
        try:
            import System.Windows.Forms as WinForms  # type: ignore[import-not-found]

            if hasattr(form, "TopMost") and getattr(form, "TopMost", False):
                form.TopMost = False
            if getattr(form, "WindowState", None) != WinForms.FormWindowState.Normal:
                form.WindowState = WinForms.FormWindowState.Normal
            if hasattr(form, "FormBorderStyle"):
                border_none = getattr(WinForms.FormBorderStyle, "None")
                if getattr(form, "FormBorderStyle", None) != border_none:
                    form.FormBorderStyle = border_none
        except Exception:
            pass

    def _configure_winforms_dark_surface_on_ui_thread(self, form: Any) -> None:
        """在 UI 线程配置无边框深色宿主背景与 WebView2 零白边填充"""
        if self._platform != "win32" or form is None:
            return
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
            if hasattr(form, "TopMost"):
                form.TopMost = False

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

    def _hook_winforms_resize_on_ui_thread(self, form: Any) -> None:
        """监听 WinForms Resize：任务栏还原时恢复先前的 mode，拦截意外的原生 Maximized"""
        if self._platform != "win32" or form is None or self._form_resize_hooked:
            return
        resize_ev = getattr(form, "Resize", None)
        if resize_ev is None:
            return

        def _on_form_resize(_sender: Any, _args: Any) -> None:
            try:
                import System.Windows.Forms as WinForms  # type: ignore[import-not-found]

                state = getattr(form, "WindowState", None)
                if state == WinForms.FormWindowState.Minimized:
                    self._was_minimized = True
                    return

                if state == WinForms.FormWindowState.Maximized:
                    # 拦截系统快捷键触发的原生 Maximized，统一交由状态机以 rcWork 接管
                    form.WindowState = WinForms.FormWindowState.Normal
                    with self._state_lock:
                        if self._mode != "fullscreen":
                            self._mode = "maximized"
                    self._apply_mode_geometry_on_ui_thread(form, self.mode)
                    self._notify_frontend_state_async()
                    return

                if self._was_minimized and state == WinForms.FormWindowState.Normal:
                    self._was_minimized = False
                    self._apply_mode_geometry_on_ui_thread(form, self.mode)
                    self._notify_frontend_state_async()
            except Exception:
                pass

        try:
            self._form_resize_handler = _on_form_resize
            form.Resize += _on_form_resize
            self._form_resize_hooked = True
        except Exception:
            pass

    def _stop_resize_timer_on_ui_thread(self, *, save: bool = False) -> None:
        """在 UI 线程安全停止并释放 8 方向拉伸定时器"""
        timer = self._resize_timer
        self._resize_timer = None
        self._resize_tick_handler = None
        if timer is not None:
            try:
                timer.Stop()
            except Exception:
                pass
            try:
                timer.Dispose()
            except Exception:
                pass

        if save:
            hwnd = self._get_hwnd()
            cur = self._capture_current_rect_safe(hwnd)
            with self._state_lock:
                if self._mode == "normal" and cur is not None:
                    self._normal_rect = cur
            self.persist_window_geometry()

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

    def _notify_frontend_state_async(self) -> None:
        """从 WinForms UI 线程回调中安全通知前端（避免在 UI 线程上阻塞调用 evaluate_js）"""
        if self._ui_dispatch is _begin_invoke_on_winforms_ui_thread and self._platform == "win32":
            threading.Thread(target=self._notify_frontend_state, daemon=True).start()
        else:
            self._notify_frontend_state()

    def _on_native_maximized(self) -> None:
        with self._state_lock:
            self._mode = "maximized"
        self._notify_frontend_state()

    def _on_native_restored(self) -> None:
        with self._state_lock:
            if self._mode == "maximized":
                self._mode = "normal"
        self._notify_frontend_state()

    def _on_win32_window_restored(self) -> None:
        """pywebview restored 兜底回调：从任务栏恢复后确保回到最小化之前的 mode"""
        if not self._is_win32_native() or not self._was_minimized:
            return
        form = self._get_native_form()

        def _restore_prev_mode() -> None:
            hwnd = self._get_hwnd_from_form(form)
            if hwnd and self._win32.is_iconic(hwnd):
                return
            self._was_minimized = False
            self._apply_mode_geometry_on_ui_thread(form, self.mode)
            self._notify_frontend_state_async()

        if form is not None:
            self._ui_dispatch(form, _restore_prev_mode)
        else:
            _restore_prev_mode()

    def _on_window_moved(self, *_args: Any) -> None:
        """在 normal 态移动窗口时同步刷新 _normal_rect（绝不在 maximized/fullscreen 态覆写）"""
        if not self._is_win32_native():
            return
        if time.monotonic() < self._ignore_move_until:
            return
        if self.mode != "normal" or self._resize_timer is not None:
            return
        hwnd = self._get_hwnd()
        cur = self._capture_current_rect_safe(hwnd)
        if cur is not None:
            with self._state_lock:
                if self._mode == "normal":
                    self._normal_rect = cur

    def _on_window_closing(self) -> None:
        """窗口关闭前停止拉伸定时器并持久化最终窗口几何尺寸"""
        if self._is_win32_native():
            if self._resize_timer is not None:
                form = self._get_native_form()
                if form is not None:
                    self._ui_dispatch(
                        form, lambda: self._stop_resize_timer_on_ui_thread(save=False)
                    )
                else:
                    self._stop_resize_timer_on_ui_thread(save=False)
            if self.mode == "normal":
                hwnd = self._get_hwnd()
                cur = self._capture_current_rect_safe(hwnd)
                if cur is not None:
                    with self._state_lock:
                        if self._mode == "normal":
                            self._normal_rect = cur
        self.persist_window_geometry()

    def _apply_mode_geometry_on_ui_thread(
        self,
        form: Any,
        target_mode: WindowMode,
        *,
        override_normal_rect: RectTuple | None = None,
    ) -> bool:
        """
        在 WinForms UI 线程通过 Win32 SetWindowPos 执行单一权威几何切换：
        - 始终保持 FormBorderStyle.None 与 FormWindowState.Normal
        - normal: 应用 _normal_rect（或 override_normal_rect），恢复常规 DWM 与窗口样式
        - maximized: 应用当前显示器 rcWork（完整保留任务栏），应用无白边/无圆角 DWM
        - fullscreen: 应用当前显示器 rcMonitor（不设 TopMost，不干扰游戏与 Alt+Tab），剥离非客户区边框并应用无白边 DWM
        """
        if not self._is_win32_native():
            return False
        if form is not None and getattr(form, "IsDisposed", False):
            return False

        self._stop_resize_timer_on_ui_thread(save=False)
        self._ensure_normal_winforms_chrome_on_ui_thread(form)

        hwnd = self._get_hwnd_from_form(form)
        if not hwnd:
            return False

        rects = self._win32.get_monitor_rects(hwnd)

        if target_mode == "fullscreen":
            if not rects:
                return False
            mon_x, mon_y, mon_w, mon_h = rects[1]
            if mon_w <= 0 or mon_h <= 0:
                return False

            style, exstyle = self._win32.get_styles(hwnd)
            if self._saved_style is None:
                self._saved_style = style
                self._saved_exstyle = exstyle
            new_style = (style & ~WS_NONCLIENT_BORDER_MASK) | WS_POPUP
            new_exstyle = exstyle & ~WS_EX_NONCLIENT_EDGE_MASK
            self._win32.set_styles(hwnd, new_style, new_exstyle)

            self._win32.apply_dwm_attributes(
                hwnd,
                borderless=True,
                disable_round_corners=True,
            )
            self._ignore_move_until = time.monotonic() + 0.35
            self._win32.set_window_pos(
                hwnd,
                mon_x,
                mon_y,
                mon_w,
                mon_h,
                insert_after=HWND_TOP,
                flags=SWP_FRAMECHANGED | SWP_SHOWWINDOW,
            )
            self._configure_winforms_dark_surface_on_ui_thread(form)
            return True

        # 退出全屏回到 normal / maximized 时先恢复原 Win32 样式
        if self._saved_style is not None and self._saved_exstyle is not None:
            self._win32.set_styles(hwnd, self._saved_style, self._saved_exstyle)
            self._saved_style = None
            self._saved_exstyle = None

        if target_mode == "maximized":
            if not rects:
                return False
            work_x, work_y, work_w, work_h = rects[0]
            if work_w <= 0 or work_h <= 0:
                return False

            self._ignore_move_until = time.monotonic() + 0.35
            self._win32.set_window_pos(
                hwnd,
                work_x,
                work_y,
                work_w,
                work_h,
                insert_after=HWND_TOP,
                flags=SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
            )
            self._win32.apply_dwm_attributes(
                hwnd,
                borderless=True,
                disable_round_corners=True,
            )
            self._configure_winforms_dark_surface_on_ui_thread(form)
            return True

        # target_mode == "normal"
        with self._state_lock:
            target_rect = override_normal_rect or self._normal_rect or DEFAULT_NORMAL_RECT
        rx, ry, rw, rh = target_rect
        if not is_valid_normal_rect((rx, ry, rw, rh)):
            rx, ry, rw, rh = DEFAULT_NORMAL_RECT

        self._ignore_move_until = time.monotonic() + 0.35
        self._win32.set_window_pos(
            hwnd,
            rx,
            ry,
            rw,
            rh,
            insert_after=HWND_NOTOPMOST,
            flags=SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
        )
        self._win32.apply_dwm_attributes(
            hwnd,
            borderless=False,
            disable_round_corners=False,
        )
        self._configure_winforms_dark_surface_on_ui_thread(form)
        return True

    def _transition_to_mode(
        self,
        target_mode: WindowMode,
        *,
        prev_mode: WindowMode,
        override_normal_rect: RectTuple | None = None,
        persist: bool = True,
    ) -> None:
        """
        执行三态转换：
        - 仅当 prev_mode == "normal" 且离开 normal 态时，将当前 GetWindowRect 记录至 _normal_rect；
        - 通过 form.BeginInvoke 在 WinForms UI 线程用 Win32 SetWindowPos 执行实际几何切换；
        - 统一派发前端状态事件 {is_desktop, mode, is_maximized, is_fullscreen}。
        """
        with self._state_lock:
            if self._is_win32_native() and prev_mode == "normal" and target_mode != "normal":
                hwnd = self._get_hwnd()
                cur = self._capture_current_rect_safe(hwnd)
                if cur is not None:
                    self._normal_rect = cur

            if override_normal_rect is not None and is_valid_normal_rect(override_normal_rect):
                self._normal_rect = override_normal_rect

            self._mode = target_mode
            self._transition_seq += 1
            seq = self._transition_seq

        if self._is_win32_native():
            form = self._get_native_form()

            def _apply_ui() -> None:
                with self._state_lock:
                    if seq != self._transition_seq:
                        return
                self._apply_mode_geometry_on_ui_thread(
                    form,
                    target_mode,
                    override_normal_rect=override_normal_rect,
                )

            dispatched = False
            if form is not None:
                dispatched = self._ui_dispatch(form, _apply_ui)
            if not dispatched:
                _apply_ui()
        elif self._window is not None:
            # 非 Windows 平台优雅回退 pywebview 内置接口
            try:
                if target_mode == "fullscreen" and prev_mode != "fullscreen":
                    self._window.toggle_fullscreen()
                elif prev_mode == "fullscreen" and target_mode != "fullscreen":
                    self._window.toggle_fullscreen()
                    if target_mode == "maximized":
                        self._window.maximize()
                    else:
                        self._window.restore()
                elif target_mode == "maximized":
                    self._window.maximize()
                elif target_mode == "normal":
                    self._window.restore()
            except Exception as exc:
                self._logger.debug("non-win32 transition %s->%s failed: %s", prev_mode, target_mode, exc)

        if persist:
            self.persist_window_geometry()
        self._notify_frontend_state()

    def minimize(self) -> bool:
        """最小化窗口（短暂设为 Minimized，绝不改动 mode；任务栏恢复后自动回到之前的 mode）"""
        if not self._window:
            return False
        try:
            if self._is_win32_native():
                form = self._get_native_form()
                self._was_minimized = True

                def _do_minimize() -> None:
                    self._stop_resize_timer_on_ui_thread(save=False)
                    if form is not None:
                        try:
                            import System.Windows.Forms as WinForms  # type: ignore[import-not-found]

                            form.WindowState = WinForms.FormWindowState.Minimized
                            return
                        except Exception:
                            pass
                    hwnd = self._get_hwnd_from_form(form)
                    if hwnd:
                        self._win32.minimize_window(hwnd)

                if form is not None and self._ui_dispatch(form, _do_minimize):
                    return True
                _do_minimize()
                return True

            self._window.minimize()
            return True
        except Exception as exc:
            self._logger.debug("minimize failed: %s", exc)
            return False

    def toggle_maximize(self) -> bool:
        """
        三态无冲突最大化/还原切换：
        - fullscreen -> maximized（应用 rcWork，彻底清除全屏态）
        - normal -> maximized（先保存 _normal_rect，再贴合当前显示器 rcWork）
        - maximized -> normal（还原 _normal_rect）
        """
        if not self._window:
            return self.is_maximized
        try:
            with self._state_lock:
                prev_mode = self._mode
                if prev_mode == "fullscreen":
                    target_mode: WindowMode = "maximized"
                elif prev_mode == "normal":
                    target_mode = "maximized"
                else:
                    target_mode = "normal"

            self._transition_to_mode(target_mode, prev_mode=prev_mode)
        except Exception as exc:
            self._logger.debug("toggle_maximize failed: %s", exc)
        return self.is_maximized

    def toggle_fullscreen(self) -> bool:
        """
        三态无冲突全屏切换：
        - 若当前非全屏：记录 _pre_fullscreen_mode = mode（若 normal 则保存 _normal_rect），覆盖 rcMonitor 设 mode="fullscreen"
        - 若当前全屏：按 _pre_fullscreen_mode 精确恢复 maximized(rcWork) 或 normal(_normal_rect)
        """
        if not self._window:
            return self.is_fullscreen
        try:
            with self._state_lock:
                prev_mode = self._mode
                if prev_mode == "fullscreen":
                    target_mode: WindowMode = self._pre_fullscreen_mode
                else:
                    self._pre_fullscreen_mode = prev_mode
                    target_mode = "fullscreen"

            self._transition_to_mode(target_mode, prev_mode=prev_mode)
        except Exception as exc:
            self._logger.debug("toggle_fullscreen failed: %s", exc)
        return self.is_fullscreen

    def exit_fullscreen(self) -> bool:
        """退出全屏并精确回到进入全屏前的状态（normal 或 maximized）"""
        if not self._window:
            return False
        with self._state_lock:
            if self._mode != "fullscreen":
                return False
            target_mode: WindowMode = self._pre_fullscreen_mode

        try:
            self._transition_to_mode(target_mode, prev_mode="fullscreen")
        except Exception as exc:
            self._logger.debug("exit_fullscreen failed: %s", exc)
        return self.is_fullscreen

    def start_drag(self, cursor_ratio_x: float = 0.5) -> bool:
        """
        Windows 无边框窗口原生拖拽入口（由前端顶栏 4px 拖动阈值触发）：
        - fullscreen 态忽略拖拽；
        - maximized 态先按鼠标水平比例平滑切回 normal 尺寸，再执行 ReleaseCapture + WM_NCLBUTTONDOWN(HTCAPTION)；
        - 拖拽松手后立即采集最终 GetWindowRect 更新 _normal_rect 并落盘至 settings.json。
        """
        if not self._window or self.mode == "fullscreen":
            return False
        if not self._is_win32_native():
            return False

        try:
            ratio = max(0.1, min(0.9, float(cursor_ratio_x)))
        except (TypeError, ValueError):
            ratio = 0.5

        form = self._get_native_form()
        if form is None:
            return False

        def _perform_native_drag() -> None:
            try:
                if self.mode == "fullscreen" or getattr(form, "IsDisposed", False):
                    return

                self._stop_resize_timer_on_ui_thread(save=False)
                hwnd = self._get_hwnd_from_form(form)
                if not hwnd:
                    return

                if self.mode == "maximized":
                    self._ensure_normal_winforms_chrome_on_ui_thread(form)
                    with self._state_lock:
                        _, _, saved_w, saved_h = self._normal_rect
                    rw, rh = (
                        (saved_w, saved_h)
                        if saved_w >= MIN_WINDOW_WIDTH and saved_h >= MIN_WINDOW_HEIGHT
                        else (DEFAULT_NORMAL_RECT[2], DEFAULT_NORMAL_RECT[3])
                    )

                    cursor = self._win32.get_cursor_pos()
                    rects = self._win32.get_monitor_rects(hwnd)
                    if cursor:
                        cx, cy = cursor
                        new_x = int(cx - rw * ratio)
                        new_y = int(cy - 18)
                        if rects:
                            wx, wy, ww, wh = rects[0]
                            new_y = max(wy, min(new_y, wy + max(0, wh - 80)))
                            new_x = max(wx - rw + 160, min(new_x, wx + ww - 160))
                    else:
                        with self._state_lock:
                            new_x, new_y = self._normal_rect[0], self._normal_rect[1]

                    with self._state_lock:
                        self._mode = "normal"
                        self._normal_rect = (new_x, new_y, rw, rh)
                        self._transition_seq += 1

                    self._ignore_move_until = time.monotonic() + 0.35
                    self._win32.set_window_pos(
                        hwnd,
                        new_x,
                        new_y,
                        rw,
                        rh,
                        insert_after=HWND_NOTOPMOST,
                        flags=SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
                    )
                    self._win32.apply_dwm_attributes(
                        hwnd,
                        borderless=False,
                        disable_round_corners=False,
                    )
                    self._notify_frontend_state_async()

                self._win32.begin_native_drag(hwnd)

                # 原生拖拽消息循环返回（用户松手）后，同步记录最终 normal 矩形并落盘
                if self.mode == "normal":
                    final_rect = self._capture_current_rect_safe(hwnd)
                    if final_rect is not None:
                        with self._state_lock:
                            if self._mode == "normal":
                                self._normal_rect = final_rect
                        self.persist_window_geometry()
            except Exception as exc:
                self._logger.debug("start_drag on UI thread failed: %s", exc)

        return self._ui_dispatch(form, _perform_native_drag)

    def restore_for_drag(self, ratio_x: float = 0.5) -> bool:
        """最大化状态下拖拽标题栏时的兼容还原接口"""
        if not self._window or self.mode != "maximized":
            return False
        clamped_ratio = max(0.15, min(0.85, float(ratio_x)))
        try:
            if self._is_win32_native():
                hwnd = self._get_hwnd()
                with self._state_lock:
                    _, _, rw, rh = self._normal_rect
                if rw < MIN_WINDOW_WIDTH or rh < MIN_WINDOW_HEIGHT:
                    rw, rh = DEFAULT_NORMAL_RECT[2], DEFAULT_NORMAL_RECT[3]

                cursor = self._win32.get_cursor_pos()
                rects = self._win32.get_monitor_rects(hwnd) if hwnd else None
                target_rect: RectTuple | None = None
                if cursor:
                    nx = int(cursor[0] - rw * clamped_ratio)
                    ny = int(cursor[1] - 16)
                    if rects:
                        wx, wy, ww, wh = rects[0]
                        ny = max(wy, min(ny, wy + max(0, wh - 80)))
                        nx = max(wx - rw + 160, min(nx, wx + ww - 160))
                    target_rect = (nx, ny, rw, rh)

                self._transition_to_mode(
                    "normal",
                    prev_mode="maximized",
                    override_normal_rect=target_rect,
                )
                return True

            self._transition_to_mode("normal", prev_mode="maximized")
            return True
        except Exception as exc:
            self._logger.debug("restore_for_drag failed: %s", exc)
            return False

    def start_resize(self, edge: str) -> bool:
        """
        8 方向无边框窗口自由拉伸入口：
        - 仅在 mode == "normal" 时响应，且 edge 属于合法的 8 方向之一；
        - 通过 form.BeginInvoke 在 WinForms UI 线程启动 8ms 高响应定时器；
        - 每次 tick 检测 GetAsyncKeyState(0x01) & 0x8000，松手立即停止释放并更新 _normal_rect 落盘；
        - 严格强制 DPI 保护最小尺寸，并在拖动 left / top 边时锚定对侧 right / bottom 边界不动。
        """
        norm_edge = str(edge or "").strip().lower()
        if norm_edge not in VALID_RESIZE_EDGES:
            return False
        if not self._window or self.mode != "normal":
            return False
        if not self._is_win32_native():
            return False

        form = self._get_native_form()
        if form is None:
            return False

        def _begin_resize_on_ui() -> None:
            try:
                if self.mode != "normal" or getattr(form, "IsDisposed", False):
                    return

                self._stop_resize_timer_on_ui_thread(save=False)
                if not self._win32.is_left_mouse_down():
                    return

                hwnd = self._get_hwnd_from_form(form)
                if not hwnd:
                    return

                start_cursor = self._win32.get_cursor_pos()
                orig_rect = self._capture_current_rect_safe(hwnd)
                if start_cursor is None or orig_rect is None:
                    return

                start_cx, start_cy = start_cursor
                dpi = self._win32.get_dpi_for_window(hwnd)
                rects = self._win32.get_monitor_rects(hwnd)
                work_rect = rects[0] if rects else None
                min_w, min_h = compute_effective_min_size(dpi, work_rect)

                timer = self._timer_factory()
                timer.Interval = RESIZE_TIMER_INTERVAL_MS
                last_rect: list[RectTuple] = [orig_rect]

                def _on_tick(_sender: Any, _args: Any) -> None:
                    try:
                        if self.mode != "normal" or getattr(form, "IsDisposed", False):
                            self._stop_resize_timer_on_ui_thread(save=False)
                            return

                        if not self._win32.is_left_mouse_down():
                            final_rect = self._capture_current_rect_safe(hwnd) or last_rect[0]
                            self._stop_resize_timer_on_ui_thread(save=False)
                            with self._state_lock:
                                if self._mode == "normal" and is_valid_normal_rect(final_rect):
                                    self._normal_rect = final_rect
                            self.persist_window_geometry()
                            return

                        cur_cursor = self._win32.get_cursor_pos()
                        if cur_cursor is None:
                            return
                        dx = cur_cursor[0] - start_cx
                        dy = cur_cursor[1] - start_cy
                        next_rect = compute_resized_rect(
                            orig_rect,
                            dx,
                            dy,
                            norm_edge,
                            min_w=min_w,
                            min_h=min_h,
                        )
                        if next_rect != last_rect[0]:
                            last_rect[0] = next_rect
                            self._win32.set_window_pos(
                                hwnd,
                                next_rect[0],
                                next_rect[1],
                                next_rect[2],
                                next_rect[3],
                                insert_after=0,
                                flags=SWP_NOZORDER | SWP_NOACTIVATE,
                            )
                    except Exception as tick_exc:
                        self._logger.debug("resize timer tick failed: %s", tick_exc)
                        self._stop_resize_timer_on_ui_thread(save=False)

                self._resize_timer = timer
                self._resize_tick_handler = _on_tick
                timer.Tick += _on_tick
                timer.Start()
            except Exception as exc:
                self._logger.debug("start_resize on UI thread failed: %s", exc)
                self._stop_resize_timer_on_ui_thread(save=False)

        return self._ui_dispatch(form, _begin_resize_on_ui)

    def close(self) -> bool:
        if not self._window:
            return False
        try:
            self._on_window_closing()
            self._window.destroy()
            return True
        except Exception as exc:
            self._logger.debug("close window failed: %s", exc)
            return False

    def get_window_state(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "is_desktop": True,
                "mode": self._mode,
                "is_fullscreen": self._mode == "fullscreen",
                "is_maximized": self._mode == "maximized",
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
            return str(result[0]) if not isinstance(result, str) else result
        except Exception as exc:
            self._logger.debug("pick_folder failed: %s", exc)
            return ""

    def select_backup_save_path(self, default_name: str = "") -> str:
        """弹出原生保存文件对话框，供桌面端整库备份直写导出 (.zip)"""
        if not self._window:
            return ""
        try:
            from datetime import datetime
            import webview

            clean_name = Path(str(default_name or "").strip()).name
            if not clean_name:
                clean_name = f"Tsumugi-Backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
            elif not clean_name.lower().endswith(".zip"):
                clean_name = f"{clean_name}.zip"

            dialog_type = getattr(webview, "FileDialog", None)
            save_flag = dialog_type.SAVE if dialog_type else webview.SAVE_DIALOG
            result = self._window.create_file_dialog(
                save_flag,
                save_filename=clean_name,
                file_types=("Tsumugi Backup (*.zip)", "All files (*.*)"),
            )
            if not result:
                return ""
            raw_path = result if isinstance(result, str) else str(result[0])
            if not raw_path.strip():
                return ""
            chosen = Path(raw_path.strip())
            if chosen.suffix.lower() != ".zip":
                chosen = chosen.with_suffix(".zip")
            return str(chosen)
        except Exception as exc:
            self._logger.debug("select_backup_save_path failed: %s", exc)
            return ""

    def select_backup_open_path(self) -> str:
        """弹出原生打开文件对话框，供桌面端选择整库备份压缩包 (.zip) 恢复"""
        if not self._window:
            return ""
        try:
            import webview

            dialog_type = getattr(webview, "FileDialog", None)
            open_flag = dialog_type.OPEN if dialog_type else webview.OPEN_DIALOG
            result = self._window.create_file_dialog(
                open_flag,
                allow_multiple=False,
                file_types=("Tsumugi Backup (*.zip)", "All files (*.*)"),
            )
            if not result:
                return ""
            raw_path = result if isinstance(result, str) else str(result[0])
            return raw_path.strip()
        except Exception as exc:
            self._logger.debug("select_backup_open_path failed: %s", exc)
            return ""

    def select_save_file_path(
        self,
        default_name: str = "",
        file_types: list[str] | None = None,
        default_ext: str = "",
    ) -> str:
        """弹出原生保存文件对话框，支持 PNG 图片、Markdown 与纯文本等任意格式导出"""
        if not self._window:
            return ""
        try:
            import webview

            clean_ext = str(default_ext or "").strip()
            if clean_ext and not clean_ext.startswith("."):
                clean_ext = f".{clean_ext}"

            clean_name = Path(str(default_name or "").strip()).name or "tsumugi-export"
            if clean_ext and not clean_name.lower().endswith(clean_ext.lower()):
                clean_name = f"{clean_name}{clean_ext}"

            ft = tuple(file_types) if file_types else ("All files (*.*)",)
            dialog_type = getattr(webview, "FileDialog", None)
            save_flag = dialog_type.SAVE if dialog_type else webview.SAVE_DIALOG
            result = self._window.create_file_dialog(
                save_flag,
                save_filename=clean_name,
                file_types=ft,
            )
            if not result:
                return ""
            raw_path = result if isinstance(result, str) else str(result[0])
            if not raw_path.strip():
                return ""
            chosen = Path(raw_path.strip())
            if clean_ext and chosen.suffix.lower() != clean_ext.lower():
                chosen = chosen.with_suffix(clean_ext)
            return str(chosen)
        except Exception as exc:
            self._logger.debug("select_save_file_path failed: %s", exc)
            return ""

    def write_export_file(self, target_path: str, content_base64: str) -> dict[str, Any]:
        """将前端生成的 Base64 字节数据安全写入用户选定的目标路径（原子替换防半截文件）"""
        raw_target = str(target_path or "").strip()
        if not raw_target:
            return {"saved": False, "detail": "未指定保存路径"}
        try:
            raw_bytes = base64.b64decode(str(content_base64 or ""), validate=True)
        except Exception as exc:
            return {"saved": False, "detail": f"导出数据编码无效: {exc}"}

        try:
            dest = Path(raw_target).expanduser()
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
            tmp_path.write_bytes(raw_bytes)
            os.replace(tmp_path, dest)
            return {
                "saved": True,
                "path": str(dest),
                "size_bytes": len(raw_bytes),
            }
        except Exception as exc:
            self._logger.debug("write_export_file failed: %s", exc)
            return {"saved": False, "detail": f"写入导出文件失败: {exc}"}


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
    saved_rect, saved_maximized = window_api.load_startup_geometry()
    if saved_rect is not None:
        logger.info(
            "读取已保存窗口几何: rect=%s, maximized=%s",
            saved_rect,
            saved_maximized,
        )

    create_kwargs: dict[str, Any] = {
        "title": "Tsumugi",
        "url": f"http://127.0.0.1:{port}",
        "width": DEFAULT_NORMAL_RECT[2],
        "height": DEFAULT_NORMAL_RECT[3],
        "min_size": (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT),
        "background_color": DARK_BG_HEX,
        "frameless": True,
        "easy_drag": False,
        "resizable": True,
        "js_api": window_api,
    }
    if saved_rect is not None and sys.platform != "win32":
        # 非 Windows 平台直接通过 pywebview 初始参数恢复；Windows 由 on_window_ready 用物理像素 SetWindowPos 精确应用
        create_kwargs["x"] = saved_rect[0]
        create_kwargs["y"] = saved_rect[1]
        create_kwargs["width"] = saved_rect[2]
        create_kwargs["height"] = saved_rect[3]

    window = webview.create_window(**create_kwargs)
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
        window_api.persist_window_geometry()
        server.should_exit = True
        try:
            asyncio.run(process_tracker.shutdown_flush())
        except Exception:
            pass
        server_thread.join(timeout=3.0)
        os._exit(0)


if __name__ == "__main__":
    main()
