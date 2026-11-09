"""图存储抽象 + PostgreSQL 实现（邻接表 + 递归 CTE）。

二期可加 Neo4jGraphStore，接口不变。
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import get_session
from app.models.kb import ChunkEntity, Entity, Relation
from app.services.kg.extractor import Triple


def normalize_name(name: str) -> str:
    return "".join(name.lower().split())


@dataclass
class GraphEntity:
    id: uuid.UUID
    name: str
    type: str
    description: str
    mention_count: int


@dataclass
class GraphEdge:
    id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    target_id: uuid.UUID
    target_name: str
    predicate: str
    weight: int


@dataclass
class SubGraph:
    entities: list[GraphEntity] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def to_facts(self, max_facts: int = 30) -> list[str]:
        """序列化为事实文本列表，用于拼入 LLM 上下文。"""
        facts = [f"{e.source_name} --{e.predicate}--> {e.target_name}" for e in self.edges]
        return facts[:max_facts]


class GraphStore(ABC):
    @abstractmethod
    async def save_triples(
        self, kb_id: uuid.UUID, triples: list[Triple], evidence_chunk_id: uuid.UUID | None
    ) -> tuple[int, int]:
        """保存三元组（实体归一合并），返回 (新增实体数, 新增关系数)。"""

    @abstractmethod
    async def subgraph(
        self, kb_id: uuid.UUID, seed_entity_names: list[str], hops: int = 1, limit: int = 50
    ) -> SubGraph:
        """从种子实体出发取 N 跳子图。"""

    @abstractmethod
    async def list_entity_names(self, kb_id: uuid.UUID, limit: int = 2000) -> list[tuple[str, int]]:
        """返回 [(实体名, mention_count)]，用于检索时实体链接。"""

    @abstractmethod
    async def delete_by_kb(self, kb_id: uuid.UUID) -> None: ...


class PGGraphStore(GraphStore):
    def __init__(self, session_factory=None):
        # session_factory 注入便于测试；默认用全局
        self._session_factory = session_factory

    def _sessions(self):
        if self._session_factory is not None:
            return self._session_factory()
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _ctx():
            async for s in get_session():
                yield s

        return _ctx()

    async def _get_or_create_entity(self, session, kb_id, name, etype) -> tuple[uuid.UUID, bool]:
        norm = normalize_name(name)
        stmt = (
            pg_insert(Entity)
            .values(kb_id=kb_id, name=name, type=etype, norm_name=norm)
            .on_conflict_do_nothing(constraint="uq_entities_kb_norm_type")
            .returning(Entity.id)
        )
        result = await session.execute(stmt)
        row = result.first()
        if row:
            return row[0], True
        existing = await session.execute(
            select(Entity.id).where(
                Entity.kb_id == kb_id, Entity.norm_name == norm, Entity.type == etype
            )
        )
        eid = existing.scalar_one()
        await session.execute(
            update(Entity).where(Entity.id == eid).values(mention_count=Entity.mention_count + 1)
        )
        return eid, False

    async def save_triples(
        self, kb_id: uuid.UUID, triples: list[Triple], evidence_chunk_id: uuid.UUID | None
    ) -> tuple[int, int]:
        new_entities, new_relations = 0, 0
        async with self._sessions() as session:
            for t in triples:
                src_id, created = await self._get_or_create_entity(
                    session, kb_id, t.source_name, t.source_type
                )
                new_entities += int(created)
                tgt_id, created = await self._get_or_create_entity(
                    session, kb_id, t.target_name, t.target_type
                )
                new_entities += int(created)

                rel_stmt = (
                    pg_insert(Relation)
                    .values(
                        kb_id=kb_id,
                        source_entity_id=src_id,
                        target_entity_id=tgt_id,
                        predicate=t.predicate,
                        evidence_chunk_id=evidence_chunk_id,
                    )
                    .on_conflict_do_update(
                        constraint="uq_relations_triple",
                        set_={"weight": Relation.weight + 1},
                    )
                    .returning(Relation.id)
                )
                result = await session.execute(rel_stmt)
                if result.first():
                    new_relations += 1

                if evidence_chunk_id:
                    await session.execute(
                        pg_insert(ChunkEntity)
                        .values(chunk_id=evidence_chunk_id, entity_id=src_id)
                        .on_conflict_do_nothing(constraint="uq_chunk_entities")
                    )
                    await session.execute(
                        pg_insert(ChunkEntity)
                        .values(chunk_id=evidence_chunk_id, entity_id=tgt_id)
                        .on_conflict_do_nothing(constraint="uq_chunk_entities")
                    )
            await session.commit()
        return new_entities, new_relations

    async def subgraph(
        self, kb_id: uuid.UUID, seed_entity_names: list[str], hops: int = 1, limit: int = 50
    ) -> SubGraph:
        if not seed_entity_names:
            return SubGraph()
        hops = max(1, min(hops, 3))
        async with self._sessions() as session:
            sql = text(
                """
                WITH RECURSIVE seed AS (
                    SELECT id FROM entities
                    WHERE kb_id = :kb_id
                      AND norm_name = ANY(CAST(:names AS text[]))
                    LIMIT 20
                ),
                walk AS (
                    SELECT e.id, 0 AS depth FROM entities e WHERE e.id IN (SELECT id FROM seed)
                    UNION
                    SELECT r.target_entity_id, w.depth + 1
                    FROM walk w
                    JOIN relations r ON r.source_entity_id = w.id
                    WHERE w.depth < :hops AND r.kb_id = :kb_id
                    UNION
                    SELECT r.source_entity_id, w.depth + 1
                    FROM walk w
                    JOIN relations r ON r.target_entity_id = w.id
                    WHERE w.depth < :hops AND r.kb_id = :kb_id
                )
                SELECT DISTINCT id FROM walk LIMIT :limit
                """
            )
            norm_names = [normalize_name(n) for n in seed_entity_names]
            result = await session.execute(
                sql,
                {
                    "kb_id": str(kb_id),
                    "names": norm_names,
                    "hops": hops,
                    "limit": limit,
                },
            )
            ids = [row[0] for row in result]
            if not ids:
                return SubGraph()

            entities = (
                (
                    await session.execute(
                        select(Entity).where(Entity.id.in_(ids)).order_by(Entity.mention_count.desc())
                    )
                )
                .scalars()
                .all()
            )
            edges = (
                (
                    await session.execute(
                        select(Relation)
                        .where(
                            Relation.kb_id == kb_id,
                            Relation.source_entity_id.in_(ids),
                            Relation.target_entity_id.in_(ids),
                        )
                        .order_by(Relation.weight.desc())
                        .limit(limit * 2)
                    )
                )
                .scalars()
                .all()
            )
            name_map = {e.id: e.name for e in entities}
            return SubGraph(
                entities=[
                    GraphEntity(e.id, e.name, e.type, e.description, e.mention_count)
                    for e in entities
                ],
                edges=[
                    GraphEdge(
                        r.id,
                        r.source_entity_id,
                        name_map.get(r.source_entity_id, "?"),
                        r.target_entity_id,
                        name_map.get(r.target_entity_id, "?"),
                        r.predicate,
                        r.weight,
                    )
                    for r in edges
                ],
            )

    async def list_entity_names(
        self, kb_id: uuid.UUID, limit: int = 2000
    ) -> list[tuple[str, int]]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(Entity.name, Entity.mention_count)
                .where(Entity.kb_id == kb_id)
                .order_by(Entity.mention_count.desc())
                .limit(limit)
            )
            return [(r[0], r[1]) for r in rows]

    async def delete_by_kb(self, kb_id: uuid.UUID) -> None:
        async with self._sessions() as session:
            await session.execute(delete(Relation).where(Relation.kb_id == kb_id))
            await session.execute(
                delete(Entity).where(Entity.kb_id == kb_id)
            )
            await session.commit()

    async def kb_stats(self, kb_id: uuid.UUID) -> dict:
        async with self._sessions() as session:
            e_count = await session.scalar(
                select(func.count()).select_from(Entity).where(Entity.kb_id == kb_id)
            )
            r_count = await session.scalar(
                select(func.count()).select_from(Relation).where(Relation.kb_id == kb_id)
            )
            top = (
                await session.execute(
                    select(Entity.name, Entity.mention_count)
                    .where(Entity.kb_id == kb_id)
                    .order_by(Entity.mention_count.desc())
                    .limit(10)
                )
            ).all()
            return {
                "entity_count": e_count or 0,
                "relation_count": r_count or 0,
                "top_entities": [(r[0], r[1]) for r in top],
            }


_graph_store: GraphStore | None = None


def get_graph_store() -> GraphStore:
    global _graph_store
    if _graph_store is None:
        _graph_store = PGGraphStore()
    return _graph_store
