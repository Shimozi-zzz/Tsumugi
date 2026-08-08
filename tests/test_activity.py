"""年度活跃度聚合接口测试（ADR 0033）：日期分组、加权、跨年边界、连续活跃"""
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.database import get_db
from app.models import Item, Review


def _mk_client(db):
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def _review(db, item_id, created_at):
    r = Review(item_id=item_id, content="x", status="看完", created_at=created_at)
    db.add(r)
    db.commit()


def _external(db, title, synced_at):
    it = Item(title=title, type="external_ref", source="bangumi", external_id=title,
              content="", synced_at=synced_at)
    db.add(it)
    db.commit()


def _local(db, title, created_at):
    it = Item(title=title, type="note", source="local", content="x", created_at=created_at)
    db.add(it)
    db.commit()


class TestActivitySummary:
    def test_no_activity(self, db):
        body = _mk_client(db).get("/api/activity?year=2026").json()
        assert body["days"] == []
        assert body["stats"]["total_reviews"] == 0
        assert body["stats"]["total_score"] == 0
        assert body["stats"]["busiest_month"] is None
        assert body["weights"] == {"review": 2, "collection": 1}

    def test_weights_and_daily_grouping(self, db):
        # 先建一个 item 供 review 关联
        it = Item(title="作品", type="external_ref", source="bangumi", external_id="w1")
        db.add(it)
        db.flush()
        _review(db, it.id, datetime(2026, 8, 7, 10, 0))
        _review(db, it.id, datetime(2026, 8, 7, 12, 0))
        _review(db, it.id, datetime(2026, 8, 8, 9, 0))
        _external(db, "收藏A", datetime(2026, 8, 7, 14, 0))
        body = _mk_client(db).get("/api/activity?year=2026").json()
        days = {d["date"]: d for d in body["days"]}
        assert days["2026-08-07"] == {"date": "2026-08-07", "reviews": 2, "collections": 1, "score": 2 * 2 + 1}
        assert days["2026-08-08"]["score"] == 2  # 1 书评 ×2
        s = body["stats"]
        assert s["total_reviews"] == 3
        assert s["total_collections"] == 1
        assert s["total_score"] == 7
        assert s["active_days"] == 2
        assert s["busiest_month"] == "2026-08"

    def test_cross_year_boundary(self, db):
        it = Item(title="作品", type="external_ref", source="bangumi", external_id="w2")
        db.add(it)
        db.flush()
        _review(db, it.id, datetime(2025, 12, 31, 23, 59))
        _review(db, it.id, datetime(2026, 1, 1, 0, 1))
        _external(db, "年前收藏", datetime(2025, 12, 31, 20, 0))
        _external(db, "新年收藏", datetime(2026, 1, 1, 8, 0))
        y26 = _mk_client(db).get("/api/activity?year=2026").json()
        days26 = {d["date"]: d for d in y26["days"]}
        assert set(days26.keys()) == {"2026-01-01"}
        assert days26["2026-01-01"]["reviews"] == 1
        assert days26["2026-01-01"]["collections"] == 1
        assert days26["2026-01-01"]["score"] == 3
        y25 = _mk_client(db).get("/api/activity?year=2025").json()
        days25 = {d["date"]: d for d in y25["days"]}
        assert set(days25.keys()) == {"2025-12-31"}
        assert days25["2025-12-31"]["score"] == 3

    def test_longest_streak(self, db):
        it = Item(title="作品", type="external_ref", source="bangumi", external_id="w3")
        db.add(it)
        db.flush()
        for i in range(3):
            _review(db, it.id, datetime(2026, 2, 10 + i, 10, 0))
        _review(db, it.id, datetime(2026, 2, 20, 10, 0))  # 隔开的另一天
        body = _mk_client(db).get("/api/activity?year=2026").json()
        assert body["stats"]["longest_streak"] == 3
        assert body["stats"]["active_days"] == 4

    def test_local_items_not_counted_as_collections(self, db):
        _local(db, "本地笔记", datetime(2026, 8, 1, 9, 0))
        body = _mk_client(db).get("/api/activity?year=2026").json()
        assert body["days"] == []  # 本地笔记不计入收藏活跃
        assert body["stats"]["total_collections"] == 0

    def test_defaults_to_current_year(self, db):
        # 无 year 参数 → 用当前年（2026）
        _external(db, "收藏X", datetime(2026, 8, 7, 10, 0))
        body = _mk_client(db).get("/api/activity").json()
        assert body["year"] == 2026
        assert body["stats"]["total_collections"] == 1
