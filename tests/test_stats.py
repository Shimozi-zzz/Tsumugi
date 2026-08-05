"""stats 模块测试：统计聚合、来源分类、token 估算"""
import pytest

from app import stats
from app.ingest import ingest_external, ingest_text_document
from app.models import Item


class TestClassifySource:
    def test_note_defaults_to_markdown(self):
        item = Item(title="我的笔记", type="note", source="local")
        assert stats._classify_source(item) == "markdown"

    def test_txt_extension(self):
        item = Item(title="readme.txt", type="note", source="local")
        assert stats._classify_source(item) == "txt"

    def test_pdf_extension(self):
        item = Item(title="手册.pdf", type="note", source="local")
        assert stats._classify_source(item) == "pdf"

    def test_external_ref_is_web(self):
        item = Item(title="辉夜", type="external_ref", source="bangumi")
        assert stats._classify_source(item) == "web"

    def test_local_external_source_is_web(self):
        item = Item(title="x", type="external_ref", source="local")
        assert stats._classify_source(item) == "web"


class TestEstimateTokens:
    def test_positive(self):
        assert stats._estimate_tokens("中文内容" * 100) > 0

    def test_empty(self):
        assert stats._estimate_tokens("") == 0


class TestGetStats:
    def test_empty_db(self, db):
        data = stats.get_stats(db=db)
        assert data["total_chars"] == 0
        assert data["total_tokens"] == 0
        assert data["chunk_count"] == 0
        assert data["item_count"] == 0
        assert sum(d["count"] for d in data["distribution"]) == 0
        assert data["top_files"] == []

    def test_with_items(self, db, fake_collection, patch_embeddings):
        ingest_text_document("笔记.md", "你好世界" * 50, db=db)
        ingest_text_document("说明.txt", "plain text" * 30, db=db)
        ingest_external(source="bangumi", external_id="1", title="外部", content="摘要" * 10, db=db)

        data = stats.get_stats(db=db)
        assert data["item_count"] == 3
        assert data["total_chars"] == 50 * 4 + 30 * 10 + 10 * 2
        assert data["total_tokens"] > 0
        assert data["chunk_count"] >= 1

        dist = {d["label"]: d["count"] for d in data["distribution"]}
        assert dist["Markdown"] == 1
        assert dist["TXT"] == 1
        assert dist["Web Crawl"] == 1

        assert len(data["top_files"]) == 3
        # 按字符数降序
        chars = [f["chars"] for f in data["top_files"]]
        assert chars == sorted(chars, reverse=True)

    def test_source_distribution_sums_to_item_count(self, db, fake_collection, patch_embeddings):
        ingest_text_document("a.md", "内容", db=db)
        data = stats.get_stats(db=db)
        assert sum(d["count"] for d in data["distribution"]) == data["item_count"]
