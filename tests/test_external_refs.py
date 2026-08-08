"""external_refs 模块测试：参考文本构建、chunk 重建、历史批量补齐（分批/限流）"""
import pytest

from app import external_refs
from app.connectors.base import ConnectorManifest, ItemDetail
from app.ingest import ingest_external
from app.models import Chunk, Item


# ---------------------------------------------------------------- 参考文本构建

class TestBuildReferenceText:
    def test_includes_intro_meta_and_characters(self):
        detail = ItemDetail(
            source="bangumi", title="作品", external_id="1",
            description="这是一个完整的简介。",
            metadata={
                "original_name": "Kaguya", "date": "2019-04-01",
                "tags": ["恋爱", "搞笑"],
                "characters": [
                    {"id": 1, "name": "辉夜", "relation": "主角",
                     "summary": "学生会副会长。", "actors": ["古贺葵"]},
                ],
            },
        )
        text = external_refs.build_reference_text(detail)
        assert "作品简介" in text
        assert "这是一个完整的简介。" in text
        assert "学生会副会长。" in text
        assert "古贺葵" in text
        assert "2019-04-01" in text
        assert "## 辉夜（主角）" in text

    def test_no_characters_still_builds(self):
        detail = ItemDetail(source="moegirl", title="词条", external_id="9",
                            description="简介。", metadata={"tags": ["a"]})
        text = external_refs.build_reference_text(detail)
        assert "简介。" in text
        assert "角色" not in text

    def test_empty_detail(self):
        assert external_refs.build_reference_text(None) == ""

    def test_stored_reference_roundtrip(self):
        detail = ItemDetail(source="bangumi", title="T", external_id="1", description="简介")
        raw = external_refs.with_reference_text(detail)
        item = Item(id=1, title="T", source="bangumi", external_id="1",
                    raw_metadata={"source": "bangumi", "detail": raw})
        assert external_refs.get_stored_reference(item) == external_refs.build_reference_text(detail)


# ---------------------------------------------------------------- 热度/评分分布（ADR 0026）

class TestExtractSocialMeta:
    def test_bangumi_rating_and_collection(self):
        meta = {
            "rating": 8.9,
            "rating_info": {"rank": 11, "total": 8413,
                            "count": {"1": 15, "2": 3, "3": 7, "4": 16, "5": 37,
                                      "6": 137, "7": 502, "8": 1697, "9": 3430, "10": 2569}},
            "collection": {"wish": 2966, "collect": 10334, "doing": 1310,
                           "on_hold": 826, "dropped": 112},
        }
        s = external_refs.extract_social_meta(meta)
        assert s["rating_rank"] == 11
        assert s["rating_total"] == 8413
        assert s["rating_distribution"]["10"] == 2569
        assert s["collection"]["collect"] == 10334

    def test_vndb_votecount(self):
        s = external_refs.extract_social_meta({"rating": 8.45, "votecount": 8675})
        assert s["votecount"] == 8675
        assert "collection" not in s

    def test_moegirl_page_info(self):
        s = external_refs.extract_social_meta({"length": 3490, "touched": "2026-04-18T15:33:45Z"})
        assert s["page_info"]["length"] == 3490
        assert s["page_info"]["touched"].startswith("2026-04")

    def test_empty_and_none(self):
        assert external_refs.extract_social_meta({}) == {}
        assert external_refs.extract_social_meta(None) == {}


# ---------------------------------------------------------------- chunk 重建

class TestReplaceChunks:
    def test_replace_writes_and_marks_source(self, db, fake_collection, patch_embeddings):
        item = ingest_external(source="bangumi", external_id="1", title="A", content="旧简介", db=db)
        n = external_refs.replace_external_reference_chunks(
            item, "# 简介\n\n完整资料" * 8, db=db)
        assert n >= 1
        chunks = db.query(Chunk).filter(Chunk.item_id == item.id).all()
        assert chunks
        assert all(c.source_type == "external_reference" for c in chunks)
        assert all(c.connector == "bangumi" for c in chunks)
        assert len(fake_collection.vectors) == len(chunks)

    def test_replace_rebuilds_content(self, db, fake_collection, patch_embeddings):
        item = ingest_external(source="bangumi", external_id="2", title="B", content="旧简介", db=db)
        external_refs.replace_external_reference_chunks(item, "第一版内容" * 20, db=db)
        external_refs.replace_external_reference_chunks(item, "第二版完全不同内容" * 20, db=db)
        chunks = db.query(Chunk).filter(Chunk.item_id == item.id).all()
        assert len(chunks) == 1
        assert "第二版" in chunks[0].content
        ref = chunks[0].embedding_ref
        assert fake_collection.docs.get(ref) == chunks[0].content
        # 旧文本向量不残留
        assert not any("第一版" in fake_collection.docs.get(r, "") for r in fake_collection.vectors)

    def test_empty_text_keeps_existing(self, db, fake_collection, patch_embeddings):
        item = ingest_external(source="bangumi", external_id="3", title="C", content="仅简介", db=db)
        n = external_refs.replace_external_reference_chunks(item, "", db=db)
        assert n >= 1  # 保留原有简介 chunk，不误删
        assert len(db.query(Chunk).filter(Chunk.item_id == item.id).all()) >= 1

    def test_ensure_skips_when_unchanged(self, db, fake_collection, patch_embeddings):
        item = ingest_external(source="bangumi", external_id="4", title="D",
                               content="旧简介",
                               reference_text="完整资料文本" * 30,
                               raw_metadata={"detail": {"metadata": {"reference_text": "完整资料文本" * 30}}},
                               db=db)
        before = len(fake_collection.vectors)
        assert external_refs.ensure_external_reference_chunks(
            item, "完整资料文本" * 30, db=db) is False
        assert len(fake_collection.vectors) == before  # 未重建

    def test_ensure_rebuilds_when_changed(self, db, fake_collection, patch_embeddings):
        item = ingest_external(source="bangumi", external_id="5", title="E", content="旧简介", db=db)
        assert external_refs.ensure_external_reference_chunks(item, "新资料文本" * 30, db=db) is True
        chunks = db.query(Chunk).filter(Chunk.item_id == item.id).all()
        assert chunks
        assert all("新资料文本" in c.content for c in chunks)


# ---------------------------------------------------------------- 批量补齐

class _CountingConn:
    name = "fakebg"
    proxy_url = None

    def __init__(self):
        self.calls = []

    @property
    def manifest(self):
        return ConnectorManifest(name="fakebg", display_name="Fake", version="0.1",
                                 base_url="https://x", capabilities=["get_detail"])

    def get_detail(self, external_id):
        self.calls.append(external_id)
        return ItemDetail(
            source="fakebg", title=f"T{external_id}", external_id=str(external_id),
            description=f"{external_id}的完整简介" * 5,
            metadata={"characters": [{"id": 1, "name": f"角色{external_id}", "summary": "小传"}]},
        )


class TestBackfill:
    def test_backfill_batches_and_resumes(self, db, fake_collection, patch_embeddings, monkeypatch):
        conn = _CountingConn()
        monkeypatch.setattr("app.connectors.registry.get_connector", lambda name: conn)
        for i in range(5):
            ingest_external(source="fakebg", external_id=str(i), title=f"T{i}",
                            content="旧", db=db)
        # 分批推进：每批 limit 条，全部补齐后再跑返回 0
        assert external_refs.backfill_external_reference(limit=2, db=db) == 2
        assert len(conn.calls) == 2
        assert external_refs.backfill_external_reference(limit=2, db=db) == 2
        assert external_refs.backfill_external_reference(limit=2, db=db) == 1
        assert external_refs.backfill_external_reference(limit=2, db=db) == 0
        assert len(conn.calls) == 5  # 每条约拉一次，不受控重复拉取
        chunks = db.query(Chunk).all()
        assert len(chunks) == 5
        assert all(c.source_type == "external_reference" for c in chunks)
        assert all(c.connector == "fakebg" for c in chunks)

    def test_backfill_skips_items_with_reference(self, db, fake_collection, patch_embeddings, monkeypatch):
        conn = _CountingConn()
        monkeypatch.setattr("app.connectors.registry.get_connector", lambda name: conn)
        item = ingest_external(source="fakebg", external_id="10", title="已补齐", content="旧", db=db)
        item.raw_metadata = {"detail": {"metadata": {"reference_text": "已有完整资料"}}}
        db.commit()
        ingest_external(source="fakebg", external_id="11", title="待补", content="旧", db=db)
        assert external_refs.backfill_external_reference(limit=5, db=db) == 1
        assert conn.calls == ["11"]

    def test_backfill_source_filter(self, db, fake_collection, patch_embeddings, monkeypatch):
        conn = _CountingConn()
        monkeypatch.setattr("app.connectors.registry.get_connector", lambda name: conn)
        ingest_external(source="fakebg", external_id="21", title="A", content="旧", db=db)
        ingest_external(source="moegirl", external_id="22", title="B", content="旧", db=db)
        assert external_refs.backfill_external_reference(limit=5, source="fakebg", db=db) == 1
        assert conn.calls == ["21"]

    def test_backfill_single_failure_skips(self, db, fake_collection, patch_embeddings, monkeypatch):
        class BoomConn:
            name = "fakebg"
            proxy_url = None

            def __init__(self):
                self.calls = []

            @property
            def manifest(self):
                return ConnectorManifest(name="fakebg", display_name="Fake", version="0.1",
                                         base_url="https://x", capabilities=["get_detail"])

            def get_detail(self, external_id):
                self.calls.append(external_id)
                if external_id == "31":
                    raise RuntimeError("boom")
                return ItemDetail(source="fakebg", title=f"T{external_id}",
                                  external_id=str(external_id),
                                  description=f"{external_id}的完整简介" * 5,
                                  metadata={"characters": []})

        conn = BoomConn()
        monkeypatch.setattr("app.connectors.registry.get_connector", lambda name: conn)
        ingest_external(source="fakebg", external_id="31", title="坏", content="旧", db=db)
        ingest_external(source="fakebg", external_id="32", title="好", content="旧", db=db)
        assert external_refs.backfill_external_reference(limit=5, db=db) == 1  # 31 失败跳过，32 补齐
        assert conn.calls == ["31", "32"]
        # 再次运行：32 已补齐不重拉；31 仍失败（下次仍会尝试，不算补齐）
        assert external_refs.backfill_external_reference(limit=5, db=db) == 0
        assert conn.calls == ["31", "32", "31"]
        # 32 始终未被重复拉取
        assert conn.calls.count("32") == 1
