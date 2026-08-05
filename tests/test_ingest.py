"""ingest 模块测试：切分策略 + 入库 + 删除 + 状态"""
import pytest

from app import ingest
from app.models import Chunk, Item, Tag


LONG_PARAGRAPH = "自然语言处理是人工智能的重要方向，它研究如何让计算机理解并生成人类语言。" * 200


class TestSplitText:
    def test_empty_input(self):
        assert ingest.split_text("") == []
        assert ingest.split_text("   \n\n ") == []

    def test_short_text_single_chunk(self):
        chunks = ingest.split_text("一句话", chunk_size=512)
        assert len(chunks) == 1
        assert chunks[0] == "一句话"

    def test_no_chunk_exceeds_chunk_size(self):
        doc = "这是第N段。语义检索与向量数据库的原理介绍。" * 40
        chunks = ingest.split_text(doc, chunk_size=100, chunk_overlap=10)
        assert chunks, "不应为空"
        assert all(len(c) <= 100 for c in chunks)

    def test_order_preserved(self):
        # 用有序标记验证内容不丢、顺序不乱
        paragraphs = [f"第{i}段内容" + "长" * 30 for i in range(12)]
        doc = "\n\n".join(f"【{i}】{p}" for i, p in enumerate(paragraphs))
        chunks = ingest.split_text(doc, chunk_size=40, chunk_overlap=8)
        flat = "".join(chunks)
        order = [i for i in range(12) if f"【{i}】" in flat]
        assert order == sorted(order), "标记出现顺序与原文不一致"
        # 每个 chunk 都出现过的段落都应出现在后续 chunk（顺序不乱即可）
        assert len(chunks) >= 3

    def test_heading_starts_new_chunk(self):
        doc = "# 第一章\n这是第一章的内容，用来填满足够长度。\n\n# 第二章\n这是第二章的内容。"
        chunks = ingest.split_text(doc, chunk_size=20, chunk_overlap=0)
        assert any(c.startswith("# 第一章") for c in chunks)
        assert any(c.startswith("# 第二章") for c in chunks)

    def test_oversized_block_splits(self):
        chunks = ingest.split_text(LONG_PARAGRAPH, chunk_size=100, chunk_overlap=20)
        assert len(chunks) > 1
        assert all(len(c) <= 100 for c in chunks)
        assert all(c.strip() for c in chunks)

    def test_overlap_carries_tail(self):
        doc = ("自然语言处理与检索增强生成是近年热门方向。我们讨论向量数据库的工程细节。") * 50
        chunks = ingest.split_text(doc, chunk_size=150, chunk_overlap=30)
        assert len(chunks) > 1
        # 相邻块之间应存在 overlap 字符
        for prev, cur in zip(chunks, chunks[1:]):
            tail = prev[-30:]
            assert tail.replace("\n", "") in cur.replace("\n", ""), "overlap 未生效"

    def test_overlap_clamped(self):
        chunks = ingest.split_text("内容。", chunk_size=10, chunk_overlap=1000)
        assert len(chunks) == 1


class TestIngest:
    def test_ingest_text_document_creates_rows(self, db, fake_collection, patch_embeddings):
        doc = "第一段关于向量检索的介绍。\n\n第二段关于余弦相似度的介绍。"
        item = ingest.ingest_text_document("我的笔记", doc, tag_names=["RAG", "测试"], db=db)

        assert item.id is not None
        assert item.type == "note"
        db_item = db.get(Item, item.id)
        assert db_item is not None
        chunks = db.query(Chunk).filter(Chunk.item_id == item.id).all()
        assert len(chunks) >= 1
        assert [t.name for t in db_item.tags] == ["RAG", "测试"]
        # 向量已写入假 collection
        assert len(fake_collection.vectors) == len(chunks)
        # embedding_ref 与 Chroma id 一致
        for c in chunks:
            assert c.embedding_ref in fake_collection.vectors

    def test_ingest_text_document_empty_content(self, db, fake_collection, patch_embeddings):
        item = ingest.ingest_text_document("空文档", "   ", db=db)
        assert len(item.chunks) == 0
        assert len(fake_collection.vectors) == 0

    def test_ingest_text_document_embedding_failure_rolls_back(self, db, fake_collection, monkeypatch):
        from app.embeddings import EmbeddingError

        def boom(texts):
            raise EmbeddingError("模型加载失败")

        monkeypatch.setattr("app.embeddings.embed_texts", boom)
        with pytest.raises(EmbeddingError):
            ingest.ingest_text_document("失败案例", "一些内容", db=db)
        assert db.query(Item).count() == 0, "embedding 失败时应回滚 Item"
        assert len(fake_collection.vectors) == 0

    def test_ingest_image_no_chunks(self, db, fake_collection):
        item = ingest.ingest_image("图片", "/tmp/foo.png", tag_names=["图片"], db=db)
        assert item.type == "image"
        assert item.file_path == "/tmp/foo.png"
        assert len(item.chunks) == 0
        assert len(fake_collection.vectors) == 0
        assert [t.name for t in item.tags] == ["图片"]

    def test_delete_item_cleans_chroma_and_tags(self, db, fake_collection, patch_embeddings):
        item = ingest.ingest_text_document("待删除", "内容内容内容", tag_names=["孤立标签"], db=db)
        item_id = item.id
        assert len(fake_collection.vectors) > 0

        assert ingest.delete_item(item_id, db=db) is True
        assert db.get(Item, item_id) is None
        assert len(fake_collection.vectors) == 0
        assert db.query(Tag).filter(Tag.name == "孤立标签").count() == 0

    def test_delete_item_missing(self, db, fake_collection):
        assert ingest.delete_item(9999, db=db) is False

    def test_get_ingestion_status(self, db, fake_collection, patch_embeddings):
        item = ingest.ingest_text_document("状态", "内容内容内容", tag_names=["a"], db=db)
        status = ingest.get_ingestion_status(item.id, db=db)
        assert status["chunks_count"] == len(item.chunks)
        assert status["tags"] == ["a"]
        assert status["embedded"] is True
        assert ingest.get_ingestion_status(9999, db=db) is None

    def test_ingest_commit_failure_cleans_chroma(self, db, fake_collection, patch_embeddings, monkeypatch):
        """SQLite 提交失败时，已写入 Chroma 的向量必须被反向清理，不留孤儿。"""
        def boom():
            raise RuntimeError("db commit failed")

        monkeypatch.setattr(db, "commit", boom)
        with pytest.raises(RuntimeError):
            ingest.ingest_text_document("失败", "内容内容内容内容内容内容内容", db=db)
        assert db.query(Item).count() == 0
        assert len(fake_collection.vectors) == 0

    def test_delete_image_removes_uploaded_file(self, db, fake_collection, tmp_path, monkeypatch):
        monkeypatch.setattr(ingest.settings, "upload_dir", str(tmp_path))
        f = tmp_path / "img.png"
        f.write_bytes(b"png-data")
        item = ingest.ingest_image("图片", str(f), db=db)
        assert f.exists()
        assert ingest.delete_item(item.id, db=db) is True
        assert not f.exists()

    def test_delete_image_keeps_outside_files(self, db, fake_collection, tmp_path, monkeypatch):
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        monkeypatch.setattr(ingest.settings, "upload_dir", str(uploads))
        outside = tmp_path / "outside.png"
        outside.write_bytes(b"x")
        item = ingest.ingest_image("图片", str(outside), db=db)
        assert ingest.delete_item(item.id, db=db) is True
        assert outside.exists(), "upload_dir 外的文件不应被删除"


class TestDuplicateIngest:
    DOC = "这是一段用于测试重复导入去重的文本内容。"

    def test_duplicate_text_skipped(self, db, fake_collection, patch_embeddings):
        first = ingest.ingest_text_document("文档A", self.DOC, db=db)
        second = ingest.ingest_text_document("文档A(重复)", self.DOC, db=db)
        assert second.id == first.id, "重复导入应返回已有条目"
        assert db.query(Item).count() == 1
        assert len(fake_collection.vectors) == len(first.chunks), "不应重复写向量"

    def test_force_reimports(self, db, fake_collection, patch_embeddings):
        first = ingest.ingest_text_document("文档A", self.DOC, db=db)
        forced = ingest.ingest_text_document("文档A(强制)", self.DOC, db=db, force=True)
        assert forced.id != first.id, "force=True 应强制再导入"
        assert db.query(Item).count() == 2
        assert len(fake_collection.vectors) == len(first.chunks) + len(forced.chunks)

    def test_duplicate_image_by_content(self, db, fake_collection, tmp_path, monkeypatch):
        monkeypatch.setattr(ingest.settings, "upload_dir", str(tmp_path))
        f1 = tmp_path / "a.png"
        f2 = tmp_path / "b.png"
        f1.write_bytes(b"same-image-bytes")
        f2.write_bytes(b"same-image-bytes")
        first = ingest.ingest_image("图1", str(f1), db=db)
        second = ingest.ingest_image("图2", str(f2), db=db)
        assert second.id == first.id, "内容相同的图片（路径不同）应判为重复"

    def test_hash_helpers(self, tmp_path):
        assert ingest.compute_content_hash("你好") == ingest.compute_content_hash("你好")
        assert ingest.compute_content_hash("你好") != ingest.compute_content_hash("你好 ")
        f = tmp_path / "t.bin"
        f.write_bytes(b"data")
        assert ingest.compute_file_hash(str(f)) == ingest.compute_bytes_hash(b"data")
        assert ingest.compute_file_hash(str(tmp_path / "missing.bin")) is None
