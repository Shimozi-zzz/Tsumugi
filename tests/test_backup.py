"""数据备份/导出/导入测试（ADR 0038）：导出完整性、导入恢复、冲突处理"""
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import backup
from app.api.routes import router
from app.database import get_db
from app.ingest import ingest_external, ingest_text_document
from app.models import Chunk, Item, LLMProviderConfig, Review, Source, Tag, item_tag_association
from app.reviews import create_review


def _mk_client(db):
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def _seed(db):
    note = ingest_text_document("我的笔记", "这是一篇关于RAG的笔记内容。" * 20,
                                tag_names=["RAG", "测试"], db=db)
    ext = ingest_external(
        source="bangumi", external_id="301", title="辉夜大小姐", content="简介",
        image_url="https://img/x.jpg", tags=["恋爱"],
        raw_metadata={"source": "bangumi", "detail": {"metadata": {
            "characters": [{"id": 1, "name": "辉夜", "actors": ["古贺葵"]}],
            "reference_text": "# 作品简介\n\n完整资料",
        }}},
        reference_text="# 作品简介\n\n完整资料", db=db,
    )
    review = create_review(note.id, "这是我写的读后感内容" * 20, title="读后感",
                           rating=9, status="看完", db=db)
    db.add(Source(name="connector_settings", type="settings",
                  config_ref='{"bangumi":{"proxy_url":"http://127.0.0.1:7897"}}'))
    db.add(LLMProviderConfig(name="deepseek", provider_type="openai_compatible",
                             base_url="https://x", model_id="deepseek-chat",
                             api_key_ref="{DEEPSEEK_API_KEY}", enabled=1))
    db.commit()
    return note, ext, review


def _wipe(db):
    db.execute(item_tag_association.delete())
    db.query(Chunk).delete()
    db.query(Review).delete()
    db.query(Item).delete()
    db.query(Tag).delete()
    db.query(Source).delete()
    db.query(LLMProviderConfig).delete()
    db.commit()


class TestExport:
    def test_export_contains_all(self, db, fake_collection, patch_embeddings):
        _seed(db)
        data = backup.export_backup(db)
        assert data["format"] == "tsumugi-library"
        assert data["version"] == 1
        d = data["data"]
        assert len(d["items"]) == 2
        assert len(d["reviews"]) == 1
        assert {t["name"] for t in d["tags"]} >= {"RAG", "测试", "恋爱"}
        # 外部条目 raw_metadata（含已下载资料）完整导出
        ext = next(i for i in d["items"] if i["source"] == "bangumi")
        assert ext["raw_metadata"]["detail"]["metadata"]["characters"][0]["name"] == "辉夜"
        assert ext["tags"] == ["恋爱"]
        # 本地笔记 content + tags
        note = next(i for i in d["items"] if i["source"] == "local")
        assert "RAG" in note["tags"]
        assert note["content"]
        # sources / llm_providers：config 为占位符，无明文 key
        src = next(s for s in d["sources"] if s["name"] == "connector_settings")
        assert '"proxy_url"' in src["config_ref"]
        prov = d["llm_providers"][0]
        assert prov["api_key_ref"] == "{DEEPSEEK_API_KEY}"  # 占位符，非明文


class TestImport:
    def test_import_restores_fresh(self, db, fake_collection, patch_embeddings):
        _seed(db)
        data = backup.export_backup(db)
        _wipe(db)  # 模拟空的新实例
        stats = backup.run_import(data, db)
        assert stats["items_imported"] == 2
        assert stats["items_updated"] == 0
        assert stats["reviews_imported"] == 1

        assert db.query(Item).count() == 2
        note = db.query(Item).filter(Item.source == "local").first()
        assert "RAG" in [t.name for t in note.tags]
        assert note.chunks  # 向量已重建
        ext = db.query(Item).filter(Item.external_id == "301").first()
        assert ext.raw_metadata["detail"]["metadata"]["characters"][0]["name"] == "辉夜"
        assert ext.chunks  # 外部参考资料向量重建
        r = db.query(Review).first()
        assert r.content == "这是我写的读后感内容" * 20
        assert r.rating == 9
        # 标签/数据源/Provider 恢复
        assert db.query(Tag).filter(Tag.name == "恋爱").count() == 1
        assert db.query(Source).filter(Source.name == "connector_settings").count() == 1
        assert db.query(LLMProviderConfig).filter(LLMProviderConfig.name == "deepseek").count() == 1

    def test_import_idempotent_merge(self, db, fake_collection, patch_embeddings):
        _seed(db)
        data = backup.export_backup(db)
        # 导入到已有数据的实例：全部命中 → 更新不新建
        stats = backup.run_import(data, db)
        assert stats["items_imported"] == 0
        assert stats["items_updated"] == 2
        assert stats["reviews_imported"] == 0
        assert stats["reviews_skipped"] == 1
        assert db.query(Item).count() == 2  # 无重复
        assert db.query(Review).count() == 1
        # 再导入一次仍幂等
        stats2 = backup.run_import(data, db)
        assert stats2["items_imported"] == 0
        assert db.query(Item).count() == 2
        assert db.query(Review).count() == 1

    def test_invalid_format_rejected(self, db):
        with __import__("pytest").raises(ValueError):
            backup.run_import({"format": "other"}, db)


class TestBackupRoutes:
    def test_export_route(self, db, fake_collection, patch_embeddings):
        _seed(db)
        r = _mk_client(db).get("/api/backup/export")
        assert r.status_code == 200
        body = r.json()
        assert body["format"] == "tsumugi-library"
        assert len(body["data"]["items"]) == 2

    def test_import_route_job(self, db, fake_collection, patch_embeddings):
        _seed(db)
        data = backup.export_backup(db)
        c = _mk_client(db)
        r = c.post("/api/backup/import", json=data)
        assert r.status_code == 200
        job_id = r.json()["job_id"]
        st = None
        for _ in range(100):
            st = c.get(f"/api/backup/import/status/{job_id}").json()
            if st["state"] in ("done", "error"):
                break
            time.sleep(0.1)
        assert st["state"] == "done", st
        assert st["updated"] == 2  # 已存在条目 → 全部更新，无重复
        assert st["imported"] == 0
        assert db.query(Item).count() == 2

    def test_import_status_404(self):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        r = TestClient(app).get("/api/backup/import/status/nope")
        assert r.status_code == 404
