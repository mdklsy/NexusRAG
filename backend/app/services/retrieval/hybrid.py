"""混合检索：BM25（倒排索引）+ RRF 融合。

设计说明：
- chunk_tokens 每 chunk 每 token 一行（去重），故 tf 恒为 1，
  BM25 退化为「查询词覆盖度 × IDF × 长度归一」——对 500 字级 chunk 效果足够
- df / doc_len 均由候选明细在应用层聚合，避免方言差异
"""

import math
import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kb import ChunkToken
from app.services.ingestion.tokenizer import tokenize

K1 = 1.5
B = 0.75
RRF_K = 60


@dataclass
class BM25Result:
    chunk_id: uuid.UUID
    score: float


def compute_bm25(
    hits: dict[uuid.UUID, set[str]],  # chunk_id -> 命中的 query token 集合
    doc_lens: dict[uuid.UUID, int],  # chunk_id -> token 总数
    df: dict[str, int],  # token -> 包含该词的 chunk 数
    n_docs: int,
    avgdl: float,
    query_tokens: list[str],
) -> list[BM25Result]:
    """tf=1 的 BM25 变体。纯函数便于单测。"""
    scores: list[BM25Result] = []
    seen_q = set(query_tokens)
    for cid, hit_tokens in hits.items():
        dl = max(1, doc_lens.get(cid, 1))
        norm = K1 * (1 - B + B * dl / max(avgdl, 1e-6))
        s = 0.0
        for t in hit_tokens & seen_q:
            tf = 1.0
            idf = math.log(1 + (n_docs - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
            s += idf * tf * (K1 + 1) / (tf + norm)
        if s > 0:
            scores.append(BM25Result(chunk_id=cid, score=s))
    scores.sort(key=lambda r: -r.score)
    return scores


def rrf_fuse(
    rank_lists: list[list[uuid.UUID]], k: int = RRF_K
) -> list[uuid.UUID]:
    """Reciprocal Rank Fusion：score = Σ 1/(k + rank)。"""
    agg: dict[uuid.UUID, float] = defaultdict(float)
    for ranks in rank_lists:
        for i, cid in enumerate(ranks):
            agg[cid] += 1.0 / (k + i + 1)
    return [cid for cid, _ in sorted(agg.items(), key=lambda x: -x[1])]


async def bm25_search(
    session: AsyncSession,
    kb_ids: list[uuid.UUID],
    query: str,
    limit: int = 200,
) -> list[BM25Result]:
    """倒排拉候选 → 应用层 BM25 精排。"""
    q_tokens = list(dict.fromkeys(tokenize(query)))  # 去重保序
    if not q_tokens or not kb_ids:
        return []

    detail_sql = text(
        """
        SELECT chunk_id, token FROM chunk_tokens
        WHERE kb_id IN :kb_ids AND token IN :tokens
        LIMIT :limit
        """
    ).bindparams(
        bindparam("kb_ids", expanding=True),
        bindparam("tokens", expanding=True),
    )
    detail = (
        await session.execute(
            detail_sql,
            {
                "kb_ids": [k.hex for k in kb_ids],
                "tokens": q_tokens,
                "limit": limit * 8,
            },
        )
    ).all()
    if not detail:
        return []

    hits: dict[uuid.UUID, set[str]] = defaultdict(set)
    df: dict[str, int] = defaultdict(int)
    for chunk_id, token in detail:
        cid = uuid.UUID(str(chunk_id))
        if token not in hits[cid]:
            hits[cid].add(token)
            df[token] += 1

    # 候选 chunk 的 token 总数（doc_len）与库规模
    cand_ids = list(hits.keys())
    len_sql = text(
        """
        SELECT chunk_id, COUNT(*) FROM chunk_tokens
        WHERE chunk_id IN :cids GROUP BY chunk_id
        """
    ).bindparams(bindparam("cids", expanding=True))
    doc_lens = {
        uuid.UUID(str(r[0])): int(r[1])
        for r in (
            await session.execute(len_sql, {"cids": [c.hex for c in cand_ids]})
        ).all()
    }
    n_docs = (
        await session.execute(
            select(func.count(func.distinct(ChunkToken.chunk_id))).where(
                ChunkToken.kb_id.in_(kb_ids)
            )
        )
    ).scalar() or len(cand_ids)
    total_rows = sum(doc_lens.values())
    avgdl = total_rows / len(doc_lens) if doc_lens else 1.0

    return compute_bm25(hits, doc_lens, df, n_docs, avgdl, q_tokens)[:limit]
