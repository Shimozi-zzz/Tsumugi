"""Phase 12-B：MediaRelation 作品关系索引测试。"""
import pytest

from app import media as media_svc
from app.models import Item, MediaRelation


def _mk_item(db, source="jikan", external_id="1", title="作品", raw_metadata=None):
    it = Item(type="external_ref", source=source, external_id=external_id, title=title, content="")
    it.raw_metadata = raw_metadata
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


REL_RAW = {"source": "jikan", "detail": {"metadata": {"relations": [
    {"relation": "Sequel", "title": "Steins;Gate 0", "external_id": "999", "source": "jikan"},
    {"relation": "Prequel", "title": "Chaos;Head", "external_id": "888", "source": "jikan"},
]}}}


class TestMediaRelation:
    def test_relation_created(self, db):
        item = _mk_item(db, raw_metadata=REL_RAW)
        media_svc.ensure_media_for_item(item, db)
        db.commit()
        rels = db.query(MediaRelation).filter(MediaRelation.media_id == item.media_id).all()
        assert len(rels) == 2
        r0 = next(r for r in rels if r.relation_type == "sequel")
        assert r0.target_title == "Steins;Gate 0"
        assert r0.target_external_id == "999"
        assert r0.target_source == "jikan"
        assert r0.target_media_id is None  # 目标未收藏

    def test_target_media_bound_when_collected(self, db):
        # 先收藏目标作品 → 其 MediaSource 存在 → relation 自动绑定 target_media_id
        target = _mk_item(db, source="jikan", external_id="999", title="Steins;Gate 0")
        target_media = media_svc.ensure_media_for_item(target, db)
        db.commit()
        item = _mk_item(db, external_id="9253", title="Steins;Gate", raw_metadata=REL_RAW)
        media_svc.ensure_media_for_item(item, db)
        db.commit()
        r0 = db.query(MediaRelation).filter(
            MediaRelation.media_id == item.media_id, MediaRelation.relation_type == "sequel").first()
        assert r0.target_media_id == target_media.id

    def test_unknown_relation_preserved(self, db):
        raw = {"source": "anilist", "detail": {"metadata": {"relations": [
            {"relation": "SPIN_OFF_WEIRD", "title": "X", "external_id": "1", "source": "anilist"}]}}}
        item = _mk_item(db, source="anilist", raw_metadata=raw)
        media_svc.ensure_media_for_item(item, db)
        db.commit()
        rels = db.query(MediaRelation).filter(MediaRelation.media_id == item.media_id).all()
        assert rels[0].relation_type == "other"  # 未知类型标准化为 other
        assert rels[0].raw_metadata["relation"] == "SPIN_OFF_WEIRD"  # 原文保留在 raw_metadata

    def test_source_isolation(self, db):
        j = _mk_item(db, source="jikan", external_id="1", raw_metadata=REL_RAW)
        a = _mk_item(db, source="anilist", external_id="2", title="作品",
                     raw_metadata={"source": "anilist", "detail": {"metadata": {"relations": [
                         {"relation": "ADAPTATION", "title": "M", "external_id": "7", "source": "anilist"}]}}})
        e1 = media_svc.ensure_media_for_item(j, db)
        e2 = media_svc.ensure_media_for_item(a, db)
        db.commit()
        assert e2.id == e1.id
        assert db.query(MediaRelation).filter(
            MediaRelation.media_id == e1.id, MediaRelation.source == "jikan").count() == 2
        assert db.query(MediaRelation).filter(
            MediaRelation.media_id == e1.id, MediaRelation.source == "anilist").count() == 1

    def test_no_duplicate_reinsert(self, db):
        item = _mk_item(db, raw_metadata=REL_RAW)
        media_svc.ensure_media_for_item(item, db)
        media_svc.ensure_media_for_item(item, db)
        db.commit()
        assert db.query(MediaRelation).count() == 2


class TestNormalizeRelation:
    """Phase 12-C：关系类型标准化（已知→规范名，未知→other + raw 保留）。"""

    def test_normalize_relation_types(self):
        from app import media as media_svc
        assert media_svc.normalize_relation_type("Sequel") == "sequel"
        assert media_svc.normalize_relation_type("SIDE_STORY") == "side_story"
        assert media_svc.normalize_relation_type("Spin-Off") == "spin_off"
        assert media_svc.normalize_relation_type("ADAPTATION") == "adaptation"
        assert media_svc.normalize_relation_type("PARENT") == "parent_story"
        assert media_svc.normalize_relation_type("SPIN_OFF_WEIRD") == "other"
        assert media_svc.normalize_relation_type(None) == "other"
        assert media_svc.normalize_relation_type("") == "other"
