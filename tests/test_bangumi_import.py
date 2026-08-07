"""Bangumi 收藏批量导入：分页、状态/评分→Review 映射、去重、进度、角色懒补"""
import time

import pytest

from app import bangumi_import
from app.models import Item, Review


def _entry(subject_id, type_, rate=0, name="作品"):
    return {
        "subject_id": subject_id, "subject_type": 2, "type": type_, "rate": rate,
        "subject": {"id": subject_id, "name": name, "name_cn": f"{name}CN",
                    "short_summary": f"{name}简介", "type": 2,
                    "images": {"large": f"https://x/{subject_id}.jpg"},
                    "tags": [{"name": "恋爱"}, {"name": "搞笑"}]},
    }


class FakeConnector:
    """带 2 页分页的假 Bangumi connector（复用 get_collections 接口形态）。"""
    name = "bangumi"
    proxy_url = None

    def __init__(self, pages):
        self.pages = pages  # 每页 entries 列表
        self.calls = []

    def get_collections(self, access_token, offset=0, limit=30, subject_type=2):
        self.calls.append(offset)
        all_entries = [e for page in self.pages for e in page]
        page = all_entries[offset:offset + limit]
        return {"data": page, "total": len(all_entries), "limit": limit, "offset": offset}


class TestReviewMapping:
    def test_status_and_rating_mapped(self, db, fake_collection, patch_embeddings):
        from app import ingest
        item = ingest.ingest_external(source="bangumi", external_id="1", title="A", db=db)
        r = bangumi_import._upsert_collection_review(db, item, _entry(1, 3, rate=8))
        assert r.status == "在看"
        assert r.rating == 8
        assert r.source == bangumi_import.BANGUMI_IMPORT_SOURCE
        assert r.title == bangumi_import.BANGUMI_IMPORT_TITLE

    def test_type_mapping_all(self, db, fake_collection, patch_embeddings):
        from app import ingest
        expect = {1: "想看", 2: "看完", 3: "在看", 4: "搁置", 5: "弃坑"}
        for t, status in expect.items():
            item = ingest.ingest_external(source="bangumi", external_id=str(t), title="X", db=db)
            r = bangumi_import._upsert_collection_review(db, item, _entry(t, t))
            assert r.status == status

    def test_rate_zero_no_rating(self, db, fake_collection, patch_embeddings):
        from app import ingest
        item = ingest.ingest_external(source="bangumi", external_id="9", title="X", db=db)
        r = bangumi_import._upsert_collection_review(db, item, _entry(9, 2, rate=0))
        assert r.rating is None
        assert r.status == "看完"

    def test_dedup_updates_in_place(self, db, fake_collection, patch_embeddings):
        from app import ingest
        item = ingest.ingest_external(source="bangumi", external_id="5", title="X", db=db)
        bangumi_import._upsert_collection_review(db, item, _entry(5, 1, rate=6))
        bangumi_import._upsert_collection_review(db, item, _entry(5, 4, rate=3))  # 重复导入
        rows = db.query(Review).filter(Review.item_id == item.id).all()
        assert len(rows) == 1  # 不产生重复
        assert rows[0].status == "搁置"  # 原地更新
        assert rows[0].rating == 3


class TestPaginationImport:
    @pytest.fixture(autouse=True)
    def _patch_registry(self, monkeypatch):
        monkeypatch.setattr("app.connectors.registry.get_connector", lambda name: self._conn)

    def _run_with_pages(self, pages, db):
        self._conn = FakeConnector(pages)
        job_id = bangumi_import.start_import("fake-token")
        deadline = time.time() + 10
        while time.time() < deadline:
            job = bangumi_import.get_job(job_id)
            if job["state"] in ("done", "error"):
                return job
            time.sleep(0.05)
        return bangumi_import.get_job(job_id)

    def test_import_two_pages_items_and_reviews(self, db, fake_collection, patch_embeddings, monkeypatch):
        monkeypatch.setattr(bangumi_import, "PAGE_LIMIT", 2)
        pages = [
            [_entry(101, 3, 8), _entry(102, 2, 0)],
            [_entry(103, 1, 7), _entry(104, 5, 6)],
            [_entry(105, 3, 0)],
        ]
        job = self._run_with_pages(pages, db)
        assert job["state"] == "done", job
        assert job["imported"] == 5
        assert job["total"] == 5
        items = db.query(Item).filter(Item.source == "bangumi").all()
        assert len(items) == 5
        reviews = db.query(Review).filter(Review.source == bangumi_import.BANGUMI_IMPORT_SOURCE).all()
        assert len(reviews) == 5
        statuses = {r.status for r in reviews}
        assert statuses == {"在看", "看完", "想看", "弃坑"}
        assert self._conn.calls == [0, 2, 4]  # 分页推进

    def test_import_dedup_second_run_no_duplicates(self, db, fake_collection, patch_embeddings):
        pages = [[_entry(101, 3, 8)]]
        self._run_with_pages(pages, db)
        job2 = self._run_with_pages(pages, db)  # 再跑一次
        assert db.query(Item).filter(Item.source == "bangumi").count() == 1
        assert db.query(Review).filter(Review.source == bangumi_import.BANGUMI_IMPORT_SOURCE).count() == 1
        # 第二次：全部记 skipped（去重计数正确，不再误标为 imported）
        assert job2["imported"] == 0
        assert job2["skipped"] == 1

    def test_import_single_failure_does_not_abort(self, db, fake_collection, patch_embeddings):
        class BoomConn(FakeConnector):
            def get_collections(self, *a, **k):
                return {"data": [_entry(201, 2)], "total": 1, "limit": 30, "offset": 0}

        self._conn = BoomConn([])
        # 让 ingest 失败：用一个会抛错的 subject_id 变体
        def broken(external_id):
            raise RuntimeError("boom")
        monkeypatch_import = pytest.MonkeyPatch()
        from app import ingest as _ingest
        monkeypatch_import.setattr(_ingest, "ingest_external", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        try:
            job = self._run_with_pages([[_entry(201, 2)]], db)
        finally:
            monkeypatch_import.undo()
        assert job["failed"] == 1
        assert job["imported"] == 0


class TestUsernameResolution:
    """收藏接口需要真实用户名：/v0/me 解析并缓存（`-` 无效，真实流程暴露）。"""

    def _make_resp(self, status, payload):
        class R:
            status_code = status
            def json(self): return payload
        return R()

    def test_resolves_and_caches_username(self, monkeypatch):
        from app.connectors.bangumi.connector import BangumiConnector
        saved = {}
        monkeypatch.setattr("app.bangumi_oauth.get_username_from_tokens", lambda: saved.get("username"))
        monkeypatch.setattr("app.bangumi_oauth.save_username", lambda u: saved.__setitem__("username", u))
        calls = []
        def fake_get(url, **kw):
            calls.append(url)
            assert "api.bgm.tv/v0/me" in url
            return self._make_resp(200, {"id": 1051338, "username": "pyk_test", "nickname": "n"})
        monkeypatch.setattr("app.connectors.bangumi.connector.http_get", fake_get)

        c = BangumiConnector()
        # 第一次：解析 + 缓存
        assert c._resolve_username("tok") == "pyk_test"
        assert saved["username"] == "pyk_test"
        # 第二次：走缓存，不再调 /v0/me
        assert c._resolve_username("tok") == "pyk_test"
        assert len(calls) == 1

    def test_get_collections_uses_username(self, monkeypatch):
        from app.connectors.bangumi.connector import BangumiConnector
        monkeypatch.setattr("app.bangumi_oauth.get_username_from_tokens", lambda: "pyk_cached")
        c = BangumiConnector()
        captured = {}
        monkeypatch.setattr(c, "_request", lambda method, path, **kw: captured.update(method=method, path=path) or {"data": [], "total": 0})
        c.get_collections("tok", offset=0, limit=30)
        assert captured["path"] == "/v0/users/pyk_cached/collections"


class TestBackfill:
    def test_backfill_fills_detail(self, db, fake_collection, patch_embeddings, monkeypatch):
        from app import ingest
        item = ingest.ingest_external(source="bangumi", external_id="301", title="A", db=db)

        class Conn:
            name = "bangumi"
            proxy_url = None
            def get_detail(self, external_id):
                from app.connectors.base import ItemDetail
                return ItemDetail(source="bangumi", title="A", external_id=external_id,
                                  description="desc", image_url="https://i/x.jpg",
                                  metadata={"rating": 8.9, "characters": [{"id": 1, "name": "角色X"}]})

        monkeypatch.setattr("app.connectors.registry.get_connector", lambda name: Conn())
        n = bangumi_import.backfill_bangumi_details(limit=5)
        assert n == 1
        db.refresh(item)
        assert item.raw_metadata["detail"]["metadata"]["characters"][0]["name"] == "角色X"

    def test_backfill_skips_already_filled(self, db, fake_collection, patch_embeddings, monkeypatch):
        from app import ingest
        item = ingest.ingest_external(source="bangumi", external_id="302", title="B", db=db)
        item.raw_metadata = {"detail": {"title": "B", "metadata": {}}}
        db.commit()
        called = []
        class Conn:
            name = "bangumi"
            def get_detail(self, external_id):
                called.append(external_id)
                return None
        monkeypatch.setattr("app.connectors.registry.get_connector", lambda name: Conn())
        assert bangumi_import.backfill_bangumi_details(limit=5) == 0
        assert called == []
