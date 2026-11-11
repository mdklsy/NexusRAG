"""检索融合层：向量召回 + BM25 混合 + KG 子图增强，统一产出上下文与引用。"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app import AppKnowledgeBase
from app.models.kb import Chunk, Document, KnowledgeBase
from app.services.ingestion.vectorstore import get_vector_store
from app.services.kg.extractor import link_query_entities
from app.services.kg.graph_store import get_graph_store
from app.services.llm import get_embedding_client, get_llm_client
from app.services.retrieval.hybrid import bm25_search, rrf_fuse
from app.services.retrieval.models import RetrievalResult, RetrievedChunk
from app.services.retrieval.rerank import rerank_chunks

logger = logging.getLogger(__name__)

__all__ = [
    "RetrievedChunk",
    "RetrievalResult",
    "get_app_knowledge_bases",
    "retrieve",
]


async def get_app_knowledge_bases(session: AsyncSession, app_id: uuid.UUID) -> list[KnowledgeBase]:
    rows = (
        (
            await session.execute(
                select(KnowledgeBase)
                .join(AppKnowledgeBase, AppKnowledgeBase.kb_id == KnowledgeBase.id)
                .where(AppKnowledgeBase.app_id == app_id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def retrieve(
    session: AsyncSession,
    kbs: list[KnowledgeBase],
    query: str,
    config: dict | None = None,
) -> RetrievalResult:
    from app.core import runtime_settings

    await runtime_settings.ensure_fresh()
    """混合检索（向量 + BM25 RRF 融合）→ 重排 → KG 子图增强。"""
    config = config or {}
    top_k = int(config.get("top_k", 5))
    threshold = float(config.get("score_threshold", 0.35))
    use_kg = bool(config.get("use_kg", True))
    hops = int(config.get("kg_hops", 1))
    top_entities = int(config.get("kg_top_entities", 3))
    use_bm25 = bool(config.get("use_bm25", True))
    rerank_mode = str(config.get("rerank", "none") or "none")

    result = RetrievalResult()
    if not kbs:
        return result

    # ---------- 召回：向量 + BM25 → RRF 融合 ----------
    embedder = get_embedding_client()
    qvec = (await embedder.embed([query]))[0]
    store = get_vector_store()

    vector_ranks: list[uuid.UUID] = []
    score_map: dict[uuid.UUID, float] = {}
    for kb in kbs:
        hits = await store.search(kb.id, qvec, top_k=top_k, score_threshold=threshold)
        for h in hits:
            vector_ranks.append(h.chunk_id)
            score_map[h.chunk_id] = h.score

    bm25_ranks: list[uuid.UUID] = []
    if use_bm25:
        try:
            bm25_hits = await bm25_search(session, [kb.id for kb in kbs], query)
            bm25_ranks = [h.chunk_id for h in bm25_hits]
        except Exception as e:  # noqa: BLE001 BM25 失败不影响向量主链路
            logger.warning("bm25 search failed: %s", e)

    if vector_ranks and bm25_ranks:
        fused = rrf_fuse([vector_ranks, bm25_ranks])[: top_k * 3]
    elif bm25_ranks:
        fused = bm25_ranks[: top_k * 3]
    else:
        fused = vector_ranks[: top_k * 3]

    if fused:
        rows = (
            (
                await session.execute(
                    select(Chunk, Document.name)
                    .join(Document, Chunk.document_id == Document.id)
                    .where(Chunk.id.in_(fused))
                )
            )
            .all()
        )
        row_map = {chunk.id: (chunk, doc_name) for chunk, doc_name in rows}
        for cid in fused:
            if cid not in row_map:
                continue
            chunk, doc_name = row_map[cid]
            result.chunks.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    document_name=doc_name,
                    content=chunk.content,
                    score=score_map.get(chunk.id, 0.0),
                    seq=chunk.seq,
                    heading=chunk.meta.get("heading", ""),
                )
            )

        # ---------- 重排 ----------
        if rerank_mode != "none" and len(result.chunks) > 1:
            llm = get_llm_client()
            result.chunks = await rerank_chunks(
                llm, rerank_mode, query, result.chunks,
                rerank_cfg=config.get("rerank_config"),
            )
        result.chunks = result.chunks[:top_k]

    # ---------- KG 增强 ----------
    if use_kg:
        graph = get_graph_store()
        for kb in kbs:
            names = await graph.list_entity_names(kb.id, limit=3000)
            if not names:
                continue
            seeds = link_query_entities(query, names)[:top_entities]
            if not seeds:
                continue
            sub = await graph.subgraph(kb.id, seeds, hops=hops, limit=40)
            if sub.entities:
                result.graph_entities.extend(sub.entities[:20])
                result.graph_facts.extend(sub.to_facts(20))
                result.subgraph = sub

    return result
