"""语义缓存：相似问题直接复用回答（Qdrant 集合存储，不引入 Redis）。

按应用隔离（payload.app_id 过滤），键为问题向量、阈值 COSINE 相似度。
写入门控在 orchestrator：仅知识问答、检索命中、无工具调用、非审核模式。
缓存层任何故障都静默放行主链路。
"""

import json
import time
import uuid

from qdrant_client import models as qm

from app.services.ingestion.vectorstore import collection_name, get_vector_store
from app.services.llm import get_embedding_client

CACHE_KB_ID = "cache"  # 合成 id → 集合 nexusrag_kb_cache


def _ensure_uuid(text: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, text)


async def _ensure_collection(dim: int) -> None:
    store = get_vector_store()
    if not await store.client.collection_exists(collection_name(CACHE_KB_ID)):
        await store.ensure_collection(CACHE_KB_ID, dim)


async def lookup(app_id, question: str, threshold: float, ttl_seconds: int) -> dict | None:
    """相似问题命中且未过期 → {answer, citations}；否则 None。"""
    try:
        embedder = get_embedding_client()
        qvec = (await embedder.embed([question]))[0]
        await _ensure_collection(len(qvec))
        hits = await get_vector_store().search(
            CACHE_KB_ID,
            qvec,
            top_k=1,
            score_threshold=threshold,
            payload_filter={"app_id": str(app_id)},
        )
        if not hits:
            return None
        payload = hits[0].payload or {}
        created = payload.get("created_at")
        if created and time.time() - float(created) > ttl_seconds:
            # 过期：只删命中的这条点（同问题重问时会重新写入）
            await get_vector_store().client.delete(
                collection_name=collection_name(CACHE_KB_ID),
                points_selector=qm.PointIdsSelector(points=[hits[0].chunk_id]),
            )
            return None
        return {
            "answer": payload.get("answer", ""),
            "citations": parse_citations(payload.get("citations")),
            "question": payload.get("question", ""),
        }
    except Exception:  # noqa: BLE001
        return None


async def write(app_id, question: str, answer: str, citations: list) -> bool:
    """写入缓存条目；失败静默。"""
    try:
        embedder = get_embedding_client()
        qvec = (await embedder.embed([question]))[0]
        await _ensure_collection(len(qvec))
        point_id = _ensure_uuid(f"{app_id}:{question}")
        await get_vector_store().upsert(
            CACHE_KB_ID,
            [point_id],
            [qvec],
            [
                {
                    "app_id": str(app_id),
                    "question": question[:1000],
                    "answer": answer[:8000],
                    "citations": json.dumps(citations or [], ensure_ascii=False)[:20000],
                    "created_at": time.time(),
                }
            ],
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def parse_citations(raw) -> list:
    """缓存 payload 里 citations 存的是 JSON 字符串；还原为列表。"""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []
    return raw or []
