"""retrieval 模块测试：排序、去重、tag 过滤、top_k、来源区分（ADR 0025）"""
import math

import pytest

from app.models import Chunk, Item, Tag
from app.retrieval import detect_query_intent, retrieve_chunks

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


def _add_external_item(db, col, title, source, content, sim):
    """创建外部条目（external_ref）与 external_reference chunk（带 connector）。"""
    item = Item(title=title, type="external_ref", source=source, external_id="1")
    db.add(item)
    db.flush()
    ref = f"item{item.id}_chunk0"
    db.add(Chunk(item_id=item.id, content=content, chunk_index=0, embedding_ref=ref,
                 source_type="external_reference", connector=source))
    col.add(ids=[ref], embeddings=[vec_with_similarity(sim)], documents=[content],
            metadatas=[{"item_id": item.id, "chunk_index": 0,
                        "source_type": "external_reference", "connector": source}])
    db.commit()
    return item


class TestQueryIntent:
    def test_personal_query(self):
        assert detect_query_intent("我为什么喜欢这部作品").personal is True
        assert detect_query_intent("我为什么喜欢这部作品").recommendation is False

    def test_temporal_query_is_personal_too(self):
        it = detect_query_intent("去年我看了什么")
        assert it.personal is True
        assert it.temporal is True

    def test_recommendation_query_is_personal_too(self):
        it = detect_query_intent("推荐几个我想重温的作品")
        assert it.recommendation is True
        assert it.personal is True

    def test_plain_query_has_no_intent(self):
        it = detect_query_intent("什么是RAG？")
        assert not it.personal and not it.temporal and not it.recommendation


def _add_source_item(db, col, title, source_type, content, sim):
    """创建带指定 source_type 的 chunk（memory / review / note 等）。"""
    item = Item(title=title, type="note", source="local")
    db.add(item)
    db.flush()
    ref = f"item{item.id}_chunk0"
    db.add(Chunk(item_id=item.id, content=content, chunk_index=0, embedding_ref=ref,
                 source_type=source_type))
    col.add(ids=[ref], embeddings=[vec_with_similarity(sim)], documents=[content],
            metadatas=[{"item_id": item.id, "chunk_index": 0, "source_type": source_type}])
    db.commit()
    return item


class TestIntentStrategy:
    def test_personal_intent_excludes_external_when_personal_sufficient(
        self, db, fake_collection, fixed_query_embedding
    ):
        """个人问题：个人内容足够（≥top_k）时，外部百科即使相似度更高也被排除。"""
        for i in range(3):
            _add_source_item(db, fake_collection, f"记忆{i}", "memory", f"关于这部作品的记忆片段{i}", 0.5)
        for i in range(2):
            add_item(db, fake_collection, f"笔记{i}", [], [(f"我的感想片段{i}", 0.5)])
        _add_external_item(db, fake_collection, "百科", "bangumi", "作品的完整背景设定。", 0.95)
        results = retrieve_chunks("我为什么喜欢这部作品", top_k=5, max_chunks_per_item=5, db=db)
        assert len(results) == 5
        assert all(h.source_type in ("note", "memory") for h in results), "个人充足时应排除外部抢占"
        assert results[0].item_title.startswith(("记忆", "笔记"))

    def test_personal_intent_external_fallback_when_personal_insufficient(
        self, db, fake_collection, fixed_query_embedding
    ):
        """个人问题：个人内容不足时，外部百科兜底补位（仍排在个人之后）。"""
        _add_source_item(db, fake_collection, "记忆", "memory", "一条个人记忆。", 0.5)
        _add_external_item(db, fake_collection, "百科", "bangumi", "高相关外部资料。", 0.95)
        results = retrieve_chunks("我为什么喜欢这部作品", top_k=5, max_chunks_per_item=5, db=db)
        sources = [h.source_type for h in results]
        assert "memory" in sources
        assert "external_reference" in sources, "个人不足时应外部兜底"
        assert sources.index("memory") < sources.index("external_reference")

    def test_recommendation_expands_candidate_pool(self, db, fake_collection, fixed_query_embedding, monkeypatch):
        """推荐/时间意图扩大候选池（40→80）；普通问题不扩大。"""
        add_item(db, fake_collection, "文档", [], [("内容", 0.9)])
        calls = []
        orig = fake_collection.query

        def spy(*a, **k):
            calls.append(k.get("n_results"))
            return orig(*a, **k)

        monkeypatch.setattr(fake_collection, "query", spy)
        retrieve_chunks("推荐几部作品", top_k=5, db=db)
        assert calls and calls[0] >= 80, "推荐意图应扩大候选池到 80"
        calls.clear()
        retrieve_chunks("查询", top_k=5, db=db)
        assert calls and calls[0] < 80, "普通问题候选池保持默认（40）"

    def test_plain_query_unchanged(self, db, fake_collection, fixed_query_embedding):
        """普通问题：行为与策略前一致（个人/外部混合按权重排序）。"""
        add_item(db, fake_collection, "我的笔记", [], [("感想。", 0.8)])
        _add_external_item(db, fake_collection, "百科", "bangumi", "外部简介。", 0.8)
        results = retrieve_chunks("查询", top_k=5, max_chunks_per_item=5, db=db)
        assert results[0].source_type == "note"
        assert results[0].score == 0.8
        ext = [h for h in results if h.source_type == "external_reference"]
        assert ext and ext[0].score == round(0.8 * 0.4, 4)


class TestSourceTypeRanking:
    def test_external_reference_penalized_behind_user_content(self, db, fake_collection, fixed_query_embedding):
        """用户笔记与外部百科相似度相同 → 用户内容排前面（1.0 vs 0.4 加权）。"""
        add_item(db, fake_collection, "我的笔记", [], [("这是我自己写的感想。", 0.8)])
        _add_external_item(db, fake_collection, "百科条目", "bangumi", "这是外部简介。", 0.8)
        results = retrieve_chunks("查询", top_k=5, max_chunks_per_item=5, db=db)
        assert results[0].source_type == "note"
        assert results[0].item_title == "我的笔记"
        assert results[0].score == 0.8
        ext_hits = [h for h in results if h.source_type == "external_reference"]
        assert ext_hits
        assert ext_hits[0].connector == "bangumi"
        assert results.index(ext_hits[0]) > results.index(results[0])
        assert ext_hits[0].score == round(0.8 * 0.4, 4)

    def test_external_reference_still_surfaces_for_factual_high_similarity(
        self, db, fake_collection, fixed_query_embedding, monkeypatch
    ):
        """外部百科相似度明显更高（事实性问题）时，即使加权仍能进入结果前列。"""
        add_item(db, fake_collection, "我的笔记", [], [("泛泛而谈的感想。", 0.3)])
        _add_external_item(db, fake_collection, "百科条目", "bangumi", "角色的完整设定与背景资料。", 0.9)
        results = retrieve_chunks("查询", top_k=5, max_chunks_per_item=5, db=db)
        ext = [h for h in results if h.source_type == "external_reference"]
        assert ext, "高相似度外部资料应仍被召回"
        assert ext[0].score == round(0.9 * 0.4, 4) > 0.3  # 0.36 > 0.3，仍排用户内容前

    def test_source_types_filter_only_user(self, db, fake_collection, fixed_query_embedding):
        add_item(db, fake_collection, "我的笔记", [], [("笔记内容。", 0.8)])
        _add_external_item(db, fake_collection, "百科", "bangumi", "外部内容。", 0.9)
        only_user = retrieve_chunks("查询", top_k=5, source_types=["note"], db=db)
        assert only_user
        assert all(h.source_type == "note" for h in only_user)
        assert {h.item_title for h in only_user} == {"我的笔记"}
        only_ext = retrieve_chunks("查询", top_k=5, source_types=["external_reference"], db=db)
        assert only_ext
        assert all(h.source_type == "external_reference" for h in only_ext)
        assert {h.item_title for h in only_ext} == {"百科"}
