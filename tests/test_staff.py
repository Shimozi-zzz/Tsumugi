"""Phase 12-B：Staff 实体化测试（轻量索引，不跨 Provider 强并 Person）。"""
import pytest

from app import media as media_svc
from app.models import Item, Staff


def _mk_item(db, source="jikan", external_id="1", title="作品", raw_metadata=None):
    it = Item(type="external_ref", source=source, external_id=external_id, title=title, content="")
    it.raw_metadata = raw_metadata
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


STAFF_RAW = {"source": "jikan", "detail": {"metadata": {"staff": [
    {"name": "Takuya Sato", "role": "Director", "source": "jikan", "external_id": "5", "credit_order": 0},
    {"name": "Writer A", "role": "Writer", "source": "jikan", "external_id": "6", "credit_order": 1},
]}}}


class TestStaff:
    def test_sync_creates_staff(self, db):
        item = _mk_item(db, raw_metadata=STAFF_RAW)
        media_svc.ensure_media_for_item(item, db)
        db.commit()
        rows = db.query(Staff).filter(Staff.media_id == item.media_id).all()
        assert len(rows) == 2
        a = next(s for s in rows if s.name == "Takuya Sato")
        assert a.role == "Director"
        assert a.external_id == "5"
        assert a.credit_order == 0
        # raw_metadata 保留
        assert a.raw_metadata == STAFF_RAW["detail"]["metadata"]["staff"][0]

    def test_same_staff_multiple_media(self, db):
        item1 = _mk_item(db, external_id="1", raw_metadata=STAFF_RAW)
        item2 = _mk_item(db, external_id="2", title="作品2", raw_metadata=STAFF_RAW)
        media_svc.ensure_media_for_item(item1, db)
        media_svc.ensure_media_for_item(item2, db)
        db.commit()
        # 不同 MediaEntry → 同名 Staff 各自保留（不跨 media 强并）
        assert db.query(Staff).count() == 4
        assert db.query(Staff).filter(Staff.name == "Takuya Sato").count() == 2

    def test_provider_isolation(self, db):
        j = _mk_item(db, source="jikan", external_id="1", raw_metadata=STAFF_RAW)
        e1 = media_svc.ensure_media_for_item(j, db)
        db.commit()
        assert db.query(Staff).filter(Staff.source == "jikan").count() == 2
        # 另一 Provider 同 media（标题匹配）：只删重建该 Provider 的 Staff
        a = _mk_item(db, source="anilist", external_id="2", title="作品",
                     raw_metadata={"source": "anilist", "detail": {"metadata": {"staff": [
                         {"name": "X", "role": "Writer", "source": "anilist", "external_id": "9", "credit_order": 0}]}}})
        e2 = media_svc.ensure_media_for_item(a, db)
        db.commit()
        assert e2.id == e1.id
        assert db.query(Staff).filter(Staff.source == "jikan").count() == 2   # jikan 未动
        assert db.query(Staff).filter(Staff.source == "anilist").count() == 1

    def test_no_external_id_allowed(self, db):
        raw = {"source": "jikan", "detail": {"metadata": {"staff": [
            {"name": "Z", "role": "Producer"}]}}}
        item = _mk_item(db, raw_metadata=raw)
        media_svc.ensure_media_for_item(item, db)
        db.commit()
        rows = db.query(Staff).filter(Staff.media_id == item.media_id).all()
        assert len(rows) == 1
        assert rows[0].external_id is None

    def test_idempotent(self, db):
        item = _mk_item(db, raw_metadata=STAFF_RAW)
        media_svc.ensure_media_for_item(item, db)
        media_svc.ensure_media_for_item(item, db)
        db.commit()
        assert db.query(Staff).count() == 2
