"""知识域模型：知识库、文档、分块、实体、关系。"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, TenantMixin, TimestampMixin

# jsonb 在 PG 上，sqlite（单测）回退为 JSON
JSONType = JSONB().with_variant(JSON(), "sqlite")

DEFAULT_CHUNK_CONFIG = {"size": 500, "overlap": 50}


class KnowledgeBase(TenantMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    embedding_model: Mapped[str] = mapped_column(String(200))
    embedding_dim: Mapped[int] = mapped_column(Integer)
    chunk_config: Mapped[dict] = mapped_column(JSONType, default=DEFAULT_CHUNK_CONFIG)
    doc_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_kb_status", "kb_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(500))
    source_type: Mapped[str] = mapped_column(String(20))  # upload | url
    source_url: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending|parsing|chunking|embedding|extracting_kg|completed|failed
    error: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)


class Chunk(TimestampMixin, Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)


class Entity(TimestampMixin, Base):
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("kb_id", "norm_name", "type", name="uq_entities_kb_norm_type"),
        Index("ix_entities_kb_name", "kb_id", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(300))
    type: Mapped[str] = mapped_column(String(50), default="OTHER")
    norm_name: Mapped[str] = mapped_column(String(300))  # 归一名（小写/去空格）用于合并
    description: Mapped[str] = mapped_column(Text, default="")
    mention_count: Mapped[int] = mapped_column(Integer, default=1)


class Relation(TimestampMixin, Base):
    __tablename__ = "relations"
    __table_args__ = (
        UniqueConstraint(
            "kb_id",
            "source_entity_id",
            "predicate",
            "target_entity_id",
            name="uq_relations_triple",
        ),
        Index("ix_relations_kb_source", "kb_id", "source_entity_id"),
        Index("ix_relations_kb_target", "kb_id", "target_entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    source_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"))
    target_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"))
    predicate: Mapped[str] = mapped_column(String(200))
    evidence_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="SET NULL")
    )
    weight: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChunkEntity(Base):
    """chunk 与实体的链接表（图检索时反查证据）。"""

    __tablename__ = "chunk_entities"
    __table_args__ = (
        UniqueConstraint("chunk_id", "entity_id", name="uq_chunk_entities"),
        Index("ix_chunk_entities_entity", "entity_id"),
    )

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )


class ChunkToken(Base):
    """BM25 倒排索引：token → chunk。

    摄取时按 chunk 分词去重写入（每词一行）；
    检索时按 token 拉候选并在应用层计算 BM25（PG/SQLite 双方言通吃）。
    """

    __tablename__ = "chunk_tokens"
    __table_args__ = (
        UniqueConstraint("chunk_id", "token", name="uq_chunk_tokens"),
        Index("ix_chunk_tokens_token", "token"),
    )

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    token: Mapped[str] = mapped_column(String(120), primary_key=True)
    kb_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
