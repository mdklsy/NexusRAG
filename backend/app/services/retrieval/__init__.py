"""检索融合层：向量召回 + KG 子图增强，统一产出上下文与引用。"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app import AppKnowledgeBase
from app.models.kb import Chunk, Document, KnowledgeBase
from app.services.ingestion.vectorstore import get_vector_store
from app.services.kg.extractor import link_query_entities
from app.services.kg.graph_store import GraphEntity, SubGraph, get_graph_store
from app.services.llm import get_embedding_client


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    content: str
    score: float
    seq: int = 0
    heading: str = ""


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    graph_entities: list[GraphEntity] = field(default_factory=list)
    graph_facts: list[str] = field(default_factory=list)
    subgraph: SubGraph | None = None

    @property
    def hit(self) -> bool:
        return bool(self.chunks)

    def build_context(self, max_chunks: int = 8, max_chars: int = 6000) -> tuple[str, list[dict]]:
        """构建 LLM 上下文块 + 引用列表。返回 (context_text, citations)。"""
        parts: list[str] = []
        citations: list[dict] = []
        used = 0
        for i, c in enumerate(self.chunks[:max_chunks], start=1):
            body = c.content[:1200]
            if used + len(body) > max_chars:
                break
            used += len(body)
            head = f"[{i}] ({c.document_name}"
            if c.heading:
                head += f" · {c.heading}"
            head += ")"
            parts.append(f"{head}\n{body}")
            citations.append(
                {
                    "index": i,
                    "chunk_id": str(c.chunk_id),
                    "document_id": str(c.document_id),
                    "document_name": c.document_name,
                    "heading": c.heading,
                    "score": round(c.score, 4),
                    "snippet": c.content[:200],
                }
            )
        context = "\n\n".join(parts)
        if self.graph_facts:
            facts = "\n".join(f"- {f}" for f in self.graph_facts)
            context += f"\n\n【知识图谱事实】\n{facts}"
        return context, citations


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
    """向量检索 + 可选 KG 子图增强。"""
    config = config or {}
    top_k = int(config.get("top_k", 5))
    threshold = float(config.get("score_threshold", 0.35))
    use_kg = bool(config.get("use_kg", True))
    hops = int(config.get("kg_hops", 1))
    top_entities = int(config.get("kg_top_entities", 3))

    result = RetrievalResult()
    if not kbs:
        return result

    # ---------- 向量召回 ----------
    embedder = get_embedding_client()
    qvec = (await embedder.embed([query]))[0]
    store = get_vector_store()

    hit_ids: list[tuple[uuid.UUID, float]] = []
    for kb in kbs:
        hits = await store.search(kb.id, qvec, top_k=top_k, score_threshold=threshold)
        hit_ids.extend((h.chunk_id, h.score) for h in hits)

    if hit_ids:
        hit_ids.sort(key=lambda x: -x[1])
        hit_ids = hit_ids[: top_k * 2]
        rows = (
            (
                await session.execute(
                    select(Chunk, Document.name)
                    .join(Document, Chunk.document_id == Document.id)
                    .where(Chunk.id.in_([h[0] for h in hit_ids]))
                )
            )
            .all()
        )
        score_map = {cid: score for cid, score in hit_ids}
        for chunk, doc_name in rows:
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
        result.chunks.sort(key=lambda c: -c.score)

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
