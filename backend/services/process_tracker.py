import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.core.os_adapter import os_adapter
from backend.db.database import AsyncSessionLocal
from backend.db.models import Game, PlayRecord, PlaySession

logger = logging.getLogger("tsumugi.services.process_tracker")

FLUSH_INTERVAL_SECONDS = 60
HANDOFF_WINDOW_SECONDS = 15


@dataclass
class ActiveSessionState:
    game_id: int
    title: str
    pid: int
    exe_path: str
    install_dir: str
    is_mock: bool
    started_at: datetime
    started_monotonic: float
    play_session_id: int
    base_total_seconds: int = 0
    flushed_seconds: int = 0
    tracked_pids: set[int] = field(default_factory=set)
    degraded_dir_poll: bool = False


class ProcessTracker:
    """
    跨平台进程树级游玩时长追踪器：
    - 防止多开：同一时刻仅允许追踪一个运行中的游戏会话。
    - Linux 模拟模式：保持真实秒级计时，支持通过接口模拟结束并触发落盘。
    - Windows 真实进程树监控：
      1. 使用 psutil 追踪主进程及其递归子进程树；
      2. 若启动器/Locale Emulator 在启动后 15 秒内退出，自动接管同安装目录下新拉起的 .exe；
      3. 捕获 UAC 提权导致的 psutil.AccessDenied，平滑降级为安装目录进程轮询；
      4. 每 60 秒增量落盘写入 play_records 与 play_sessions，退出或关闭应用时强制最终落盘。
    """

    def __init__(self) -> None:
        self._active: ActiveSessionState | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self._active is not None

    def _current_elapsed(self, state: ActiveSessionState) -> int:
        return max(0, int(time.monotonic() - state.started_monotonic))

    def get_status(self) -> dict[str, Any]:
        state = self._active
        if not state:
            return {
                "running": False,
                "game_id": None,
                "title": "",
                "elapsed_seconds": 0,
                "total_seconds": 0,
                "pid": None,
                "is_mock": sys.platform != "win32",
                "started_at": None,
                "platform": os_adapter.platform_name,
            }
        elapsed = self._current_elapsed(state)
        return {
            "running": True,
            "game_id": state.game_id,
            "title": state.title,
            "elapsed_seconds": elapsed,
            "total_seconds": state.base_total_seconds + elapsed,
            "pid": state.pid,
            "is_mock": state.is_mock,
            "started_at": state.started_at.isoformat(),
            "platform": os_adapter.platform_name,
        }

    async def start_tracking(
        self,
        game_id: int,
        title: str,
        pid: int,
        exe_path: str,
        is_mock: bool,
        base_total_seconds: int = 0,
    ) -> dict[str, Any]:
        async with self._lock:
            if self._active is not None:
                raise RuntimeError(
                    f"游戏《{self._active.title}》正在运行中，请先退出当前游戏后再启动新游戏"
                )

            now = datetime.now()
            async with AsyncSessionLocal() as db:
                play_session = PlaySession(
                    game_id=game_id,
                    started_at=now,
                    duration_seconds=0,
                )
                db.add(play_session)
                await db.commit()
                await db.refresh(play_session)
                session_id = play_session.id

            install_dir = ""
            if exe_path and not exe_path.lower().startswith(("steam://", "http://", "https://")):
                try:
                    install_dir = str(Path(exe_path).resolve().parent)
                except OSError:
                    install_dir = str(Path(exe_path).parent)

            tracked = {pid} if (pid and pid > 0 and not is_mock) else set()
            self._active = ActiveSessionState(
                game_id=game_id,
                title=title,
                pid=pid,
                exe_path=exe_path,
                install_dir=install_dir,
                is_mock=is_mock,
                started_at=now,
                started_monotonic=time.monotonic(),
                play_session_id=session_id,
                base_total_seconds=base_total_seconds,
                flushed_seconds=0,
                tracked_pids=tracked,
            )

            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info(
                "Started tracking game_id=%s (%s) pid=%s is_mock=%s",
                game_id,
                title,
                pid,
                is_mock,
            )
            return self.get_status()

    async def _flush_delta(self, state: ActiveSessionState, force: bool = False) -> int:
        elapsed = self._current_elapsed(state)
        if force and elapsed == 0:
            # 哪怕只运行不到 1 秒被立刻手动结束，至少记录 1 秒便于验证闭环
            elapsed = 1
        delta = elapsed - state.flushed_seconds
        if delta <= 0:
            return state.base_total_seconds + state.flushed_seconds

        async with AsyncSessionLocal() as db:
            stmt = (
                select(Game)
                .where(Game.id == state.game_id)
                .options(selectinload(Game.play_record))
            )
            game = (await db.execute(stmt)).scalar_one_or_none()
            new_total = state.base_total_seconds + elapsed
            if game:
                if not game.play_record:
                    game.play_record = PlayRecord(game_id=game.id, total_seconds=0)
                game.play_record.total_seconds += delta
                game.play_record.last_played_at = datetime.now()
                new_total = game.play_record.total_seconds

            ps = await db.get(PlaySession, state.play_session_id)
            if ps:
                ps.duration_seconds = elapsed

            await db.commit()

        state.flushed_seconds = elapsed
        logger.debug(
            "Flushed +%ss for game_id=%s (session=%ss total=%ss)",
            delta,
            state.game_id,
            elapsed,
            new_total,
        )
        return new_total

    def _scan_install_dir_pids(self, install_dir: str, exclude_pids: set[int] | None = None) -> set[int]:
        """扫描指定安装目录下所有存活的进程 PID"""
        if not install_dir:
            return set()
        norm_dir = install_dir.lower().rstrip("\\/")
        found: set[int] = set()
        excluded = exclude_pids or set()
        for proc in psutil.process_iter(["pid", "exe", "name"]):
            try:
                pid = proc.info["pid"]
                if pid in excluded:
                    continue
                exe = (proc.info.get("exe") or "").lower()
                if exe and (exe.startswith(norm_dir + "\\") or exe.startswith(norm_dir + "/")):
                    found.add(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return found

    def _check_real_processes_alive(self, state: ActiveSessionState) -> bool:
        """检查真实 Windows/OS 进程树是否仍在运行，包含 15s 接管窗口与 UAC 降级轮询"""
        elapsed = self._current_elapsed(state)

        # 若已降级为目录轮询（例如遇到 UAC AccessDenied 或 URI 拉起无初始 PID）
        if state.degraded_dir_poll or not state.tracked_pids:
            dir_pids = self._scan_install_dir_pids(state.install_dir)
            if dir_pids:
                state.tracked_pids.update(dir_pids)
                return True
            # 15 秒启动/转区接管窗口内继续等待游戏主进程拉起
            if elapsed < HANDOFF_WINDOW_SECONDS:
                return True
            return False

        alive_pids: set[int] = set()
        access_denied_hit = False

        for pid in list(state.tracked_pids):
            try:
                proc = psutil.Process(pid)
                if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                    alive_pids.add(pid)
                    for child in proc.children(recursive=True):
                        if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                            alive_pids.add(child.pid)
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied:
                access_denied_hit = True
                # 进程仍存在只是无权限访问，先视为存活并启用目录兜底
                if psutil.pid_exists(pid):
                    alive_pids.add(pid)
            except Exception:
                continue

        if access_denied_hit:
            state.degraded_dir_poll = True
            logger.info(
                "Encountered AccessDenied for game_id=%s, enabling directory-level process polling",
                state.game_id,
            )

        # 始终把同安装目录内新拉起的子程序纳入追踪（兼容转区工具、启动器多阶段拉起）
        if state.install_dir:
            dir_pids = self._scan_install_dir_pids(state.install_dir)
            alive_pids.update(dir_pids)

        state.tracked_pids = alive_pids
        if alive_pids:
            return True

        # 15 秒接管宽限期：防止 Locale Emulator / Launcher 先退出、真实游戏慢半拍启动
        if elapsed < HANDOFF_WINDOW_SECONDS:
            return True

        return False

    async def _monitor_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(1.0)
                state = self._active
                if state is None:
                    break

                elapsed = self._current_elapsed(state)

                # 真实模式下检测进程树存活
                if not state.is_mock:
                    alive = await asyncio.to_thread(self._check_real_processes_alive, state)
                    if not alive:
                        logger.info(
                            "Tracked process tree exited for game_id=%s after %ss",
                            state.game_id,
                            elapsed,
                        )
                        async with self._lock:
                            if self._active is state:
                                await self._flush_delta(state, force=True)
                                self._active = None
                        break

                # 每 60 秒增量落盘一次，防止崩溃/断电丢时长
                if elapsed - state.flushed_seconds >= FLUSH_INTERVAL_SECONDS:
                    async with self._lock:
                        if self._active is state:
                            await self._flush_delta(state, force=False)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("ProcessTracker monitor loop error: %s", exc)

    async def stop_tracking(self, terminate_process: bool = False) -> dict[str, Any]:
        """主动结束当前游玩会话（Linux 模拟退出 或 Windows 手动停止/结束进程）并落盘"""
        async with self._lock:
            state = self._active
            if state is None:
                return {
                    "stopped": False,
                    "message": "当前没有正在运行的游戏",
                }

            if terminate_process and not state.is_mock:
                for pid in list(state.tracked_pids):
                    try:
                        proc = psutil.Process(pid)
                        proc.terminate()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

            final_total = await self._flush_delta(state, force=True)
            session_seconds = state.flushed_seconds
            game_id = state.game_id
            title = state.title

            self._active = None
            task = self._monitor_task
            self._monitor_task = None

        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        logger.info(
            "Stopped tracking game_id=%s (%s): session=%ss total=%ss",
            game_id,
            title,
            session_seconds,
            final_total,
        )
        return {
            "stopped": True,
            "game_id": game_id,
            "title": title,
            "session_seconds": session_seconds,
            "total_seconds": final_total,
            "message": f"《{title}》游玩会话已结束并保存时长（本次 {session_seconds} 秒）",
        }

    async def shutdown_flush(self) -> None:
        """应用关闭时强制落盘未写入的时长"""
        if self._active is not None:
            logger.info("Application shutting down, flushing active play session...")
            await self.stop_tracking(terminate_process=False)


process_tracker = ProcessTracker()
