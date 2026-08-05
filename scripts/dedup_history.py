"""历史重复数据清理工具（备用，按需手动执行）

去重功能（ADR 0005）上线前导入的重复内容不会自动清理（content_hash 为
NULL）。本脚本扫描全部 Item，计算指纹，对相同指纹保留 id 最小的一条，
删除其余条目（级联清向量 + 清理孤立标签）。

用法：
    .venv\\Scripts\\python.exe scripts/dedup_history.py [--dry-run] [--delete-images]

默认 dry-run（只报告不删除）；确认无误后加 --apply 实际执行。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app import ingest  # noqa: E402
from app.models import Item  # noqa: E402


def scan_duplicates(db) -> list:
    """按 content_hash 分组，返回 [(hash, [ids])]，重复组在前。"""
    from sqlalchemy import func
    groups = (
        db.query(Item.content_hash, func.group_concat(Item.id))
        .filter(Item.content_hash.isnot(None))
        .group_by(Item.content_hash)
        .having(func.count(Item.id) > 1)
        .all()
    )
    result = []
    for h, ids_str in groups:
        ids = [int(x) for x in ids_str.split(",")]
        result.append((h, ids))
    return result


def main():
    parser = argparse.ArgumentParser(description="Tsumugi 历史重复数据清理")
    parser.add_argument("--apply", action="store_true", help="实际执行删除（默认只报告）")
    parser.add_argument("--delete-images", action="store_true",
                        help="同时删除重复图片的本地附件文件（默认只清条目与向量）")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        duplicates = scan_duplicates(db)
        if not duplicates:
            print("没有发现重复数据（或历史数据 content_hash 均为 NULL）。")
            return

        total_to_delete = sum(len(ids) - 1 for _, ids in duplicates)
        print(f"发现 {len(duplicates)} 组重复，共将删除 {total_to_delete} 条重复条目。")

        for h, ids in duplicates:
            keep = ids[0]
            drop = ids[1:]
            titles = [db.get(Item, i).title if db.get(Item, i) else f"#{i}" for i in ids]
            print(f"  hash {h[:12]}… keep #{keep}（{titles[0]}），删除 {drop}")
            if args.apply:
                for i in drop:
                    ingest.delete_item(i, db=db)

        if not args.apply:
            print("\n以上为预览。确认无误后加 --apply 执行删除；"
                  "图片附件删除需另加 --delete-images。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
