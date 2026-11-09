"""initial schema（一期 MVP 的 13 张表，显式 DDL）

Revision ID: 0001
Revises:
Create Date: 2026-11-09

注意：不能用 Base.metadata.create_all —— metadata 是"当前"模型，
会把后续迁移（0002+）的表/列提前建出，升级链必然撞车。
历史时点的结构只能显式书写；列定义与一期模型严格一致。
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
NOW = sa.func.now()
UUID_PK = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=UUID_PK, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("updated_at", TS, server_default=NOW, nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "apps",
        sa.Column("id", sa.Uuid(), server_default=UUID_PK, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("icon", sa.String(10), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("llm_config", sa.JSON(), nullable=False),
        sa.Column("retrieval_config", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("updated_at", TS, server_default=NOW, nullable=False),
    )
    op.create_index("ix_apps_tenant_id", "apps", ["tenant_id"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), server_default=UUID_PK, primary_key=True),
        sa.Column("app_id", sa.Uuid(), sa.ForeignKey("apps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_used_at", TS),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("updated_at", TS, server_default=NOW, nullable=False),
    )
    op.create_index("ix_api_keys_app_id", "api_keys", ["app_id"])
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Uuid(), server_default=UUID_PK, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        sa.Column("chunk_config", sa.JSON(), nullable=False),
        sa.Column("doc_count", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("updated_at", TS, server_default=NOW, nullable=False),
    )
    op.create_index("ix_knowledge_bases_tenant_id", "knowledge_bases", ["tenant_id"])

    op.create_table(
        "app_knowledge_bases",
        sa.Column("app_id", sa.Uuid(), sa.ForeignKey("apps.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kb_id", sa.Uuid(), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), server_default=UUID_PK, primary_key=True),
        sa.Column("app_id", sa.Uuid(), sa.ForeignKey("apps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("updated_at", TS, server_default=NOW, nullable=False),
    )
    op.create_index("ix_conversations_app_id", "conversations", ["app_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), server_default=UUID_PK, primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("updated_at", TS, server_default=NOW, nullable=False),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_conversation", "messages", ["conversation_id", "created_at"])

    op.create_table(
        "usage_events",
        sa.Column("id", sa.Uuid(), server_default=UUID_PK, primary_key=True),
        sa.Column("app_id", sa.Uuid(), sa.ForeignKey("apps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("hit", sa.Boolean()),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
    )
    op.create_index("ix_usage_events_app_id", "usage_events", ["app_id"])
    op.create_index("ix_usage_events_created_at", "usage_events", ["created_at"])
    op.create_index("ix_usage_events_app_created", "usage_events", ["app_id", "created_at"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), server_default=UUID_PK, primary_key=True),
        sa.Column("kb_id", sa.Uuid(), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("file_path", sa.Text()),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("updated_at", TS, server_default=NOW, nullable=False),
    )
    op.create_index("ix_documents_kb_id", "documents", ["kb_id"])
    op.create_index("ix_documents_kb_status", "documents", ["kb_id", "status"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), server_default=UUID_PK, primary_key=True),
        sa.Column("kb_id", sa.Uuid(), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("updated_at", TS, server_default=NOW, nullable=False),
    )
    op.create_index("ix_chunks_kb_id", "chunks", ["kb_id"])
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])

    op.create_table(
        "entities",
        sa.Column("id", sa.Uuid(), server_default=UUID_PK, primary_key=True),
        sa.Column("kb_id", sa.Uuid(), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("norm_name", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("mention_count", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("updated_at", TS, server_default=NOW, nullable=False),
        # KG 实体归一合并的 upsert 依赖此唯一约束（ON CONFLICT）
        sa.UniqueConstraint("kb_id", "norm_name", "type", name="uq_entities_kb_norm_type"),
    )
    op.create_index("ix_entities_kb_id", "entities", ["kb_id"])
    op.create_index("ix_entities_kb_name", "entities", ["kb_id", "name"])

    op.create_table(
        "relations",
        sa.Column("id", sa.Uuid(), server_default=UUID_PK, primary_key=True),
        sa.Column("kb_id", sa.Uuid(), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_entity_id", sa.Uuid(), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("target_entity_id", sa.Uuid(), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("predicate", sa.String(200), nullable=False),
        sa.Column("evidence_chunk_id", sa.Uuid(), sa.ForeignKey("chunks.id", ondelete="SET NULL")),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("updated_at", TS, server_default=NOW, nullable=False),
        # 关系去重 upsert 依赖此唯一约束（ON CONFLICT DO UPDATE weight+1）
        sa.UniqueConstraint("kb_id", "source_entity_id", "predicate", "target_entity_id", name="uq_relations_triple"),
    )
    op.create_index("ix_relations_kb_id", "relations", ["kb_id"])
    op.create_index("ix_relations_kb_source", "relations", ["kb_id", "source_entity_id"])
    op.create_index("ix_relations_kb_target", "relations", ["kb_id", "target_entity_id"])

    op.create_table(
        "chunk_entities",
        sa.Column("chunk_id", sa.Uuid(), sa.ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("entity_id", sa.Uuid(), sa.ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True),
        sa.UniqueConstraint("chunk_id", "entity_id", name="uq_chunk_entities"),
    )
    op.create_index("ix_chunk_entities_entity", "chunk_entities", ["entity_id"])


def downgrade() -> None:
    for name in [
        "chunk_entities", "relations", "entities", "chunks", "documents",
        "usage_events", "messages", "conversations", "app_knowledge_bases",
        "knowledge_bases", "api_keys", "apps", "users",
    ]:
        op.drop_table(name)
