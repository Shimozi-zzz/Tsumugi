"""Review 模块测试：CRUD、向量同步清理、RAG 检索来源区分、spoiler、评分对比"""
import pytest

from app import reviews
from app.ingest import ingest_external, ingest_text_document
from app.models import Chunk, Item, Review
from app.retrieval import retrieve_chunks
from app.reviews import REVIEW_STATUSES


def _mk_item(db, fake_collection, patch_embeddings, title="作品", content="原作内容" * 20, source="local", **kw):
    if source == "local":
        return ingest_text_document(title, content, db=db)
    return ingest_external(source=source, external_id=str(kw.get("external_id", "1")),
                           title=title, content=content, raw_metadata=kw.get("raw_metadata"), db=db)


class TestCreate:
    def test_create_review_writes_vectors(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings)
        r = reviews.create_review(item.id, "这是一段很长的读后感内容。" * 30,
                                  title="完结感想", rating=9, status="看完", spoiler=True, db=db)
        assert r.item_id == item.id
        assert r.rating == 9
        assert r.status == "看完"
        assert r.spoiler == 1
        chunks = db.query(Chunk).filter(Chunk.review_id == r.id).all()
        assert len(chunks) >= 1
        # review 的向量已写入（collection 含 item + review，review 相关 = chunks 数）
        review_vecs = [k for k in fake_collection.vectors if k.startswith(f"review{r.id}_")]
        assert len(review_vecs) == len(chunks)

    def test_create_invalid_status(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings)
        with pytest.raises(ValueError):
            reviews.create_review(item.id, "内容", status="不存在的状态", db=db)

    def test_create_invalid_rating(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings)
        with pytest.raises(ValueError):
            reviews.create_review(item.id, "内容", rating=11, db=db)

    def test_create_missing_item(self, db, fake_collection, patch_embeddings):
        with pytest.raises(ValueError):
            reviews.create_review(9999, "内容", db=db)

    def test_embedding_failure_rolls_back_vectors(self, db, fake_collection, monkeypatch):
        from app.embeddings import EmbeddingError
        # 手动造 item，避免依赖 patch
        it = Item(title="x", type="note", content="内容", source="local")
        db.add(it); db.flush()
        def boom(texts):
            raise EmbeddingError("模型挂了")
        monkeypatch.setattr("app.embeddings.embed_texts", boom)
        with pytest.raises(EmbeddingError):
            reviews.create_review(it.id, "很长的内容" * 30, db=db)
        assert db.query(Review).count() == 0
        assert len(fake_collection.vectors) == 0


class TestUpdateDelete:
    def test_update_changes_vectors(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings)
        r = reviews.create_review(item.id, "第一版读后感内容" * 20, db=db)
        item_vecs = len([k for k in fake_collection.vectors if k.startswith("item")])
        old_review_refs = set(c.embedding_ref for c in db.query(Chunk).filter(Chunk.review_id == r.id).all())
        old_docs = {ref: fake_collection.docs.get(ref) for ref in old_review_refs}

        r2 = reviews.update_review(r.id, content="第二版完全不同的读后感内容" * 30, rating=7, db=db)
        new_refs = set(c.embedding_ref for c in db.query(Chunk).filter(Chunk.review_id == r2.id).all())
        assert r2.content != "第一版读后感内容" * 20
        # 向量总数 = item chunks + review 新 chunks（旧向量被替换）
        assert len(fake_collection.vectors) == item_vecs + len(new_refs)
        # id 若复用，则内容文档应已更新（不再是旧内容）
        for ref in old_review_refs & new_refs:
            assert fake_collection.docs.get(ref) != old_docs.get(ref), f"{ref} 内容未更新"
        for ref in new_refs:
            assert ref in fake_collection.vectors

    def test_update_meta_only_no_vector_change(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings)
        r = reviews.create_review(item.id, "内容不变" * 20, db=db)
        refs = [c.embedding_ref for c in r.chunks]
        before = len(fake_collection.vectors)
        reviews.update_review(r.id, title="新标题", rating=5, db=db)  # 内容未变
        assert len(fake_collection.vectors) == before
        for ref in refs:
            assert ref in fake_collection.vectors

    def test_delete_review_cleans_vectors(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings)
        r = reviews.create_review(item.id, "待删除的读后感" * 20, db=db)
        refs = [c.embedding_ref for c in r.chunks]
        assert reviews.delete_review(r.id, db=db) is True
        assert db.get(Review, r.id) is None
        assert db.query(Chunk).filter(Chunk.review_id == r.id).count() == 0
        for ref in refs:
            assert ref not in fake_collection.vectors

    def test_delete_missing(self, db, fake_collection):
        assert reviews.delete_review(9999, db=db) is False

    def test_list_reviews_desc(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings)
        reviews.create_review(item.id, "第一条" * 10, db=db)
        reviews.create_review(item.id, "第二条" * 10, db=db)
        rows = reviews.list_reviews(item.id, db=db)
        assert len(rows) == 2


class TestRagIntegration:
    def test_retrieval_distinguishes_review_source(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings, content="讲的是原作剧情展开" * 20)
        reviews.create_review(item.id, "这是关于结局的深度感想与伏笔解析" * 20,
                              title="结局分析", db=db)
        results = retrieve_chunks("结局感想伏笔", top_k=10, max_chunks_per_item=5, db=db)
        # 至少应命中 review 内容，且 source_type 正确标记
        review_hits = [h for h in results if h.source_type == "review"]
        assert review_hits, "检索应能命中 review 内容"
        assert review_hits[0].review_id is not None
        assert review_hits[0].review_title == "结局分析"
        # item 自身的 chunk source_type 为 note（ADR 0025 来源类型）
        item_hits = [h for h in results if h.source_type == "note"]
        assert item_hits

    def test_retrieval_review_has_correct_item(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings, content="无关内容" * 20)
        reviews.create_review(item.id, "独特的关键词：量子纠缠结局" * 20, db=db)
        results = retrieve_chunks("量子纠缠结局", top_k=5, db=db)
        assert results
        top = results[0]
        assert top.item_id == item.id
        assert top.source_type == "review"


class TestMyRating:
    def test_average_multiple_rated(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings)
        reviews.create_review(item.id, "第一条" * 10, rating=8, db=db)
        reviews.create_review(item.id, "第二条" * 10, rating=9, db=db)
        reviews.create_review(item.id, "第三条" * 10, rating=7, db=db)
        assert reviews.get_my_rating(item.id, db=db) == 8.0

    def test_ignores_unrated_reviews(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings)
        reviews.create_review(item.id, "无评分" * 10, db=db)  # 未打分
        reviews.create_review(item.id, "评分1" * 10, rating=6, db=db)
        reviews.create_review(item.id, "评分2" * 10, rating=10, db=db)
        assert reviews.get_my_rating(item.id, db=db) == 8.0  # (6+10)/2，忽略未打分

    def test_single_review_equals_its_rating(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings)
        reviews.create_review(item.id, "唯一" * 10, rating=5, db=db)
        assert reviews.get_my_rating(item.id, db=db) == 5.0

    def test_all_unrated_returns_none(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings)
        reviews.create_review(item.id, "没打分1" * 10, db=db)
        reviews.create_review(item.id, "没打分2" * 10, db=db)
        assert reviews.get_my_rating(item.id, db=db) is None

    def test_no_reviews_returns_none(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings)
        assert reviews.get_my_rating(item.id, db=db) is None

    def test_own_session_closed(self, db, fake_collection, patch_embeddings):
        # 不传 db 时自建 session（应正常关闭，不报 DetachedInstanceError）
        item = _mk_item(db, fake_collection, patch_embeddings)
        reviews.create_review(item.id, "内容" * 10, rating=7, db=db)
        assert reviews.get_my_rating(item.id) == 7.0


class TestSpoilerRetrieval:
    """ADR 0017：spoilered Review 内容不参与语义检索（方案A）。

    用"item 自身无内容 chunk"的场景保证确定性：检索候选只有 review 的
    向量，过滤效果可精确断言（hash 假 embedding 无语义，避免依赖相似度）。
    """

    def test_spoiler_review_filtered_non_spoiler_kept(self, db, fake_collection, patch_embeddings):
        item_a = _mk_item(db, fake_collection, patch_embeddings, title="A", content="")
        item_b = _mk_item(db, fake_collection, patch_embeddings, title="B", content="")
        sp = reviews.create_review(item_a.id, "剧透关键词：凶手是管家" * 20, spoiler=True, db=db)
        ns = reviews.create_review(item_b.id, "分析关键词：结局伏笔" * 20, spoiler=False, db=db)
        results = retrieve_chunks("随便问点什么", top_k=10, max_chunks_per_item=10, db=db)
        review_hits = [h for h in results if h.source_type == "review"]
        assert [h.review_id for h in review_hits] == [ns.id]
        assert all(h.review_id != sp.id for h in review_hits)

    def test_spoiler_only_review_not_retrieved(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings, title="X", content="")
        reviews.create_review(item.id, "关于凶手身份的深度解析与伏笔" * 20, spoiler=True, db=db)
        results = retrieve_chunks("凶手身份解析", top_k=5, db=db)
        review_hits = [h for h in results if h.source_type == "review"]
        assert review_hits == [], "spoiler 内容被完全过滤，不应出现在检索结果"

    def test_non_spoiler_review_still_retrieved(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings, title="Y", content="")
        ns = reviews.create_review(item.id, "普通读后感不含剧透的讨论" * 20, spoiler=False, db=db)
        results = retrieve_chunks("随便问点什么", top_k=5, db=db)
        assert any(h.source_type == "review" and h.review_id == ns.id for h in results)

    def test_item_content_still_retrieved_when_spoiler_filtered(self, db, fake_collection, patch_embeddings):
        # item 自身内容与 spoiler review 并存：过滤只影响 review chunk
        item = _mk_item(db, fake_collection, patch_embeddings, title="Z", content="原作正文" * 20)
        reviews.create_review(item.id, "剧透内容不该出现" * 20, spoiler=True, db=db)
        results = retrieve_chunks("原作正文", top_k=10, max_chunks_per_item=10, db=db)
        assert any(h.source_type == "note" for h in results)  # item 自身内容仍在
        assert all(h.source_type != "review" for h in results)  # spoiler review 被过滤


class TestPublicRating:
    def test_local_item_no_public_rating(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings, source="local")
        assert reviews.get_public_rating(item) is None

    def test_external_rating_dict(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings,
                        source="bangumi", raw_metadata={"rating": {"score": 8.9}})
        assert reviews.get_public_rating(item) == 8.9

    def test_external_rating_flat(self, db, fake_collection, patch_embeddings):
        item = _mk_item(db, fake_collection, patch_embeddings,
                        source="bangumi", raw_metadata={"rating": 7.5})
        assert reviews.get_public_rating(item) == 7.5

    def test_status_constants(self):
        assert REVIEW_STATUSES == ["想看", "在看", "看完", "搁置", "弃坑"]
