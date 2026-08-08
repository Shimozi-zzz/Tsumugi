"""批量回填缺失的本地封面缓存（ADR 0034 补）

对缺 file_path / 扩展名错误(.img) 的外部条目，重新下载并缓存封面：
- 复用 bangumi connector 的出站代理（若配置）；
- 顺序执行 + 每条约 0.6s 间隔（限速，避免快速连续请求触发数据源限流）；
- 记录成功/失败与具体原因（网络不可达 / 404 / 非图片等）。

用法：.venv\\Scripts\\python.exe scripts\\backfill_covers.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.connectors import registry
from app.database import SessionLocal
from app.images import download_and_cache_cover
from app.models import Item

DELAY = 0.3  # 每条约 0.3s 间隔，控制请求速率
TIMEOUT = 2.5  # 单条下载超时（连接不可达时快速失败，避免长时间挂起）


def out(msg: str):
    print(msg, flush=True)  # flush：重定向到文件时也实时落盘，便于中断后查进度


def main():
    # 与 main.py 启动一致：先发现并注册内置 Connector，再应用持久化的设置（出站代理），
    # 否则 registry 为空，get_connector 返回 None、代理读不到（此前 59 条全连超时的根因）
    from app.connectors import persistence
    registry.discover()
    registry.apply_settings(persistence.get_connector_settings())

    db = SessionLocal()
    items = db.query(Item).filter(Item.source != "local").all()
    pending = []
    for it in items:
        fp = it.file_path or ""
        missing = not fp
        wrong_ext = fp.lower().endswith(".img")  # 上一轮 .img 错误的残留
        if missing or wrong_ext:
            pending.append((it, missing, wrong_ext))

    n_missing = sum(1 for _, m, w in pending if m)
    n_wrong = sum(1 for _, m, w in pending if w)
    out(f"待回填 {len(pending)} 条：缺本地封面 {n_missing}，扩展名错误 {n_wrong}")

    ok = fail = 0
    failures = []
    for it, missing, wrong_ext in pending:
        # 按条目的数据源取代理（bangumi 用 bangumi 的代理，moegirl/vndb 用各自的）
        conn = registry.get_connector(it.source)
        proxy = getattr(conn, "proxy_url", None) if conn else None
        if not it.image_url:
            fail += 1
            failures.append((it.title, "无 image_url"))
            continue
        try:
            path, reason = download_and_cache_cover(it.image_url, proxy=proxy, timeout=TIMEOUT)
        except Exception as e:  # noqa: BLE001 - 单条失败不中断整体
            fail += 1
            failures.append((it.title, f"异常：{e}"))
            continue
        if path:
            it.file_path = path
            db.commit()
            ok += 1
            out(f"  OK [{it.id}] {(it.title or '')[:16]} -> {os.path.basename(path)}")
        else:
            fail += 1
            failures.append((it.title, reason))
        time.sleep(DELAY)

    db.close()
    out(f"\n回填完成：成功 {ok}，失败 {fail}")
    for title, reason in failures:
        out(f"  FAIL {(title or '')[:22]}：{reason}")
    return ok, fail


if __name__ == "__main__":
    main()
