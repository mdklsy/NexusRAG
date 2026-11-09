"""摄取管线：解析 → 分块 → 嵌入入库 → KG 三元组抽取。

核心函数 ingest_document 是纯编排逻辑，由 ARQ 任务（或直接 await）调用。
"""

import uuid
from pathlib import Path

from sqlalchemy import delete, func, select, update

from app.core.config import get_settings
from app.db.session import session_scope
from app.models.kb import Chunk, Document, KnowledgeBase, Relation
from app.services.ingestion.chunkers import chunk_text, estimate_tokens
from app.services.ingestion.parsers import ParseError, fetch_url, parse_bytes
from app.services.ingestion.vectorstore import get_vector_store
from app.services.kg.extractor import extract_triples
from app.services.kg.graph_store import get_graph_store
from app.services.llm import get_embedding_client, get_llm_client

EMBED_BATCH_SIZE = 32


async def _set_document_status(document_id: uuid.UUID, status: str, error: str | None = None):
    async with session_scope() as session:
        await session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(status=status, error=error)
        )
        await session.commit()


async def _read_source_text(document: Document) -> str:
    if document.source_type == "url":
        _title, text = await fetch_url(document.source_url)
        return text
    path = Path(get_settings().upload_dir) / str(document.file_path)
    data = path.read_bytes()
    return parse_bytes(data, document.name, document.mime_type)


async def ingest_document(document_id: uuid.UUID) -> None:
    """文档摄取全流程。任何阶段失败都会把文档置为 failed。"""
    async with session_scope() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return
        kb = await session.get(KnowledgeBase, doc.kb_id)
        kb_chunk_config = kb.chunk_config if kb else {}
    if kb is None:
        await _set_document_status(document_id, "failed", "knowledge base not found")
        return

    try:
        # ---------- 1. 解析 ----------
        await _set_document_status(document_id, "parsing")
        text = await _read_source_text(doc)

        # ---------- 2. 分块 ----------
        await _set_document_status(document_id, "chunking")
        size = int(kb_chunk_config.get("size", 500))
        overlap = int(kb_chunk_config.get("overlap", 50))
        results = chunk_text(text, size=size, overlap=overlap, meta={"doc": doc.name})

        # ---------- 3. 嵌入 + 双写 ----------
        await _set_document_status(document_id, "embedding")
        embedder = get_embedding_client()
        store = get_vector_store()
        await store.ensure_collection(kb.id, kb.embedding_dim)

        saved_chunks: list[Chunk] = []
        for i in range(0, len(results), EMBED_BATCH_SIZE):
            batch = results[i : i + EMBED_BATCH_SIZE]
            vectors = await embedder.embed([r.content for r in batch])
            chunk_ids = [uuid.uuid4() for _ in batch]
            payloads = [
                {
                    "kb_id": str(kb.id),
                    "document_id": str(doc.id),
                    "document_name": doc.name,
                    "seq": r.seq,
                    "heading": r.meta.get("heading"),
                }
                for r in batch
            ]
            async with session_scope() as session:
                for cid, r, _vec in zip(chunk_ids, batch, vectors, strict=True):
                    session.add(
                        Chunk(
                            id=cid,
                            kb_id=kb.id,
                            document_id=doc.id,
                            seq=r.seq,
                            content=r.content,
                            token_count=estimate_tokens(r.content),
                            meta=r.meta,
                        )
                    )
                await session.commit()
            await store.upsert(kb.id, chunk_ids, vectors, payloads)
            saved_chunks.extend(batch)  # 仅计数用

        # ---------- 4. KG 抽取 ----------
        await _set_document_status(document_id, "extracting_kg")
        llm = get_llm_client()
        graph = get_graph_store()
        # 重新查出已入库的 chunk（按顺序），保证 evidence_chunk_id 正确
        async with session_scope() as session:
            chunk_rows = (
                (
                    await session.execute(
                        select(Chunk.id, Chunk.content)
                        .where(Chunk.document_id == document_id)
                        .order_by(Chunk.seq)
                    )
                )
                .all()
            )
        for chunk_id, content in chunk_rows:
            triples = await extract_triples(llm, content)
            if triples:
                await graph.save_triples(kb.id, triples, evidence_chunk_id=chunk_id)

        # ---------- 5. 完成 ----------
        async with session_scope() as session:
            chunk_count = await session.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.document_id == document_id)
            )
            await session.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(status="completed", error=None, chunk_count=chunk_count or 0)
            )
            await session.execute(
                update(KnowledgeBase)
                .where(KnowledgeBase.id == kb.id)
                .values(
                    chunk_count=KnowledgeBase.chunk_count + (chunk_count or 0),
                    doc_count=KnowledgeBase.doc_count + 1,
                )
            )
            await session.commit()
    except ParseError as e:
        await _set_document_status(document_id, "failed", str(e))
    except Exception as e:  # noqa: BLE001
        await _set_document_status(document_id, "failed", f"{type(e).__name__}: {e}")


async def purge_document(document_id: uuid.UUID) -> None:
    """删除文档的全部痕迹：向量、分块、KG 证据、计数。"""
    async with session_scope() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return
        chunk_count = await session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
        )
        kb = await session.get(KnowledgeBase, doc.kb_id)

        # KG：先清 evidence 指针（chunk_entities 由 FK 级联删除）
        # 注意：实体不删除——可能被其他文档共享（mention_count 计数 MVP 不回收）
        await session.execute(
            update(Relation)
            .where(Relation.evidence_chunk_id.in_(
                select(Chunk.id).where(Chunk.document_id == document_id)
            ))
            .values(evidence_chunk_id=None)
        )
        await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        if kb:
            await session.execute(
                update(KnowledgeBase)
                .where(KnowledgeBase.id == kb.id)
                .values(
                    chunk_count=func.greatest(KnowledgeBase.chunk_count - (chunk_count or 0), 0),
                    doc_count=func.greatest(KnowledgeBase.doc_count - 1, 0),
                )
            )
        await session.delete(doc)
        await session.commit()

    if kb:
        store = get_vector_store()
        await store.delete_by_document(kb.id, document_id)
