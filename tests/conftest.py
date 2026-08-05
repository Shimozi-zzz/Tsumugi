"""pytest fixture 配置"""
import hashlib

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Item, Chunk, Tag

TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # 所有线程共享同一连接，保证 TestClient 与测试线程看到同一内存库
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def db():
    """每个测试函数一个全新内存数据库。"""
    Base.metadata.create_all(bind=test_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function", autouse=True)
def _patch_session_local(monkeypatch):
    """把数据库会话工厂替换为测试工厂。

    检索/入库会在内部自建 session（run_in_threadpool / 独立事务场景），
    必须指向测试内存库，否则会误操作真实 ./tsumugi.db。
    注意：
    - ingest/retrieval 在**模块顶层** `from app.database import SessionLocal`，
      已经绑定到各自的命名空间，仅 patch app.database.SessionLocal 不生效，
      必须同时 patch app.ingest / app.retrieval 的属性；
    - routes._ingest_sync 是**函数体内** `from app.database import SessionLocal`，
      每次执行时读取模块属性，patch app.database 对该路径生效。
    """
    import app.database
    import app.ingest
    import app.retrieval

    monkeypatch.setattr(app.database, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(app.ingest, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(app.retrieval, "SessionLocal", TestingSessionLocal)


@pytest.fixture(scope="function")
def sample_item(db):
    item = Item(title="测试文档", type="note", content="这是一个测试文档的内容。", source="local")
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture(scope="function")
def sample_tag(db):
    tag = Tag(name="测试标签")
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@pytest.fixture(scope="function")
def sample_chunks(db, sample_item):
    chunks = [
        Chunk(item_id=sample_item.id, content="这是第一个chunk的内容。", chunk_index=0, embedding_ref="emb_001"),
        Chunk(item_id=sample_item.id, content="这是第二个chunk的内容。", chunk_index=1, embedding_ref="emb_002"),
    ]
    for chunk in chunks:
        db.add(chunk)
    db.commit()
    return chunks


# ------------------------------------------------------------------ 假向量库

def _meta_matches(meta: dict, where: dict) -> bool:
    """支持 {"$or": [...]} 与 {"field": value} / {"field": {"$in": [...]}}。"""
    if not where:
        return True
    if "$or" in where:
        return any(_meta_matches(meta, sub) for sub in where["$or"])
    for field, cond in where.items():
        val = meta.get(field)
        if isinstance(cond, dict) and "$in" in cond:
            if val not in cond["$in"]:
                return False
        elif val != cond:
            return False
    return True


class FakeCollection:
    """最小可用的 Chroma collection 假实现：内存 dict + numpy 余弦相似度。"""

    def __init__(self):
        self.vectors = {}
        self.docs = {}
        self.metas = {}

    def add(self, ids, embeddings, documents=None, metadatas=None):
        for i, id_ in enumerate(ids):
            self.vectors[id_] = embeddings[i]
            if documents:
                self.docs[id_] = documents[i]
            if metadatas:
                self.metas[id_] = metadatas[i]

    def delete(self, ids):
        for id_ in ids:
            self.vectors.pop(id_, None)
            self.docs.pop(id_, None)
            self.metas.pop(id_, None)

    def query(self, query_embeddings, n_results, where=None, include=None):
        qv = np.asarray(query_embeddings[0], dtype=float)
        qv = qv / (np.linalg.norm(qv) + 1e-12)
        scored = []
        for id_, vec in self.vectors.items():
            if where and not _meta_matches(self.metas[id_], where):
                continue
            v = np.asarray(vec, dtype=float)
            sim = float(np.dot(qv, v) / (np.linalg.norm(v) + 1e-12))
            scored.append((sim, id_))
        scored.sort(key=lambda x: -x[0])
        scored = scored[:n_results]
        return {
            "ids": [[s[1] for s in scored]],
            "documents": [[self.docs.get(s[1], "") for s in scored]],
            "metadatas": [[self.metas.get(s[1], {}) for s in scored]],
            "distances": [[round(1.0 - s[0], 6) for s in scored]],
        }


@pytest.fixture(scope="function")
def fake_collection(monkeypatch):
    col = FakeCollection()
    monkeypatch.setattr("app.vectorstore.get_collection", lambda: col)
    return col


# ------------------------------------------------------------------ 假 embedding

def _hash_embed(text: str) -> list:
    h = hashlib.md5(text.encode("utf-8")).digest()
    v = np.frombuffer(h, dtype=np.uint8)[:8].astype(np.float64)
    return (v / (np.linalg.norm(v) + 1e-12)).tolist()


@pytest.fixture(scope="function")
def patch_embeddings(monkeypatch):
    """把 embedding 换成确定性 hash 向量，同文本恒同向量。"""
    monkeypatch.setattr("app.embeddings.embed_texts", lambda texts: [_hash_embed(t) for t in texts])
    monkeypatch.setattr("app.embeddings.embed_query", lambda text: _hash_embed(text))
    return _hash_embed
