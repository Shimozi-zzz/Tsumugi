from datetime import datetime, timezone
import threading
from typing import Any, Literal

TaskAssetType = Literal["pv", "bgm"]
TaskStatus = Literal["queued", "downloading", "done", "error"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DownloadTaskManager:
    """
    轻量内存后台下载任务追踪器：
    按 (game_id, asset_type) 索引维护 PV / BGM 的下载状态与进度，线程安全（支持 yt-dlp 线程钩子回写）。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[tuple[int, str], dict[str, Any]] = {}

    def set_task(
        self,
        game_id: int,
        asset_type: TaskAssetType,
        status: TaskStatus,
        progress: int | None = None,
        message: str = "",
    ) -> dict[str, Any]:
        clamped = (
            max(0, min(100, int(progress)))
            if progress is not None
            else None
        )
        entry = {
            "game_id": int(game_id),
            "asset_type": asset_type,
            "status": status,
            "progress": clamped,
            "message": message,
            "updated_at": _now_iso(),
        }
        with self._lock:
            self._tasks[(int(game_id), asset_type)] = entry
        return dict(entry)

    def update_progress(
        self,
        game_id: int,
        asset_type: TaskAssetType,
        progress: int | None,
        message: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            key = (int(game_id), asset_type)
            existing = self._tasks.get(key) or {
                "game_id": int(game_id),
                "asset_type": asset_type,
                "status": "downloading",
                "progress": None,
                "message": "",
            }
            existing["status"] = "downloading"
            if progress is not None:
                existing["progress"] = max(0, min(100, int(progress)))
            if message is not None:
                existing["message"] = message
            existing["updated_at"] = _now_iso()
            self._tasks[key] = existing
            return dict(existing)

    def mark_done(
        self,
        game_id: int,
        asset_type: TaskAssetType,
        message: str = "下载完成",
    ) -> dict[str, Any]:
        return self.set_task(game_id, asset_type, "done", 100, message)

    def mark_error(
        self,
        game_id: int,
        asset_type: TaskAssetType,
        message: str = "下载失败",
    ) -> dict[str, Any]:
        return self.set_task(game_id, asset_type, "error", None, message)

    def get_task(self, game_id: int, asset_type: TaskAssetType) -> dict[str, Any] | None:
        with self._lock:
            entry = self._tasks.get((int(game_id), asset_type))
            return dict(entry) if entry else None

    def is_active(self, game_id: int, asset_type: TaskAssetType | None = None) -> bool:
        with self._lock:
            for (gid, atype), entry in self._tasks.items():
                if gid != int(game_id):
                    continue
                if asset_type is not None and atype != asset_type:
                    continue
                if entry.get("status") in ("queued", "downloading"):
                    return True
            return False

    def list_tasks(self, game_id: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = [
                dict(entry)
                for (gid, _), entry in self._tasks.items()
                if game_id is None or gid == int(game_id)
            ]
        items.sort(key=lambda it: it.get("updated_at") or "", reverse=True)
        return items


task_manager = DownloadTaskManager()
