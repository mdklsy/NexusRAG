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
    "allowed_document_ids",
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


async def allowed_document_ids(
    session: AsyncSession, kb_ids: list[uuid.UUID], end_user_id: str | None
) -> set[uuid.UUID] | None:
    """按文档 ACL 计算 end_user 可见的文档集合。

    返回 None = 不需要过滤（kb 内没有受限文档，或调用方无终端用户身份——
    控制台/评测/开放 API 直连视为运营侧全量可见）。
    """
    if not kb_ids or not end_user_id:
        return None
    docs = (
        (
            await session.execute(
                select(Document).where(
                    Document.kb_id.in_(kb_ids),
                    Document.status == "completed",
                )
            )
        )
        .scalars()
        .all()
    )
    restricted = [d for d in docs if (d.acl or {}).get("mode") == "restricted"]
    if not restricted:
        return None  # 全部公开，无需过滤
    allowed: set[uuid.UUID] = set()
    for d in docs:
        acl = d.acl or {}
        if acl.get("mode") == "restricted":
            if end_user_id in (acl.get("end_users") or []):
                allowed.add(d.id)
        else:
            allowed.add(d.id)  # 公开（含未配置 acl 的旧文档）
    return allowed


async def retrieve(
    session: AsyncSession,
    kbs: list[KnowledgeBase],
    query: str,
    config: dict | None = None,
    *,
    allowed_document_ids: set[uuid.UUID] | None = None,
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
                    select(Chunk, Document.name, Document.updated_at)
                    .join(Document, Chunk.document_id == Document.id)
                    .where(Chunk.id.in_(fused))
                )
            )
            .all()
        )
        row_map = {chunk.id: (chunk, doc_name, doc_updated) for chunk, doc_name, doc_updated in rows}
        for cid in fused:
            if cid not in row_map:
                continue
            chunk, doc_name, doc_updated = row_map[cid]
            result.chunks.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    document_name=doc_name,
                    content=chunk.content,
                    score=score_map.get(chunk.id, 0.0),
                    seq=chunk.seq,
                    heading=chunk.meta.get("heading", ""),
                    updated_at=doc_updated.strftime("%Y-%m-%d") if doc_updated else "",
                )
            )

        # 文档级 ACL：hydrate 后按可见文档过滤（chunk→document 归属在此才可知）
        if allowed_document_ids is not None:
            result.chunks = [c for c in result.chunks if c.document_id in allowed_document_ids]

        # ---------- 重排 ----------
        if rerank_mode != "none" and len(result.chunks) > 1:
            llm = get_llm_client()
            result.chunks = await rerank_chunks(
                llm, rerank_mode, query, result.chunks,
                rerank_cfg=config.get("rerank_config"),
            )
        result.chunks = result.chunks[:top_k]

    # ---------- KG 增强（ACL 过滤激活时跳过：图谱事实无文档归属，避免绕过权限泄露） ----------
    if use_kg and allowed_document_ids is None:
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
