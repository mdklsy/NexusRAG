"""Qdrant 向量库封装。每个知识库一个 collection：nexusrag_kb_{kb_id}。"""

import uuid
from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qm

from app.core.config import get_settings


def collection_name(kb_id: uuid.UUID | str) -> str:
    return f"nexusrag_kb_{str(kb_id).replace('-', '')}"


@dataclass
class VectorHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    score: float
    payload: dict


class VectorStore:
    def __init__(self):
        self._client: AsyncQdrantClient | None = None

    @property
    def client(self) -> AsyncQdrantClient:
        if self._client is None:
            s = get_settings()
            self._client = AsyncQdrantClient(
                url=s.qdrant_url, api_key=s.qdrant_api_key or None, timeout=30
            )
        return self._client

    async def ensure_collection(self, kb_id: uuid.UUID, dim: int) -> None:
        name = collection_name(kb_id)
        if not await self.client.collection_exists(name):
            await self.client.create_collection(
                collection_name=name,
                vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
            )

    async def upsert(
        self,
        kb_id: uuid.UUID,
        chunk_ids: list[uuid.UUID],
        vectors: list[list[float]],
        payloads: list[dict],
    ) -> None:
        points = [
            qm.PointStruct(
                id=str(cid),
                vector=vec,
                payload={k: v for k, v in p.items() if v is not None},
            )
            for cid, vec, p in zip(chunk_ids, vectors, payloads, strict=True)
        ]
        await self.client.upsert(collection_name=collection_name(kb_id), points=points)

    async def search(
        self,
        kb_id: uuid.UUID,
        vector: list[float],
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> list[VectorHit]:
        resp = await self.client.query_points(
            collection_name=collection_name(kb_id),
            query=vector,
            limit=top_k,
            score_threshold=score_threshold or None,
            with_payload=True,
        )
        return [
            VectorHit(
                chunk_id=uuid.UUID(str(p.id)),
                document_id=uuid.UUID(p.payload.get("document_id", str(p.id))),
                score=p.score,
                payload=p.payload or {},
            )
            for p in resp.points
        ]

    async def delete_by_document(self, kb_id: uuid.UUID, document_id: uuid.UUID) -> None:
        await self.client.delete(
            collection_name=collection_name(kb_id),
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="document_id", match=qm.MatchValue(value=str(document_id))
                        )
                    ]
                )
            ),
        )

    async def delete_collection(self, kb_id: uuid.UUID) -> None:
        name = collection_name(kb_id)
        if await self.client.collection_exists(name):
            await self.client.delete_collection(name)


_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
