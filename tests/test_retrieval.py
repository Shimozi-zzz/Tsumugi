"""retrieval 模块测试：排序、去重、tag 过滤、top_k"""
import math

import pytest

from app.models import Chunk, Item, Tag
from app.retrieval import retrieve_chunks

QUERY_VEC = [1.0, 0, 0, 0, 0, 0, 0, 0]


@pytest.fixture(scope="function")
def fixed_query_embedding(monkeypatch):
    """查询向量固定为 [1,0,...]，便于精确控制相似度排序。"""
    monkeypatch.setattr("app.embeddings.embed_query", lambda text: list(QUERY_VEC))


def vec_with_similarity(sim: float) -> list:
    """构造与查询向量的余弦相似度恰为 sim 的单位向量。"""
    sim = min(max(sim, 0.0), 1.0)
    y = math.sqrt(max(1.0 - sim * sim, 0.0))
    return [float(sim), y, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def add_item(db, col, title: str, tag_names, chunks):
    """创建 Item(+tags) 与 Chunk 行，并把向量写入假 collection。
    chunks: [(content, similarity), ...]
    """
    item = Item(title=title, type="note", source="local")
    db.add(item)
    db.flush()
    for name in tag_names:
        tag = db.query(Tag).filter(Tag.name == name).first()
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        item.tags.append(tag)
    for i, (content, sim) in enumerate(chunks):
        ref = f"item{item.id}_chunk{i}"
        db.add(Chunk(item_id=item.id, content=content, chunk_index=i, embedding_ref=ref))
        col.add(ids=[ref], embeddings=[vec_with_similarity(sim)], documents=[content],
                metadatas=[{"item_id": item.id, "chunk_index": i}])
    db.commit()
    return item


class TestRetrieveChunks:
    def test_basic_sorted(self, db, fake_collection, fixed_query_embedding):
        add_item(db, fake_collection, "文档A", [], [("关于向量检索。", 0.5), ("关于排序。", 0.3)])
        add_item(db, fake_collection, "文档B", [], [("最相关的内容。", 0.9)])
        results = retrieve_chunks("查询", top_k=5, max_chunks_per_item=2, db=db)
        assert len(results) == 3
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)
        assert results[0].content == "最相关的内容。"

    def test_top_k(self, db, fake_collection, fixed_query_embedding):
        add_item(db, fake_collection, "文档A", [], [("A1", 0.9), ("A2", 0.8), ("A3", 0.7)])
        add_item(db, fake_collection, "文档B", [], [("B1", 0.6)])
        results = retrieve_chunks("查询", top_k=2, db=db)
        assert len(results) == 2
        # top_k 限制生效，B 的相似度更低，不应出现在 top2
        assert {r.item_title for r in results} == {"文档A", "文档B"}

    def test_dedup_exact_content(self, db, fake_collection, fixed_query_embedding):
        add_item(db, fake_collection, "文档A", [], [("相同内容", 0.9), ("相同内容", 0.6)])
        results = retrieve_chunks("查询", top_k=5, db=db)
        contents = [r.content for r in results]
        assert len(contents) == len(set(contents))

    def test_dedup_per_item_cap(self, db, fake_collection, fixed_query_embedding):
        add_item(db, fake_collection, "文档A", [], [("A1", 0.9), ("A2", 0.8), ("A3", 0.7)])
        add_item(db, fake_collection, "文档B", [], [("B1", 0.6)])
        # 默认每 item 最多 1 条
        results = retrieve_chunks("查询", top_k=5, db=db)
        assert len(results) == 2
        assert results[0].item_id != results[1].item_id
        # 放宽上限后能看到同 item 的更多 chunk
        results2 = retrieve_chunks("查询", top_k=5, max_chunks_per_item=2, db=db)
        assert len(results2) == 3
        assert results2[0].content == "A1" and results2[1].content == "A2"

    def test_tag_filter(self, db, fake_collection, fixed_query_embedding):
        add_item(db, fake_collection, "带标签文档", ["RAG"], [("标签文档内容。", 0.9)])
        add_item(db, fake_collection, "无标签文档", [], [("无标签内容。", 0.9)])
        results = retrieve_chunks("查询", top_k=5, tags=["RAG"], db=db)
        assert len(results) == 1
        assert results[0].item_title == "带标签文档"
        assert results[0].tags == ["RAG"]

    def test_tag_filter_multiple_items(self, db, fake_collection, fixed_query_embedding):
        add_item(db, fake_collection, "文档一", ["RAG"], [("内容一", 0.9)])
        add_item(db, fake_collection, "文档二", ["RAG"], [("内容二", 0.8)])
        add_item(db, fake_collection, "文档三", [], [("无关内容", 0.7)])
        results = retrieve_chunks("查询", top_k=5, tags=["RAG"], db=db)
        assert {r.item_title for r in results} == {"文档一", "文档二"}

    def test_tag_filter_no_match_returns_empty(self, db, fake_collection, fixed_query_embedding):
        add_item(db, fake_collection, "文档", ["a"], [("内容", 0.9)])
        results = retrieve_chunks("查询", top_k=5, tags=["不存在的标签"], db=db)
        assert results == []

    def test_empty_collection(self, db, fake_collection, fixed_query_embedding):
        assert retrieve_chunks("查询", db=db) == []

    def test_blank_query(self, db, fake_collection, fixed_query_embedding):
        add_item(db, fake_collection, "文档", [], [("内容", 0.9)])
        assert retrieve_chunks("   ", db=db) == []

    def test_metadata_loaded(self, db, fake_collection, fixed_query_embedding):
        add_item(db, fake_collection, "标题验证", ["tag1", "tag2"], [("内容。", 0.9)])
        results = retrieve_chunks("查询", top_k=5, db=db)
        assert results[0].item_title == "标题验证"
        assert set(results[0].tags) == {"tag1", "tag2"}

    def test_tag_match_all_requires_all_tags(self, db, fake_collection, fixed_query_embedding):
        add_item(db, fake_collection, "双标签文档", ["RAG", "向量库"], [("双标签内容。", 0.9)])
        add_item(db, fake_collection, "单标签文档", ["RAG"], [("单标签内容。", 0.8)])
        # any：两个都命中
        results_any = retrieve_chunks("查询", top_k=5, tags=["RAG", "向量库"], tag_match="any", db=db)
        assert {r.item_title for r in results_any} == {"双标签文档", "单标签文档"}
        # all：只有同时含两个标签的命中
        results_all = retrieve_chunks("查询", top_k=5, tags=["RAG", "向量库"], tag_match="all", db=db)
        assert [r.item_title for r in results_all] == ["双标签文档"]

    def test_tag_match_all_no_match(self, db, fake_collection, fixed_query_embedding):
        add_item(db, fake_collection, "单标签文档", ["RAG"], [("内容。", 0.9)])
        results = retrieve_chunks("查询", top_k=5, tags=["RAG", "不存在"], tag_match="all", db=db)
        assert results == []
