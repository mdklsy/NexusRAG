"""混合检索（BM25 + RRF）与重排测试。"""

import uuid

import pytest

from app.services.ingestion.tokenizer import tokenize
from app.services.retrieval.hybrid import compute_bm25, rrf_fuse
from app.services.retrieval.rerank import parse_scores

pytestmark = pytest.mark.asyncio


def test_tokenize_filters():
    tokens = tokenize("NexusRAG 是一个开源的检索增强平台")
    assert "开源" in tokens or "nexusrag" in tokens
    assert "是" not in tokens and "的" not in tokens and "一个" not in tokens
    assert all(len(t) > 1 for t in tokens)


def test_rrf_fuse_prefers_multi_list_hits():
    a = [uuid.uuid4() for _ in range(3)]
    b = [a[1], a[0], uuid.uuid4()]  # a[1]、a[0] 双路命中
    fused = rrf_fuse([a, b])
    # 双路命中的 a[0]/a[1] 得分对称相等，稳居前二；单路的殿后
    assert set(fused[:2]) == {a[0], a[1]}
    assert fused[2] == a[2]


def test_rrf_fuse_empty():
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []


def test_compute_bm25_rare_word_scores_higher():
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    hits = {c1: {"退款"}, c2: {"平台"}}
    doc_lens = {c1: 50, c2: 50}
    # "退款" 稀有(df=1)，"平台" 常见(df=2)
    df = {"退款": 1, "平台": 2}
    scored = compute_bm25(hits, doc_lens, df, 3, 50.0, ["退款", "平台"])
    scores = {r.chunk_id: r.score for r in scored}
    assert scores[c1] > scores[c2]


def test_compute_bm25_long_doc_penalty():
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    hits = {c1: {"退款"}, c2: {"退款"}}
    df = {"退款": 1}
    scores = {r.chunk_id: r.score for r in compute_bm25(
        hits, {c1: 20, c2: 500}, df, 2, 100.0, ["退款"]
    )}
    assert scores[c1] > scores[c2]  # 短文档同命中得分更高


def test_parse_scores_variants():
    assert parse_scores('{"scores": [9, 3, 5]}', 3) == [9.0, 3.0, 5.0]
    assert parse_scores('```json\n{"scores": [1, 2]}\n```', 3) == [1.0, 2.0, 0.0]
    assert parse_scores("前置噪声 [8, 7] 后置", 2) == [8.0, 7.0]
    assert parse_scores("完全不是JSON", 2) is None


async def test_hybrid_retrieval_e2e(sqlite_env):
    """摄取后 BM25 命中关键词 chunk；RRF 融合不丢结果。"""
    import pathlib

    from app.core.config import get_settings
    from app.db.session import session_scope
    from app.models.kb import Document, KnowledgeBase
    from app.services.ingestion.pipeline import ingest_document
    from app.services.retrieval import retrieve

    async with session_scope() as session:
        kb = KnowledgeBase(name="bm25", embedding_model="m", embedding_dim=8,
                           chunk_config={"size": 100, "overlap": 20})
        session.add(kb)
        await session.flush()
        doc = Document(kb_id=kb.id, name="policy.md", source_type="upload", file_path="bm25.md")
        session.add(doc)
        await session.commit()
        kb_id, doc_id = kb.id, doc.id
    p = pathlib.Path(get_settings().upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    (p / "bm25.md").write_text(
        "# 退款政策\n\n未拆封商品支持七天无理由退款，运费自理。\n\n"
        "# 配送说明\n\n全国包邮，顺丰发出，预计三到五天送达。",
        encoding="utf-8",
    )
    async with session_scope() as session:
        await session.execute(
            Document.__table__.update().where(Document.__table__.c.id == doc_id)
            .values(file_path="bm25.md")
        )
        await session.commit()
    await ingest_document(doc_id)

    async with session_scope() as session:
        kb = await session.get(KnowledgeBase, kb_id)
        # 语义近似无效的 hash 向量下，BM25 仍应命中"退款"chunk
        result = await retrieve(
            session, [kb], "退款政策是什么",
            {"top_k": 3, "score_threshold": 0, "use_kg": False, "use_bm25": True},
        )
    assert result.hit
    assert any("七天无理由" in c.content for c in result.chunks)

    # 关闭 BM25 时纯向量路径也正常（不抛错）
    async with session_scope() as session:
        kb = await session.get(KnowledgeBase, kb_id)
        r2 = await retrieve(
            session, [kb], "退款政策是什么",
            {"top_k": 3, "score_threshold": 0, "use_kg": False, "use_bm25": False},
        )
    assert isinstance(r2.chunks, list)


async def test_llm_rerank_reorders(sqlite_env):
    """LLM 重排按打分重排；解析失败时原样返回。"""
    from app.services.retrieval import RetrievedChunk
    from app.services.retrieval.rerank import llm_rerank

    class RerankLLM:
        async def chat_json(self, messages, temperature=0.0, max_tokens=4096):
            return '{"scores": [2, 9, 5]}'

    class BadLLM:
        async def chat_json(self, messages, temperature=0.0, max_tokens=4096):
            return "not json at all ]"

    chunks = [
        RetrievedChunk(uuid.uuid4(), uuid.uuid4(), "a.md", "内容甲", 0.9),
        RetrievedChunk(uuid.uuid4(), uuid.uuid4(), "b.md", "内容乙", 0.5),
        RetrievedChunk(uuid.uuid4(), uuid.uuid4(), "c.md", "内容丙", 0.7),
    ]
    out = await llm_rerank(RerankLLM(), "问题", chunks)
    assert [c.document_name for c in out] == ["b.md", "c.md", "a.md"]

    out2 = await llm_rerank(BadLLM(), "问题", chunks)
    assert out2 is chunks  # 失败原样返回


async def test_api_rerank_reorders(sqlite_env, monkeypatch):
    """托管 Rerank API：按 relevance_score 降序映射回候选。"""
    import httpx

    from app.core.config import get_settings
    from app.services.retrieval import RetrievedChunk
    from app.services.retrieval.rerank import api_rerank

    cfg = get_settings()
    monkeypatch.setattr(cfg, "rerank_api_base", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(cfg, "rerank_api_key", "sk-test")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            # 故意乱序返回，验证按分数降序重排
            return {"results": [
                {"index": 2, "relevance_score": 0.5},
                {"index": 0, "relevance_score": 0.1},
                {"index": 1, "relevance_score": 0.9},
            ]}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    chunks = [
        RetrievedChunk(uuid.uuid4(), uuid.uuid4(), "a.md", "内容甲", 0.9),
        RetrievedChunk(uuid.uuid4(), uuid.uuid4(), "b.md", "内容乙", 0.5),
        RetrievedChunk(uuid.uuid4(), uuid.uuid4(), "c.md", "内容丙", 0.7),
    ]
    out = await api_rerank("问题", chunks)
    assert [c.document_name for c in out] == ["b.md", "c.md", "a.md"]


async def test_api_rerank_not_configured_and_failure(sqlite_env, monkeypatch):
    """未配置 / 请求失败时原样返回（不阻塞检索主链路）。"""
    import httpx

    from app.core.config import get_settings
    from app.services.retrieval import RetrievedChunk
    from app.services.retrieval.rerank import api_rerank

    cfg = get_settings()
    chunks = [
        RetrievedChunk(uuid.uuid4(), uuid.uuid4(), "a.md", "内容甲", 0.9),
        RetrievedChunk(uuid.uuid4(), uuid.uuid4(), "b.md", "内容乙", 0.5),
    ]

    monkeypatch.setattr(cfg, "rerank_api_base", "")
    assert await api_rerank("问题", chunks) is chunks

    monkeypatch.setattr(cfg, "rerank_api_base", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(cfg, "rerank_api_key", "sk-test")

    class BoomClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(httpx, "AsyncClient", BoomClient)
    assert await api_rerank("问题", chunks) is chunks
