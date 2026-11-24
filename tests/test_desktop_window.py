from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import sys
import tempfile
import unittest
from typing import Any, Callable

import desktop
from desktop import (
    DEFAULT_NORMAL_RECT,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    RESIZE_TIMER_INTERVAL_MS,
    SWP_NOACTIVATE,
    SWP_NOZORDER,
    VALID_RESIZE_EDGES,
    DesktopWindowApi,
    RectTuple,
    compute_effective_min_size,
    compute_resized_rect,
    is_valid_normal_rect,
    load_window_geometry,
    save_window_geometry,
    validate_window_rect_for_monitors,
)


class _FakeEvent:
    def __init__(self) -> None:
        self._handlers: list[Callable[..., Any]] = []

    def __iadd__(self, handler: Callable[..., Any]) -> _FakeEvent:
        self._handlers.append(handler)
        return self

    def fire(self, *args: Any, **kwargs: Any) -> None:
        for h in list(self._handlers):
            h(*args, **kwargs)


class _FakeWindowEvents:
    def __init__(self) -> None:
        self.shown = _FakeEvent()
        self.loaded = _FakeEvent()
        self.moved = _FakeEvent()
        self.closing = _FakeEvent()
        self.maximized = _FakeEvent()
        self.restored = _FakeEvent()


class _FakeNativeForm:
    def __init__(self, hwnd: int = 0x123456) -> None:
        self.Handle = hwnd
        self.IsDisposed = False
        self.IsHandleCreated = True
        self.TopMost = False
        self.WindowState = "Normal"
        self.FormBorderStyle = "None"


class _FakeWindow:
    def __init__(self, form: _FakeNativeForm | None = None) -> None:
        self.title = "Tsumugi"
        self.native = form if form is not None else _FakeNativeForm()
        self.events = _FakeWindowEvents()
        self.js_calls: list[str] = []
        self.dispatched_states: list[dict[str, Any]] = []
        self.destroyed = False
        self.minimize_calls = 0

    def evaluate_js(self, script: str) -> None:
        self.js_calls.append(script)
        m = re.search(r"detail:\s*(\{.*?\})\s*\}", script)
        if m:
            self.dispatched_states.append(json.loads(m.group(1)))

    def minimize(self) -> None:
        self.minimize_calls += 1

    def destroy(self) -> None:
        self.destroyed = True


class _FakeTimer:
    def __init__(self) -> None:
        self.Interval: int = 0
        self.Tick = _FakeEvent()
        self.started = False
        self.stopped = False
        self.disposed = False

    def Start(self) -> None:
        self.started = True
        self.stopped = False

    def Stop(self) -> None:
        self.started = False
        self.stopped = True

    def Dispose(self) -> None:
        self.disposed = True

    def fire_tick(self) -> None:
        if self.started and not self.disposed:
            self.Tick.fire(self, None)


class _FakeWin32:
    """确定性 Win32 桩实现：在 Linux/WSL2 上完整演练 Windows 三态状态机与 8 方向拉伸逻辑"""

    def __init__(
        self,
        *,
        initial_rect: RectTuple = (150, 90, 1280, 800),
        work_rect: RectTuple = (0, 0, 1920, 1040),
        mon_rect: RectTuple = (0, 0, 1920, 1080),
        all_work_rects: list[RectTuple] | None = None,
        dpi: int = 96,
    ) -> None:
        self.available = True
        self.current_rect: RectTuple = initial_rect
        self.work_rect: RectTuple = work_rect
        self.mon_rect: RectTuple = mon_rect
        self.all_work_rects: list[RectTuple] = (
            list(all_work_rects) if all_work_rects is not None else [work_rect]
        )
        self.dpi = dpi
        self.iconic = False
        self.cursor_pos: tuple[int, int] = (500, 300)
        self.left_mouse_down = True
        self.style = 0x16CF0000
        self.exstyle = 0x00000100
        self.set_window_pos_calls: list[dict[str, Any]] = []
        self.dwm_calls: list[dict[str, Any]] = []
        self.drag_end_rect: RectTuple | None = None
        self.drag_calls = 0
        self.minimize_calls = 0

    def find_window(self, _title: str) -> int:
        return 0x123456

    def is_iconic(self, _hwnd: int) -> bool:
        return self.iconic

    def minimize_window(self, _hwnd: int) -> bool:
        self.minimize_calls += 1
        self.iconic = True
        return True

    def get_window_rect(self, _hwnd: int) -> RectTuple | None:
        if self.iconic:
            return (-32000, -32000, 160, 28)
        return self.current_rect

    def get_cursor_pos(self) -> tuple[int, int] | None:
        return self.cursor_pos

    def is_left_mouse_down(self) -> bool:
        return self.left_mouse_down

    def get_dpi_for_window(self, _hwnd: int) -> int:
        return self.dpi

    def begin_native_drag(self, _hwnd: int) -> bool:
        self.drag_calls += 1
        if self.drag_end_rect is not None:
            self.current_rect = self.drag_end_rect
        return True

    def get_monitor_rects(self, _hwnd: int) -> tuple[RectTuple, RectTuple]:
        return (self.work_rect, self.mon_rect)

    def get_all_monitor_work_rects(self) -> list[RectTuple]:
        return list(self.all_work_rects)

    def get_styles(self, _hwnd: int) -> tuple[int, int]:
        return (self.style, self.exstyle)

    def set_styles(self, _hwnd: int, style: int, exstyle: int) -> None:
        self.style = style
        self.exstyle = exstyle

    def set_window_pos(
        self,
        hwnd: int,
        x: int,
        y: int,
        width: int,
        height: int,
        *,
        insert_after: int = 0,
        flags: int = 0,
    ) -> bool:
        self.current_rect = (int(x), int(y), int(width), int(height))
        self.set_window_pos_calls.append(
            {
                "hwnd": hwnd,
                "rect": self.current_rect,
                "insert_after": insert_after,
                "flags": flags,
            }
        )
        return True

    def apply_dwm_attributes(
        self,
        hwnd: int,
        *,
        borderless: bool = False,
        disable_round_corners: bool = False,
    ) -> None:
        self.dwm_calls.append(
            {
                "hwnd": hwnd,
                "borderless": borderless,
                "disable_round_corners": disable_round_corners,
            }
        )


class CrossPlatformImportGuardTestCase(unittest.TestCase):
    """验证 desktop.py 在 Linux / WSL2 下可无报错导入且跨平台守卫生效"""

    def test_linux_import_and_win32_helper_guard(self) -> None:
        if sys.platform != "win32":
            self.assertFalse(desktop._WIN32.available)
            self.assertEqual(desktop._WIN32.get_all_monitor_work_rects(), [])
            self.assertFalse(desktop._WIN32.is_left_mouse_down())
            self.assertEqual(desktop._WIN32.get_dpi_for_window(123), 96)
        self.assertEqual(len(VALID_RESIZE_EDGES), 8)


class WindowStateMachineMatrixTestCase(unittest.TestCase):
    """完整覆盖 Windows 三态状态机转换矩阵（normal ↔ maximized ↔ fullscreen）与拖拽/最小化边界"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self._tmp.name) / "settings.json"
        self.win32 = _FakeWin32(
            initial_rect=(180, 110, 1280, 780),
            work_rect=(0, 0, 1920, 1040),
            mon_rect=(0, 0, 1920, 1080),
        )
        self.ui_dispatch_count = 0

        def _sync_dispatch(_form: Any, fn: Callable[[], None]) -> bool:
            self.ui_dispatch_count += 1
            fn()
            return True

        self.timers: list[_FakeTimer] = []

        def _make_timer() -> _FakeTimer:
            t = _FakeTimer()
            self.timers.append(t)
            return t

        self.window = _FakeWindow()
        self.api = DesktopWindowApi(
            logging.getLogger("test.desktop"),
            win32=self.win32,
            settings_path=self.settings_path,
            platform="win32",
            ui_dispatch=_sync_dispatch,
            timer_factory=_make_timer,
        )
        self.api.attach(self.window)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_normal_to_maximized_and_back_preserves_normal_rect(self) -> None:
        self.assertEqual(self.api.mode, "normal")
        self.assertEqual(self.win32.current_rect, (180, 110, 1280, 780))

        # normal -> maximized
        res_max = self.api.toggle_maximize()
        self.assertTrue(res_max)
        self.assertEqual(self.api.mode, "maximized")
        self.assertTrue(self.api.is_maximized)
        self.assertFalse(self.api.is_fullscreen)
        self.assertEqual(self.api.normal_rect, (180, 110, 1280, 780))
        self.assertEqual(self.win32.current_rect, (0, 0, 1920, 1040))
        self.assertGreaterEqual(self.ui_dispatch_count, 1)
        self.assertEqual(
            self.window.dispatched_states[-1],
            {
                "is_desktop": True,
                "mode": "maximized",
                "is_maximized": True,
                "is_fullscreen": False,
            },
        )

        # maximized -> normal
        res_norm = self.api.toggle_maximize()
        self.assertFalse(res_norm)
        self.assertEqual(self.api.mode, "normal")
        self.assertFalse(self.api.is_maximized)
        self.assertFalse(self.api.is_fullscreen)
        self.assertEqual(self.win32.current_rect, (180, 110, 1280, 780))
        self.assertEqual(
            self.window.dispatched_states[-1],
            {
                "is_desktop": True,
                "mode": "normal",
                "is_maximized": False,
                "is_fullscreen": False,
            },
        )

    def test_normal_to_fullscreen_to_exit_fullscreen_restores_normal(self) -> None:
        # normal -> fullscreen
        self.assertTrue(self.api.toggle_fullscreen())
        self.assertEqual(self.api.mode, "fullscreen")
        self.assertEqual(self.api.pre_fullscreen_mode, "normal")
        self.assertFalse(self.api.is_maximized)
        self.assertTrue(self.api.is_fullscreen)
        self.assertEqual(self.api.normal_rect, (180, 110, 1280, 780))
        self.assertEqual(self.win32.current_rect, (0, 0, 1920, 1080))
        self.assertFalse(self.window.native.TopMost)
        self.assertEqual(
            self.window.dispatched_states[-1],
            {
                "is_desktop": True,
                "mode": "fullscreen",
                "is_maximized": False,
                "is_fullscreen": True,
            },
        )

        # exit_fullscreen -> normal
        self.assertFalse(self.api.exit_fullscreen())
        self.assertEqual(self.api.mode, "normal")
        self.assertEqual(self.win32.current_rect, (180, 110, 1280, 780))
        self.assertEqual(
            self.window.dispatched_states[-1],
            {
                "is_desktop": True,
                "mode": "normal",
                "is_maximized": False,
                "is_fullscreen": False,
            },
        )

        # 再次调用 exit_fullscreen 为安全空操作
        prev_calls = len(self.win32.set_window_pos_calls)
        self.assertFalse(self.api.exit_fullscreen())
        self.assertEqual(len(self.win32.set_window_pos_calls), prev_calls)

    def test_maximized_to_fullscreen_to_exit_fullscreen_restores_maximized_and_normal_rect_intact(
        self,
    ) -> None:
        # normal -> maximized
        self.api.toggle_maximize()
        self.assertEqual(self.api.mode, "maximized")
        self.assertEqual(self.api.normal_rect, (180, 110, 1280, 780))

        # maximized -> fullscreen
        self.assertTrue(self.api.toggle_fullscreen())
        self.assertEqual(self.api.mode, "fullscreen")
        self.assertEqual(self.api.pre_fullscreen_mode, "maximized")
        self.assertEqual(self.win32.current_rect, (0, 0, 1920, 1080))
        # _normal_rect 绝不能被 rcWork 覆盖
        self.assertEqual(self.api.normal_rect, (180, 110, 1280, 780))

        # fullscreen -> exit_fullscreen -> maximized (rcWork)
        self.assertFalse(self.api.exit_fullscreen())
        self.assertEqual(self.api.mode, "maximized")
        self.assertTrue(self.api.is_maximized)
        self.assertFalse(self.api.is_fullscreen)
        self.assertEqual(self.win32.current_rect, (0, 0, 1920, 1040))
        self.assertEqual(self.api.normal_rect, (180, 110, 1280, 780))

        # maximized -> toggle_maximize -> 回到最初 normal 矩形
        self.assertFalse(self.api.toggle_maximize())
        self.assertEqual(self.api.mode, "normal")
        self.assertEqual(self.win32.current_rect, (180, 110, 1280, 780))

    def test_fullscreen_to_toggle_maximize_leaves_zero_fullscreen_residue(self) -> None:
        # normal -> fullscreen
        self.api.toggle_fullscreen()
        self.assertEqual(self.api.mode, "fullscreen")
        self.assertEqual(self.api.normal_rect, (180, 110, 1280, 780))

        # fullscreen -> toggle_maximize -> maximized (无全屏标志残留)
        self.assertTrue(self.api.toggle_maximize())
        self.assertEqual(self.api.mode, "maximized")
        self.assertTrue(self.api.is_maximized)
        self.assertFalse(self.api.is_fullscreen)
        self.assertEqual(self.win32.current_rect, (0, 0, 1920, 1040))
        self.assertEqual(self.api.normal_rect, (180, 110, 1280, 780))
        self.assertEqual(
            self.window.dispatched_states[-1],
            {
                "is_desktop": True,
                "mode": "maximized",
                "is_maximized": True,
                "is_fullscreen": False,
            },
        )

        # 再点一次最大化 -> 还原最初 normal 矩形
        self.assertFalse(self.api.toggle_maximize())
        self.assertEqual(self.api.mode, "normal")
        self.assertEqual(self.win32.current_rect, (180, 110, 1280, 780))

    def test_minimize_preserves_mode_and_restores_previous_mode(self) -> None:
        self.api.toggle_maximize()
        self.assertEqual(self.api.mode, "maximized")

        self.assertTrue(self.api.minimize())
        # 最小化期间 mode 与 _normal_rect 均不受污染
        self.assertEqual(self.api.mode, "maximized")
        self.assertEqual(self.api.normal_rect, (180, 110, 1280, 780))

        # 模拟从任务栏恢复
        self.win32.iconic = False
        self.win32.current_rect = (300, 300, 1000, 700)  # 即使系统临时偏移，恢复后应重新贴合 rcWork
        self.window.events.restored.fire()
        self.assertEqual(self.api.mode, "maximized")
        self.assertEqual(self.win32.current_rect, (0, 0, 1920, 1040))

    def test_start_drag_updates_normal_rect_and_persists(self) -> None:
        # fullscreen 禁止拖拽
        self.api.toggle_fullscreen()
        self.assertFalse(self.api.start_drag(0.5))
        self.api.exit_fullscreen()

        # normal 拖拽后更新 _normal_rect 并落盘
        self.win32.drag_end_rect = (260, 140, 1280, 780)
        self.assertTrue(self.api.start_drag(0.5))
        self.assertEqual(self.api.mode, "normal")
        self.assertEqual(self.api.normal_rect, (260, 140, 1280, 780))
        saved = load_window_geometry(self.settings_path)
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved["rect"], (260, 140, 1280, 780))
        self.assertFalse(saved["maximized"])

        # maximized 拖拽时平滑切回 normal 并落盘
        self.api.toggle_maximize()
        self.assertEqual(self.api.mode, "maximized")
        self.win32.cursor_pos = (960, 20)
        self.win32.drag_end_rect = (320, 90, 1280, 780)
        self.assertTrue(self.api.start_drag(0.5))
        self.assertEqual(self.api.mode, "normal")
        self.assertEqual(self.api.normal_rect, (320, 90, 1280, 780))
        saved2 = load_window_geometry(self.settings_path)
        assert saved2 is not None
        self.assertEqual(saved2["rect"], (320, 90, 1280, 780))
        self.assertFalse(saved2["maximized"])


class EightDirectionResizeTestCase(unittest.TestCase):
    """覆盖 8 方向自由拉伸纯计算、最小尺寸对侧锚定防平移与 Timer 完整生命周期"""

    def test_all_eight_edges_normal_resize(self) -> None:
        orig = (200, 150, 1200, 800)  # right=1400, bottom=950

        self.assertEqual(compute_resized_rect(orig, -50, 0, "left"), (150, 150, 1250, 800))
        self.assertEqual(compute_resized_rect(orig, 80, 0, "right"), (200, 150, 1280, 800))
        self.assertEqual(compute_resized_rect(orig, 0, -40, "top"), (200, 110, 1200, 840))
        self.assertEqual(compute_resized_rect(orig, 0, 60, "bottom"), (200, 150, 1200, 860))
        self.assertEqual(compute_resized_rect(orig, -50, -40, "top-left"), (150, 110, 1250, 840))
        self.assertEqual(compute_resized_rect(orig, 80, -40, "top-right"), (200, 110, 1280, 840))
        self.assertEqual(compute_resized_rect(orig, -50, 60, "bottom-left"), (150, 150, 1250, 860))
        self.assertEqual(compute_resized_rect(orig, 80, 60, "bottom-right"), (200, 150, 1280, 860))

    def test_left_and_top_min_size_anchoring_prevents_window_translation(self) -> None:
        orig = (200, 150, 1200, 800)
        orig_right = orig[0] + orig[2]  # 1400
        orig_bottom = orig[1] + orig[3]  # 950

        # 向右过度拖动 left 边：宽度钳制在 MIN_WINDOW_WIDTH，右边界严格锚定在 1400 不动
        nx, ny, nw, nh = compute_resized_rect(orig, 800, 0, "left")
        self.assertEqual(nw, MIN_WINDOW_WIDTH)
        self.assertEqual(nx + nw, orig_right)
        self.assertEqual((ny, nh), (150, 800))

        # 向下过度拖动 top 边：高度钳制在 MIN_WINDOW_HEIGHT，下边界严格锚定在 950 不动
        nx, ny, nw, nh = compute_resized_rect(orig, 0, 700, "top")
        self.assertEqual(nh, MIN_WINDOW_HEIGHT)
        self.assertEqual(ny + nh, orig_bottom)
        self.assertEqual((nx, nw), (200, 1200))

        # 向右下过度拖动 top-left 角：右边界与下边界同时严格锚定不动
        nx, ny, nw, nh = compute_resized_rect(orig, 900, 900, "top-left")
        self.assertEqual((nw, nh), (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT))
        self.assertEqual(nx + nw, orig_right)
        self.assertEqual(ny + nh, orig_bottom)

        # top-right 触底最小宽/高：左边界与下边界严格锚定
        nx, ny, nw, nh = compute_resized_rect(orig, -900, 900, "top-right")
        self.assertEqual((nw, nh), (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT))
        self.assertEqual(nx, orig[0])
        self.assertEqual(ny + nh, orig_bottom)

        # bottom-left 触底最小宽/高：右边界与上边界严格锚定
        nx, ny, nw, nh = compute_resized_rect(orig, 900, -900, "bottom-left")
        self.assertEqual((nw, nh), (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT))
        self.assertEqual(nx + nw, orig_right)
        self.assertEqual(ny, orig[1])

        # bottom-right 触底最小宽/高：左上角严格锚定
        nx, ny, nw, nh = compute_resized_rect(orig, -900, -900, "bottom-right")
        self.assertEqual((nx, ny, nw, nh), (200, 150, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT))

    def test_invalid_edge_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            compute_resized_rect((0, 0, 1200, 800), 10, 10, "diagonal")

    def test_effective_min_size_dpi_and_small_screen_cap(self) -> None:
        self.assertEqual(compute_effective_min_size(96, (0, 0, 1920, 1040)), (960, 620))
        self.assertEqual(compute_effective_min_size(120, (0, 0, 1920, 1040)), (1200, 775))
        # 小屏 1366x728 @ 150% DPI 不会超出工作区
        min_w, min_h = compute_effective_min_size(144, (0, 0, 1366, 728))
        self.assertLess(min_w, 1366)
        self.assertLess(min_h, 728)

    def test_start_resize_timer_lifecycle_and_mode_guards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            win32 = _FakeWin32(initial_rect=(200, 150, 1200, 800))
            timers: list[_FakeTimer] = []
            api = DesktopWindowApi(
                logging.getLogger("test.desktop.resize"),
                win32=win32,
                settings_path=settings_path,
                platform="win32",
                ui_dispatch=lambda _form, fn: (fn(), True)[1],
                timer_factory=lambda: (timers.append(_FakeTimer()), timers[-1])[1],
            )
            api.attach(_FakeWindow())

            # 非法 edge 拒绝
            self.assertFalse(api.start_resize("center"))
            self.assertEqual(len(timers), 0)

            # maximized / fullscreen 态拒绝拉伸
            api.toggle_maximize()
            self.assertFalse(api.start_resize("right"))
            api.toggle_fullscreen()
            self.assertFalse(api.start_resize("bottom-right"))
            api.exit_fullscreen()
            api.toggle_maximize()
            self.assertEqual(api.mode, "normal")

            # normal 态发起 top-left 拉伸
            win32.cursor_pos = (200, 150)
            win32.left_mouse_down = True
            self.assertTrue(api.start_resize("top-left"))
            self.assertEqual(len(timers), 1)
            timer = timers[0]
            self.assertEqual(timer.Interval, RESIZE_TIMER_INTERVAL_MS)
            self.assertTrue(timer.started)

            # 拖动至触达最小尺寸：验证对侧右下角 (1400, 950) 锚定 + flags 正确
            win32.cursor_pos = (700, 600)  # dx=+500, dy=+450
            timer.fire_tick()
            self.assertEqual(
                win32.current_rect,
                (1400 - MIN_WINDOW_WIDTH, 950 - MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT),
            )
            last_call = win32.set_window_pos_calls[-1]
            self.assertEqual(last_call["flags"], SWP_NOZORDER | SWP_NOACTIVATE)

            # 模拟松开左键：停止并释放定时器、更新 _normal_rect 并落盘
            win32.left_mouse_down = False
            timer.fire_tick()
            self.assertTrue(timer.stopped)
            self.assertTrue(timer.disposed)
            self.assertEqual(
                api.normal_rect,
                (1400 - MIN_WINDOW_WIDTH, 950 - MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT),
            )
            saved = load_window_geometry(settings_path)
            assert saved is not None
            self.assertEqual(saved["rect"], api.normal_rect)
            self.assertFalse(saved["maximized"])

            # 若上次定时器未结束再次发起拉伸，自动停止清理旧定时器
            win32.left_mouse_down = True
            self.assertTrue(api.start_resize("right"))
            first_active = timers[-1]
            self.assertTrue(first_active.started)
            self.assertTrue(api.start_resize("bottom"))
            self.assertTrue(first_active.stopped)
            self.assertTrue(first_active.disposed)
            self.assertTrue(timers[-1].started)


class WindowGeometryPersistenceTestCase(unittest.TestCase):
    """覆盖 settings.json 持久化保留已有字段 + 多屏/断屏坐标校验与启动恢复"""

    def test_save_and_load_preserves_other_settings_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fp = Path(tmp) / "settings.json"
            fp.write_text(
                json.dumps(
                    {
                        "scraper_sources": {
                            "enabled_sources": {"vndb": True, "steam": False},
                            "bangumi_token": "secret-token",
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            ok = save_window_geometry((210, 120, 1440, 880), maximized=True, settings_path=fp)
            self.assertTrue(ok)

            raw = json.loads(fp.read_text(encoding="utf-8"))
            # 刮削配置原样保留
            self.assertEqual(raw["scraper_sources"]["bangumi_token"], "secret-token")
            self.assertFalse(raw["scraper_sources"]["enabled_sources"]["steam"])

            loaded = load_window_geometry(fp)
            self.assertEqual(
                loaded,
                {"rect": (210, 120, 1440, 880), "maximized": True},
            )

    def test_monitor_bounds_validation_handles_disconnected_external_display(self) -> None:
        primary = (0, 0, 1920, 1040)
        secondary = (1920, 0, 2560, 1400)

        # 双屏时位于副屏的矩形有效
        saved_on_secondary = (2100, 120, 1360, 840)
        self.assertEqual(
            validate_window_rect_for_monitors(saved_on_secondary, [primary, secondary]),
            saved_on_secondary,
        )

        # 拔掉外接副屏后，仅剩主屏 -> 坐标落在屏外，返回 None 安全回退
        self.assertIsNone(validate_window_rect_for_monitors(saved_on_secondary, [primary]))

        # Win32 最小化哨兵坐标无效
        self.assertFalse(is_valid_normal_rect((-32000, -32000, 1360, 840)))
        self.assertIsNone(validate_window_rect_for_monitors((-32000, -32000, 1360, 840), [primary]))

        # 合法矩形超出缩小后屏幕宽高时自动安全夹紧
        clamped = validate_window_rect_for_monitors((100, 80, 1800, 1200), [(0, 0, 1366, 728)])
        self.assertEqual(clamped, (100, 80, 1366, 728))

    def test_startup_restore_applies_valid_rect_and_maximized_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fp = Path(tmp) / "settings.json"
            save_window_geometry((240, 130, 1300, 820), maximized=True, settings_path=fp)

            win32 = _FakeWin32(
                initial_rect=DEFAULT_NORMAL_RECT,
                work_rect=(0, 0, 1920, 1040),
                mon_rect=(0, 0, 1920, 1080),
                all_work_rects=[(0, 0, 1920, 1040)],
            )
            window = _FakeWindow()
            api = DesktopWindowApi(
                logging.getLogger("test.desktop.startup"),
                win32=win32,
                settings_path=fp,
                platform="win32",
                ui_dispatch=lambda _form, fn: (fn(), True)[1],
            )
            rect, is_max = api.load_startup_geometry()
            self.assertEqual(rect, (240, 130, 1300, 820))
            self.assertTrue(is_max)

            api.attach(window)
            window.events.shown.fire()
            # 启动恢复为 maximized，同时 _normal_rect 保留为持久化尺寸
            self.assertEqual(api.mode, "maximized")
            self.assertEqual(api.normal_rect, (240, 130, 1300, 820))
            self.assertEqual(win32.current_rect, (0, 0, 1920, 1040))

            # 取消最大化后精确还原至上次 normal 位置与尺寸
            api.toggle_maximize()
            self.assertEqual(api.mode, "normal")
            self.assertEqual(win32.current_rect, (240, 130, 1300, 820))

            # 窗口关闭时落盘最新状态
            win32.current_rect = (300, 160, 1240, 760)
            api.close()
            self.assertTrue(window.destroyed)
            final_saved = load_window_geometry(fp)
            self.assertEqual(final_saved, {"rect": (300, 160, 1240, 760), "maximized": False})


if __name__ == "__main__":
    unittest.main()
