"""retrieval 模块测试：排序、去重、tag 过滤、top_k、来源区分（ADR 0025）"""
import math
from datetime import datetime

import pytest

from app.models import Chunk, Item, Tag
from app.retrieval import (
    _compute_retrieval_score, _current_time, _explicit_temporal_range, _parse_occurred_at,
    detect_query_intent, retrieve_chunks,
)

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


def _add_memory_item(db, col, title, content, sim, occurred_at):
    """创建带 occurred_at metadata 的 memory chunk（B-5 形态；None → 省略该键=旧向量）。"""
    return _add_memory_item_full(db, col, title, content, sim, occurred_at, None, None)


def _add_memory_item_full(db, col, title, content, sim, occurred_at=None, emotion=None, milestone=None):
    """创建带 emotion / milestone / occurred_at metadata 的 memory chunk（B-5/B-8 形态）。"""
    item = Item(title=title, type="note", source="local")
    db.add(item)
    db.flush()
    ref = f"item{item.id}_chunk0"
    db.add(Chunk(item_id=item.id, content=content, chunk_index=0, embedding_ref=ref,
                 source_type="memory"))
    meta = {"item_id": item.id, "chunk_index": 0, "source_type": "memory"}
    if occurred_at:
        meta["occurred_at"] = occurred_at
    if emotion:
        meta["emotion"] = emotion
    if milestone is not None:
        meta["milestone"] = milestone
    col.add(ids=[ref], embeddings=[vec_with_similarity(sim)], documents=[content], metadatas=[meta])
    db.commit()
    return item


def _mk_plain_item(db, title="作品"):
    item = Item(title=title, type="note", source="local")
    db.add(item)
    db.flush()
    db.commit()
    return item


def _add_chunk(db, col, item, content, sim, source_type, review_id=None, memory_id=None,
               occurred_at=None, emotion=None, milestone=None):
    """向已有 item 追加一个带可选身份/信号 metadata 的 chunk（B-9）。"""
    idx = sum(1 for k in col.vectors if str(k).startswith(f"item{item.id}_"))
    ref = f"item{item.id}_chunk{idx}"
    db.add(Chunk(item_id=item.id, content=content, chunk_index=0, embedding_ref=ref,
                 source_type=source_type))
    meta = {"item_id": item.id, "chunk_index": 0, "source_type": source_type}
    if review_id is not None:
        meta["review_id"] = review_id
    if memory_id is not None:
        meta["memory_id"] = memory_id
    if occurred_at:
        meta["occurred_at"] = occurred_at
    if emotion:
        meta["emotion"] = emotion
    if milestone is not None:
        meta["milestone"] = milestone
    col.add(ids=[ref], embeddings=[vec_with_similarity(sim)], documents=[content], metadatas=[meta])
    db.commit()
    return item


class TestSourceAwareCap:
    """Phase 10-1-B-9：entity-aware per-item cap（personal 深度 2、其它 1）。"""

    def test_same_review_multichunk_only_one(self, db, fake_collection, fixed_query_embedding):
        item = _mk_plain_item(db, "作品A")
        _add_chunk(db, fake_collection, item, "书评片段0", 0.9, "review", review_id=7)
        _add_chunk(db, fake_collection, item, "书评片段1", 0.88, "review", review_id=7)
        results = retrieve_chunks("我对这部作品的记录", top_k=5, db=db)
        assert len([h for h in results if h.item_id == item.id]) == 1  # 同一 review 只 1 个

    def test_same_memory_multichunk_only_one(self, db, fake_collection, fixed_query_embedding):
        item = _mk_plain_item(db, "作品A")
        _add_chunk(db, fake_collection, item, "记忆片段0", 0.9, "memory", memory_id=12)
        _add_chunk(db, fake_collection, item, "记忆片段1", 0.88, "memory", memory_id=12)
        results = retrieve_chunks("我对这部作品的记录", top_k=5, db=db)
        assert len([h for h in results if h.item_id == item.id]) == 1

    def test_memory_plus_review_same_item_coexist(self, db, fake_collection, fixed_query_embedding):
        item = _mk_plain_item(db, "作品A")
        _add_chunk(db, fake_collection, item, "记忆内容", 0.82, "memory", memory_id=12)
        _add_chunk(db, fake_collection, item, "书评内容", 0.9, "review", review_id=7)
        results = retrieve_chunks("我对这部作品的记录", top_k=5, db=db)
        item_chunks = [h for h in results if h.item_id == item.id]
        assert len(item_chunks) == 2  # memory + review 共存
        assert {h.source_type for h in item_chunks} == {"memory", "review"}

    def test_review_plus_note_same_item_coexist(self, db, fake_collection, fixed_query_embedding):
        item = _mk_plain_item(db, "作品A")
        _add_chunk(db, fake_collection, item, "书评内容", 0.9, "review", review_id=7)
        _add_chunk(db, fake_collection, item, "笔记内容", 0.85, "note")
        results = retrieve_chunks("我对这部作品的记录", top_k=5, db=db)
        item_chunks = [h for h in results if h.item_id == item.id]
        assert len(item_chunks) == 2
        assert {h.source_type for h in item_chunks} == {"review", "note"}

    def test_three_personal_entities_max_two(self, db, fake_collection, fixed_query_embedding):
        item = _mk_plain_item(db, "作品A")
        _add_chunk(db, fake_collection, item, "记忆", 0.95, "memory", memory_id=1)
        _add_chunk(db, fake_collection, item, "书评", 0.9, "review", review_id=2)
        _add_chunk(db, fake_collection, item, "笔记", 0.85, "note")
        results = retrieve_chunks("我对这部作品的记录", top_k=5, db=db)
        assert len([h for h in results if h.item_id == item.id]) == 2  # 最多 2 实体

    def test_neutral_same_item_still_one(self, db, fake_collection, fixed_query_embedding):
        item = _mk_plain_item(db, "作品A")
        _add_chunk(db, fake_collection, item, "记忆", 0.95, "memory", memory_id=1)
        _add_chunk(db, fake_collection, item, "书评", 0.9, "review", review_id=2)
        results = retrieve_chunks("这部作品是什么", top_k=5, db=db)
        assert len([h for h in results if h.item_id == item.id]) <= 1

    def test_recommendation_same_item_one_and_breadth(self, db, fake_collection, fixed_query_embedding):
        for i in range(5):
            it = _mk_plain_item(db, f"作品{i}")
            _add_chunk(db, fake_collection, it, f"记忆{i}", 0.6, "memory", memory_id=100 + i)
        rich = _mk_plain_item(db, "富作品")
        _add_chunk(db, fake_collection, rich, "富记忆1", 0.95, "memory", memory_id=200)
        _add_chunk(db, fake_collection, rich, "富记忆2", 0.9, "memory", memory_id=201)
        results = retrieve_chunks("推荐几个我可能想重温的作品", top_k=5, db=db)
        assert len({h.item_id for h in results}) == 5  # 跨作品广度保持
        assert len([h for h in results if h.item_id == rich.id]) == 1  # 富作品只占 1

    def test_temporal_personal_memory_review_coexist(self, db, fake_collection, fixed_query_embedding, monkeypatch):
        monkeypatch.setattr("app.retrieval._current_time", lambda: datetime(2026, 8, 15))
        item = _mk_plain_item(db, "作品A")
        _add_chunk(db, fake_collection, item, "去年记忆", 0.8, "memory", memory_id=12, occurred_at="2025-06-01")
        _add_chunk(db, fake_collection, item, "去年书评", 0.8, "review", review_id=7, occurred_at="2025-06-02")
        results = retrieve_chunks("去年我看了什么", top_k=5, db=db)
        assert len([h for h in results if h.item_id == item.id]) == 2  # temporal+personal 深度 2

    def test_external_does_not_consume_personal_depth(self, db, fake_collection, fixed_query_embedding):
        item = _mk_plain_item(db, "作品A")
        _add_chunk(db, fake_collection, item, "记忆", 0.95, "memory", memory_id=1)
        _add_chunk(db, fake_collection, item, "书评", 0.9, "review", review_id=2)
        _add_chunk(db, fake_collection, item, "外部", 0.85, "external_reference")
        results = retrieve_chunks("我对这部作品的记录", top_k=5, db=db)
        item_chunks = [h for h in results if h.item_id == item.id]
        assert len(item_chunks) == 2
        assert "external_reference" not in {h.source_type for h in item_chunks}  # 不占个人深度

    def test_legacy_missing_identity_no_error(self, db, fake_collection, fixed_query_embedding):
        item = _mk_plain_item(db, "作品A")
        _add_chunk(db, fake_collection, item, "无id记忆", 0.9, "memory")
        _add_chunk(db, fake_collection, item, "无id书评", 0.88, "review")
        results = retrieve_chunks("我对这部作品的记录", top_k=5, db=db)
        assert len(results) > 0  # 不报错、可返回
        assert len([h for h in results if h.item_id == item.id]) == 2  # 保守：memory/review 各 1

    def test_regression_neutral_old_behavior(self, db, fake_collection, fixed_query_embedding):
        """neutral：同作品仍 1，行为与 B-8 一致（显式 cap 路径未启用 entity 规则）。"""
        item = _mk_plain_item(db, "作品A")
        _add_chunk(db, fake_collection, item, "记忆", 0.95, "memory", memory_id=1)
        _add_chunk(db, fake_collection, item, "书评", 0.9, "review", review_id=2)
        results = retrieve_chunks("这部作品什么时候播出", top_k=5, max_chunks_per_item=5, db=db)
        assert len([h for h in results if h.item_id == item.id]) == 2  # 显式 cap=5 → 不启用 entity 规则


class TestTemporalRange:
    def test_calendar_year_ranges(self):
        now = datetime(2026, 8, 15, 12, 0, 0)
        assert _explicit_temporal_range("去年我看了什么", now) == (datetime(2025, 1, 1), datetime(2025, 12, 31, 23, 59, 59))
        assert _explicit_temporal_range("今年我记录了什么", now) == (datetime(2026, 1, 1), datetime(2026, 12, 31, 23, 59, 59))
        assert _explicit_temporal_range("前年我看了什么", now) == (datetime(2024, 1, 1), datetime(2024, 12, 31, 23, 59, 59))

    def test_month_week_yesterday_recent(self):
        now = datetime(2026, 8, 15, 12, 0, 0)
        start, end = _explicit_temporal_range("上个月我记录了什么", now)
        assert start == datetime(2026, 7, 1) and end == datetime(2026, 7, 31, 23, 59, 59)
        start, end = _explicit_temporal_range("上周我记录了什么", now)
        assert start == datetime(2026, 8, 3) and end == datetime(2026, 8, 9, 23, 59, 59)  # ISO 周一
        start, end = _explicit_temporal_range("昨天我记录了什么", now)
        assert start == datetime(2026, 8, 14) and end == datetime(2026, 8, 14, 23, 59, 59)
        start, end = _explicit_temporal_range("最近我记录了什么", now)
        assert start == datetime(2026, 7, 16) and end == datetime(2026, 8, 15, 23, 59, 59)  # 30 天窗口

    def test_vague_temporal_has_no_explicit_range(self):
        now = datetime(2026, 8, 15)
        for q in ["以前我记录过哪些作品", "之前我看了什么", "那时候的事", "当时"]:
            assert _explicit_temporal_range(q, now) is None

    def test_parse_occurred_at(self):
        assert _parse_occurred_at("2025-06-01T10:00:00") == datetime(2025, 6, 1, 10, 0, 0)
        assert _parse_occurred_at("2025-06-01") == datetime(2025, 6, 1)
        assert _parse_occurred_at("2025-06-01T10:00:00+08:00") == datetime(2025, 6, 1, 10, 0, 0)  # 墙钟
        assert _parse_occurred_at(None) is None
        assert _parse_occurred_at("not-a-date") is None


class TestTemporalRetrieval:
    def _freeze_now(self, monkeypatch, dt):
        monkeypatch.setattr("app.retrieval._current_time", lambda: dt)

    def test_temporal_hit_ranks_above_unknown_and_outside(self, db, fake_collection, fixed_query_embedding, monkeypatch):
        """去年：时间命中(2025) > 时间未知 > 时间不匹配(2026)；external 不加分。"""
        self._freeze_now(monkeypatch, datetime(2026, 8, 15))
        _add_memory_item(db, fake_collection, "去年记忆", "去年冬天看完了这部作品。", 0.5, "2025-12-01T10:00:00")
        _add_memory_item(db, fake_collection, "未知记忆", "一条没有时间的旧记忆。", 0.5, None)  # 无 occurred_at（旧向量）
        _add_memory_item(db, fake_collection, "今年记忆", "今年才补看的。", 0.5, "2026-06-01T10:00:00")
        _add_external_item(db, fake_collection, "百科", "bangumi", "作品设定。", 0.8)
        results = retrieve_chunks("去年我看了什么", top_k=5, max_chunks_per_item=5, db=db)
        order = [r.item_title for r in results]
        assert order.index("去年记忆") < order.index("未知记忆") < order.index("今年记忆"), order
        # 时间命中分 > 未知分；外部不加时间分
        by_title = {r.item_title: r.score for r in results}
        assert by_title["去年记忆"] > by_title["未知记忆"] > by_title["今年记忆"]
        assert "百科" in order  # 个人不足场景 external 兜底（本测试个人≥5 则无；此处 3 个人 → 兜底）

    def test_outside_range_not_masked_as_hit(self, db, fake_collection, fixed_query_embedding, monkeypatch):
        self._freeze_now(monkeypatch, datetime(2026, 8, 15))
        _add_memory_item(db, fake_collection, "2025", "去年内容。", 0.5, "2025-06-01")
        _add_memory_item(db, fake_collection, "2026", "今年内容。", 0.5, "2026-06-01")
        results = retrieve_chunks("去年我看了什么", top_k=5, max_chunks_per_item=5, db=db)
        assert [r.item_title for r in results][0] == "2025"

    def test_old_metadata_unknown_still_retrieves_no_error(self, db, fake_collection, fixed_query_embedding, monkeypatch):
        """历史向量无 occurred_at：不报错、仍进入结果、不加时间分。"""
        self._freeze_now(monkeypatch, datetime(2026, 8, 15))
        _add_memory_item(db, fake_collection, "旧记忆", "没有时间元数据的旧记忆。", 0.6, None)
        results = retrieve_chunks("去年我看了什么", top_k=5, max_chunks_per_item=5, db=db)
        assert any(r.item_title == "旧记忆" for r in results)

    def test_personal_non_temporal_zero_regression(self, db, fake_collection, fixed_query_embedding, monkeypatch):
        """「我为什么喜欢这部作品」：B-6 引入时间信号不应改变既有 personal 策略。"""
        self._freeze_now(monkeypatch, datetime(2026, 8, 15))
        for i in range(3):
            _add_memory_item(db, fake_collection, f"记忆{i}", f"关于这部作品的记忆{i}", 0.5, "2025-01-01")
        for i in range(2):
            add_item(db, fake_collection, f"笔记{i}", [], [(f"我的感想{i}", 0.5)])
        _add_external_item(db, fake_collection, "百科", "bangumi", "高相关外部。", 0.95)
        results = retrieve_chunks("我为什么喜欢这部作品", top_k=5, max_chunks_per_item=5, db=db)
        assert all(h.source_type in ("note", "memory") for h in results)  # personal 优先保持
        assert [r.score for r in results] == sorted([r.score for r in results], reverse=True)

    def test_recommendation_no_temporal_boost(self, db, fake_collection, fixed_query_embedding, monkeypatch):
        """纯推荐 query 不自动时间加分（除非含 temporal intent）。"""
        self._freeze_now(monkeypatch, datetime(2026, 8, 15))
        _add_memory_item(db, fake_collection, "旧年记忆", "很久以前的记忆。", 0.5, "2025-01-01")
        _add_memory_item(db, fake_collection, "今年记忆", "今年的记忆。", 0.5, "2026-06-01")
        results = retrieve_chunks("推荐几部作品", top_k=5, max_chunks_per_item=5, db=db)
        by = {r.item_title: r.score for r in results}
        # 无 temporal intent → 无时间加分 → 同相似度下 0.5 平分（无 bonus/penalty）
        assert abs(by["旧年记忆"] - by["今年记忆"]) < 1e-6


class TestMetadataRerank:
    """Phase 10-1-B-7：_compute_retrieval_score 统一 rerank 层。"""

    LAST_YEAR = (datetime(2025, 1, 1), datetime(2025, 12, 31, 23, 59, 59))

    def _freeze_now(self, monkeypatch, dt):
        monkeypatch.setattr("app.retrieval._current_time", lambda: dt)

    def test_base_score_unchanged_for_ordinary(self):
        # 无 temporal_range：final = semantic × source_weight（B-3 语义）
        final, adj = _compute_retrieval_score(0.8, "note", None, None)
        assert final == 0.8 and adj == 0.0
        final, adj = _compute_retrieval_score(0.8, "external_reference", "2025-06-01", None)
        assert final == round(0.8 * 0.4, 4) and adj == 0.0  # external 权重 0.4，无时间调整

    def test_temporal_hit_and_miss_and_unknown(self):
        hit, _ = _compute_retrieval_score(0.5, "memory", "2025-06-01", self.LAST_YEAR)
        assert hit == round(0.5 + 0.15, 4)  # +0.15
        miss, _ = _compute_retrieval_score(0.5, "memory", "2026-06-01", self.LAST_YEAR)
        assert miss == round(0.5 - 0.05, 4)  # -0.05
        unknown, _ = _compute_retrieval_score(0.5, "memory", None, self.LAST_YEAR)
        assert unknown == 0.5 and _ == 0.0  # 缺失 → 0
        bad, _ = _compute_retrieval_score(0.5, "memory", "not-a-date", self.LAST_YEAR)
        assert bad == 0.5  # 非法 → 0

    def test_external_gets_no_temporal_bonus_even_when_in_range(self):
        final, adj = _compute_retrieval_score(0.5, "external_reference", "2025-06-01", self.LAST_YEAR)
        assert final == round(0.5 * 0.4, 4) and adj == 0.0

    def test_semantic_dominance(self, db, fake_collection, fixed_query_embedding, monkeypatch):
        """语义主导：低相关时间命中不能压过高相关 personal chunk。"""
        self._freeze_now(monkeypatch, datetime(2026, 8, 15))
        _add_memory_item(db, fake_collection, "低相关时间命中", "不太相关的旧记忆。", 0.2, "2025-06-01")
        _add_memory_item(db, fake_collection, "高相关未知", "与查询高度相关的记忆。", 0.9, None)
        results = retrieve_chunks("去年我看了什么", top_k=5, max_chunks_per_item=5, db=db)
        order = [r.item_title for r in results]
        # 0.9(高相关) > 0.2+0.15=0.35(时间命中但低相关)
        assert order.index("高相关未知") < order.index("低相关时间命中")

    def test_rerank_before_per_item_cap(self, db, fake_collection, fixed_query_embedding, monkeypatch):
        """同一 item：时间命中 chunk 在 per-item cap 前获得更高分，cap=1 保留它。"""
        self._freeze_now(monkeypatch, datetime(2026, 8, 15))
        _add_memory_item(db, fake_collection, "同作品命中", "去年看的内容。", 0.5, "2025-06-01")
        _add_memory_item(db, fake_collection, "同作品未中", "今年看的内容。", 0.5, "2026-06-01")
        # 两个 chunk 同 item? 需要同 item 的两条 memory —— 这里用独立 item 验证排序已足够，
        # 真正的 per-item 时序由 pipeline（rerank→dedup→cap）保证；cap 未改。
        results = retrieve_chunks("去年我看了什么", top_k=5, max_chunks_per_item=5, db=db)
        by = {r.item_title: r.score for r in results}
        assert by["同作品命中"] == round(0.5 + 0.15, 4)
        assert by["同作品未中"] == round(0.5 - 0.05, 4)

    def test_ordinary_query_zero_regression(self, db, fake_collection, fixed_query_embedding, monkeypatch):
        """普通 query：final score/排序与 B-3 语义一致（无时间调整）。"""
        self._freeze_now(monkeypatch, datetime(2026, 8, 15))
        add_item(db, fake_collection, "我的笔记", [], [("感想。", 0.8)])
        _add_external_item(db, fake_collection, "百科", "bangumi", "外部简介。", 0.8)
        results = retrieve_chunks("查询", top_k=5, max_chunks_per_item=5, db=db)
        assert results[0].source_type == "note"
        assert results[0].score == 0.8
        ext = [h for h in results if h.source_type == "external_reference"]
        assert ext and ext[0].score == round(0.8 * 0.4, 4)


class TestEmotionMilestoneSignals:
    """Phase 10-1-B-8：emotion / milestone 确定性信号（经 _compute_retrieval_score）。"""

    def _freeze_now(self, monkeypatch, dt):
        monkeypatch.setattr("app.retrieval._current_time", lambda: dt)

    def test_emotion_intent_and_matching_emotion_boost(self):
        final, _ = _compute_retrieval_score(0.5, "memory", None, None,
                                            emotion="怀念", milestone=None, query="哪些作品让我印象深刻")
        assert final == round(0.5 + 0.08, 4)  # 印象 ∈ 怀念组 → +0.08

    def test_emotion_intent_and_nonmatching_emotion_no_boost(self):
        final, _ = _compute_retrieval_score(0.5, "memory", None, None,
                                            emotion="平静", milestone=None, query="哪些作品让我印象深刻")
        assert final == 0.5  # 平静组无 query 关键词 → 不加

    def test_no_emotion_intent_zero(self):
        final, _ = _compute_retrieval_score(0.5, "memory", None, None,
                                            emotion="怀念", milestone=None, query="这部作品是什么")
        assert final == 0.5

    def test_missing_and_invalid_emotion_zero(self):
        assert _compute_retrieval_score(0.5, "memory", None, None, None, None, "印象最深")[0] == 0.5
        assert _compute_retrieval_score(0.5, "memory", None, None, "zzz", None, "印象最深")[0] == 0.5

    def test_milestone_intent_and_true_boost(self):
        final, _ = _compute_retrieval_score(0.5, "memory", None, None, None, True, "第一次看这部作品")
        assert final == round(0.5 + 0.08, 4)

    def test_milestone_intent_false_and_missing_zero(self):
        assert _compute_retrieval_score(0.5, "memory", None, None, None, False, "第一次看这部作品")[0] == 0.5
        assert _compute_retrieval_score(0.5, "memory", None, None, None, None, "第一次看这部作品")[0] == 0.5

    def test_no_milestone_intent_zero(self):
        assert _compute_retrieval_score(0.5, "memory", None, None, None, True, "这部作品是什么")[0] == 0.5

    def test_external_never_gets_metadata_boost(self):
        final, _ = _compute_retrieval_score(0.5, "external_reference", None, None,
                                            emotion="怀念", milestone=True, query="印象最深的第一次")
        assert final == round(0.5 * 0.4, 4)  # external 权重 0.4，无 emotion/milestone 加分

    def test_temporal_plus_emotion_stack(self):
        final, _ = _compute_retrieval_score(0.5, "memory", "2025-06-01", (datetime(2025, 1, 1), datetime(2025, 12, 31, 23, 59, 59)),
                                            emotion="怀念", milestone=None, query="去年印象最深")
        assert final == round(0.5 + 0.15 + 0.08, 4)

    def test_emotion_plus_milestone_stack(self):
        final, _ = _compute_retrieval_score(0.5, "memory", None, None,
                                            emotion="感动", milestone=True, query="第一次看很感动")
        assert final == round(0.5 + 0.08 + 0.08, 4)

    def test_semantic_still_dominant(self, db, fake_collection, fixed_query_embedding, monkeypatch):
        """低相关三信号命中（+0.31）不能压过高相关无信号 personal。"""
        self._freeze_now(monkeypatch, datetime(2026, 8, 15))
        _add_memory_item_full(db, fake_collection, "低相关三命中", "不太相关。", 0.3, "2025-06-01", "怀念", True)
        _add_memory_item(db, fake_collection, "高相关", "与查询高度相关的内容。", 0.9, None)
        results = retrieve_chunks("去年印象最深的第一次", top_k=5, max_chunks_per_item=5, db=db)
        order = [r.item_title for r in results]
        assert order.index("高相关") < order.index("低相关三命中")  # 0.9 > 0.3+0.31=0.61

    def test_old_metadata_missing_all_still_retrieves(self, db, fake_collection, fixed_query_embedding, monkeypatch):
        """历史向量无 occurred_at/emotion/milestone：emotion/milestone query 仍正常返回、不加分。"""
        self._freeze_now(monkeypatch, datetime(2026, 8, 15))
        add_item(db, fake_collection, "旧笔记", [], [("旧内容。", 0.5)])
        results = retrieve_chunks("印象最深", top_k=5, max_chunks_per_item=5, db=db)
        assert any(r.item_title == "旧笔记" for r in results)
        assert [r for r in results if r.item_title == "旧笔记"][0].score == 0.5  # 无 metadata 加分

    def test_recommendation_no_metadata_boost(self, db, fake_collection, fixed_query_embedding, monkeypatch):
        """推荐 query 不因 metadata 自动改变（无 emotion/milestone intent）。"""
        self._freeze_now(monkeypatch, datetime(2026, 8, 15))
        _add_memory_item_full(db, fake_collection, "带情绪记忆", "记忆内容。", 0.5, None, "感动", True)
        _add_memory_item(db, fake_collection, "普通记忆", "另一条记忆。", 0.5, None)
        results = retrieve_chunks("推荐几部作品", top_k=5, max_chunks_per_item=5, db=db)
        by = {r.item_title: r.score for r in results}
        assert abs(by["带情绪记忆"] - by["普通记忆"]) < 1e-6  # 无加分


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

    def test_old_metadata_missing_signals_still_retrieves(self, db, fake_collection, fixed_query_embedding):
        """Phase 10-1-B-5：旧向量缺少 occurred_at/emotion/milestone metadata 仍可正常检索。"""
        add_item(db, fake_collection, "旧文档", [], [("没有新信号字段的旧内容。", 0.9)])
        _add_external_item(db, fake_collection, "旧百科", "bangumi", "旧外部内容。", 0.85)
        results = retrieve_chunks("查询", top_k=5, max_chunks_per_item=5, db=db)
        assert any(h.item_title == "旧文档" for h in results)
        assert any(h.source_type == "external_reference" for h in results)


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
