"""端到端集成测试：上传 → 摄取(分块/嵌入/KG) → 检索融合 → SSE 对话 → 落库计量。"""


from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import session_scope
from app.models.app import App, AppKnowledgeBase, Conversation, Message, UsageEvent
from app.models.kb import Chunk, Document, Entity, KnowledgeBase, Relation
from app.services.chat.orchestrator import run_chat
from app.services.ingestion.pipeline import ingest_document
from app.services.retrieval import retrieve

DOC_TEXT = """# NexusRAG 产品说明

NexusRAG 是一个开源的 RAG 与知识图谱平台。它使用 Qdrant 作为向量数据库。

## 核心特性

支持文档解析、分块、向量化检索与知识图谱增强。用户可以快速搭建智能客服系统。

## 部署

通过 docker compose 一键部署，包含 PostgreSQL、Qdrant、Redis 等组件。
"""


async def _setup_kb_with_doc():
    """建 KB + 文档并完整摄取。返回 (kb, doc)。"""
    async with session_scope() as session:
        kb = KnowledgeBase(
            name="测试库",
            embedding_model=get_settings().embedding_model,
            embedding_dim=8,
            chunk_config={"size": 100, "overlap": 20},
        )
        session.add(kb)
        await session.flush()
        doc = Document(kb_id=kb.id, name="product.md", source_type="upload", file_path=None)
        session.add(doc)
        await session.commit()
        kb_id, doc_id = kb.id, doc.id

    # 直接注入解析文本：通过 file_path 指向临时文件
    import pathlib

    p = pathlib.Path(get_settings().upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    stored = p / f"{doc_id.hex}.md"
    stored.write_text(DOC_TEXT, encoding="utf-8")
    from app.models.kb import Document as DocModel

    async with session_scope() as session:
        await session.execute(
            DocModel.__table__.update()
            .where(DocModel.__table__.c.id == doc_id)
            .values(file_path=stored.name)
        )
        await session.commit()

    await ingest_document(doc_id)
    async with session_scope() as session:
        doc = await session.get(Document, doc_id)
        kb = await session.get(KnowledgeBase, kb_id)
        return kb, doc


async def test_full_ingestion(sqlite_env):
    kb, doc = await _setup_kb_with_doc()
    assert doc.status == "completed", doc.error
    assert doc.chunk_count >= 3
    assert kb.doc_count == 1

    async with session_scope() as session:
        chunk_count = await session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == doc.id)
        )
        assert chunk_count == doc.chunk_count

        # KG：FakeLLM 抽出了 NexusRAG/Qdrant/向量数据库 三个实体两条关系
        entity_count = await session.scalar(
            select(func.count()).select_from(Entity).where(Entity.kb_id == kb.id)
        )
        rel_count = await session.scalar(
            select(func.count()).select_from(Relation).where(Relation.kb_id == kb.id)
        )
        assert entity_count == 3
        assert rel_count == 2


async def test_failed_document_marks_status(sqlite_env, monkeypatch):
    """解析失败 → failed 状态与错误信息。"""
    async with session_scope() as session:
        kb = KnowledgeBase(name="bad", embedding_model="m", embedding_dim=8)
        session.add(kb)
        await session.flush()
        doc = Document(kb_id=kb.id, name="broken.bin", source_type="upload", file_path="nope.bin")
        session.add(doc)
        await session.commit()
        doc_id = doc.id

    await ingest_document(doc_id)
    async with session_scope() as session:
        doc = await session.get(Document, doc_id)
        assert doc.status == "failed"
        assert doc.error


async def test_retrieval_with_kg_fusion(sqlite_env):
    kb, _ = await _setup_kb_with_doc()

    async with session_scope() as session:
        result = await retrieve(
            session,
            [kb],
            "NexusRAG 用什么向量数据库？",
            {"top_k": 3, "score_threshold": 0, "use_kg": True},
        )
    assert result.hit
    assert len(result.chunks) >= 1
    assert any("Qdrant" in c.content for c in result.chunks)
    # KG 增强：实体链接命中 NexusRAG → 子图召回两条事实
    assert len(result.graph_facts) == 2
    assert any("Qdrant" in f for f in result.graph_facts)

    context, citations = result.build_context()
    assert "[1]" in context
    assert citations and citations[0]["document_name"] == "product.md"
    assert "知识图谱事实" in context


async def test_subgraph_multi_hop(sqlite_env):
    """NexusRAG →(使用)→ Qdrant →(属于)→ 向量数据库：2 跳子图应含全部三个实体。"""
    kb, _ = await _setup_kb_with_doc()
    from app.services.kg.graph_store import get_graph_store

    graph = get_graph_store()
    sub = await graph.subgraph(kb.id, ["NexusRAG"], hops=2)
    names = {e.name for e in sub.entities}
    assert {"NexusRAG", "Qdrant", "向量数据库"} <= names
    assert len(sub.edges) == 2

    stats = await graph.kb_stats(kb.id)
    assert stats["entity_count"] == 3
    assert stats["relation_count"] == 2


async def test_chat_stream_events_and_metrics(sqlite_env):
    kb, _ = await _setup_kb_with_doc()
    async with session_scope() as session:
        app = App(name="客服", system_prompt="你是测试客服", retrieval_config={
            "top_k": 3, "score_threshold": 0, "use_kg": True, "intent_route": True
        })
        session.add(app)
        await session.flush()
        session.add(AppKnowledgeBase(app_id=app.id, kb_id=kb.id))
        conv = Conversation(app_id=app.id)
        session.add(conv)
        await session.commit()
        app_id, conv_id = app.id, conv.id

    events = []
    async with session_scope() as session:
        app = await session.get(App, app_id)
        async for ev in run_chat(session, app, conv_id, "NexusRAG 用什么向量数据库？", []):
            events.append(ev)

    types = [e["type"] for e in events]
    assert types[0] == "intent"
    assert "retrieval" in types and "delta" in types
    assert "citations" in types and "done" in types

    delta = "".join(e["content"] for e in events if e["type"] == "delta")
    assert "[1]" in delta
    citations = next(e for e in events if e["type"] == "citations")["citations"]
    assert citations[0]["document_name"] == "product.md"

    # 落库验证：user + assistant 消息、用量事件
    async with session_scope() as session:
        msgs = (
            (
                await session.execute(
                    select(Message)
                    .where(Message.conversation_id == conv_id)
                    .order_by(Message.created_at)
                )
            )
            .scalars()
            .all()
        )
        assert [m.role for m in msgs] == ["user", "assistant"]
        assert msgs[1].citations and msgs[1].tokens_in == 12
        events_rows = (
            (
                await session.execute(
                    select(UsageEvent).where(UsageEvent.app_id == app_id, UsageEvent.type == "chat")
                )
            )
            .scalars()
            .all()
        )
        assert len(events_rows) == 1
        assert events_rows[0].hit is True
        conv_row = await session.get(Conversation, conv_id)
        assert conv_row.title.startswith("NexusRAG")
