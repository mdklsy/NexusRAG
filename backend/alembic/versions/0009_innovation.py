"""创新批次：审核决策审计、知识缺口、消息检索命中/卡片、文档 ACL、评测诊断、语义缓存标记。

Revision ID: 0009
Revises: 0008
"""

revision = "0009"
down_revision = "0008"

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # ---- 审核数据飞轮：决策审计（replace 前的原文必须留存） ----
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("app_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("apps.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("message_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(10), nullable=False),  # approve|replace|reject
        sa.Column("editor_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("content_before", sa.Text, nullable=True),
        sa.Column("content_after", sa.Text, nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_review_decisions_app_time", "review_decisions", ["app_id", "decided_at"]
    )

    # ---- 知识缺口：无答案问题聚类主题 ----
    op.create_table(
        "knowledge_gaps",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("app_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("apps.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("theme", sa.String(200), nullable=False),
        sa.Column("representative_questions", sa.JSON, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("occurrences", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),  # open|drafted|resolved
        sa.Column("draft_answer", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_knowledge_gaps_app_status", "knowledge_gaps", ["app_id", "status"])

    # ---- 消息：检索命中（缺口信号源）+ 结构化卡片（生成式 UI） ----
    op.add_column("messages", sa.Column("hit", sa.Boolean, nullable=True))
    op.add_column("messages", sa.Column("cards", sa.JSON, nullable=True))

    # ---- 文档 ACL：{"mode":"public"} | {"mode":"restricted","end_users":[...]} ----
    op.add_column("documents", sa.Column("acl", sa.JSON, nullable=True))

    # ---- 评测自诊断：chunk 级召回证据 + 归因结论 ----
    op.add_column("eval_results", sa.Column("retrieved_chunks", sa.JSON, nullable=True))
    op.add_column("eval_results", sa.Column("diagnosis", sa.JSON, nullable=True))
    op.add_column("eval_runs", sa.Column("avg_context_sufficiency", sa.Float, nullable=True))

    # ---- 语义缓存命中标记（看板统计节省量） ----
    op.add_column(
        "usage_events",
        sa.Column("cached", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("usage_events", "cached")
    op.drop_column("eval_runs", "avg_context_sufficiency")
    op.drop_column("eval_results", "diagnosis")
    op.drop_column("eval_results", "retrieved_chunks")
    op.drop_column("documents", "acl")
    op.drop_column("messages", "cards")
    op.drop_column("messages", "hit")
    op.drop_index("ix_knowledge_gaps_app_status", table_name="knowledge_gaps")
    op.drop_table("knowledge_gaps")
    op.drop_index("ix_review_decisions_app_time", table_name="review_decisions")
    op.drop_table("review_decisions")
