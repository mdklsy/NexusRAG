"""集成测试公共设施：sqlite 库 + 内存 Qdrant + Fake LLM/Embedding。

不依赖任何外部服务（无 PG/Qdrant/Redis/API Key），验证管道逻辑正确性。
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.session as dbs
import app.models  # noqa: F401
from app.db.base import Base

DIM = 8


def _stable_vec(text: str) -> list[float]:
    """确定性伪向量：相同文本 → 相同向量；按首字符聚类制造粗粒度相似。"""
    import hashlib

    h = hashlib.md5(text.encode()).digest()
    seed = h[0] / 255.0
    vec = [seed] + [b / 255.0 for b in h[1:DIM]]
    norm = sum(x * x for x in vec) ** 0.5 or 1.0
    return [x / norm for x in vec]


class FakeEmbeddingClient:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_stable_vec(t) for t in texts]


class FakeLLMClient:
    """意图=qa；三元组固定；流式回答带 [1] 引用。"""

    def __init__(self):
        self.stream_answer = "根据资料，NexusRAG 支持知识图谱增强检索。[1]"

    async def chat(self, messages, temperature=0.3, max_tokens=2048):
        last = messages[-1]["content"] if messages else ""
        if "【参考资料】" in last:
            return "未拆封商品支持七天无理由退款，运费自理。", {
                "tokens_in": 10, "tokens_out": 5,
            }
        return "ok", {"tokens_in": 10, "tokens_out": 5}

    async def chat_json(self, messages, temperature=0.0, max_tokens=4096):
        last = messages[-1]["content"]
        if "意图" in last:
            return '{"intent": "qa"}'
        if "质量评审员" in last:
            return '{"faithfulness": 5, "relevance": 4}'
        if "查询改写助手" in last:
            return '{"query": "改写后的独立查询"}'
        if "压缩为一段简洁的摘要" in last:
            return '{"summary": "用户此前询问了NexusRAG的检索架构与重排配置"}'
        if "知识图谱信息抽取" in last:
            return (
                '{"triples": ['
                '{"source": {"name": "NexusRAG", "type": "产品"}, "predicate": "使用", '
                '"target": {"name": "Qdrant", "type": "技术"}}, '
                '{"source": {"name": "Qdrant", "type": "技术"}, "predicate": "属于", '
                '"target": {"name": "向量数据库", "type": "概念"}}'
                "]}"
            )
        return "{}"

    async def chat_stream(self, messages, temperature=0.3, max_tokens=2048):
        for piece in ["根据资料，", "NexusRAG 支持知识图谱增强检索。[1]"]:
            yield piece, None
        yield "", {"tokens_in": 12, "tokens_out": 8}

    async def chat_with_tools(self, messages, tools, temperature=0.3, max_tokens=2048):
        """默认不调用工具，直接作答；测试中可覆写。"""
        return "默认回答", None, {"tokens_in": 5, "tokens_out": 3}


@pytest_asyncio.fixture
async def sqlite_env(tmp_path, monkeypatch):
    """重定向数据库到 sqlite 文件库，替换 LLM/嵌入为 Fake，Qdrant 用内存模式。"""
    db_file = tmp_path / "test.db"
    url = f"sqlite+aiosqlite:///{db_file}"
    monkeypatch.setattr(dbs.get_settings(), "database_url", url)

    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    dbs._engine = engine
    dbs._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Qdrant 内存模式
    from qdrant_client import AsyncQdrantClient

    from app.services.ingestion import vectorstore as vs_mod

    store = vs_mod.get_vector_store()
    store._client = AsyncQdrantClient(location=":memory:")

    # Fake LLM / Embedding（patch 各使用方模块的绑定）
    fake_llm, fake_embed = FakeLLMClient(), FakeEmbeddingClient()
    monkeypatch.setattr(
        "app.services.ingestion.pipeline.get_embedding_client", lambda: fake_embed
    )
    monkeypatch.setattr("app.services.ingestion.pipeline.get_llm_client", lambda: fake_llm)
    monkeypatch.setattr("app.services.retrieval.get_embedding_client", lambda: fake_embed)
    monkeypatch.setattr("app.services.cache.get_embedding_client", lambda: fake_embed)
    monkeypatch.setattr("app.services.chat.orchestrator.get_llm_client", lambda *_: fake_llm)
    monkeypatch.setattr(
        "app.services.kg.extractor.get_llm_client", lambda *_: fake_llm
    )
    monkeypatch.setattr(
        "app.services.evaluator.get_llm_client", lambda *_: fake_llm
    )

    yield engine

    await engine.dispose()
    dbs._engine = None
    dbs._session_factory = None
    await store.client.close()
    store._client = None


@pytest.fixture
def anyio_backend():
    return "asyncio"
