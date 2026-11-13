"""人机协作：工具调用审批单表 + 消息人工审核状态列。

Revision ID: 0008
Revises: 0007
"""

revision = "0008"
down_revision = "0007"

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        "pending_actions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("app_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("apps.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("conversation_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("tool_name", sa.String(120), nullable=False),
        sa.Column("args", sa.JSON, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ctx_snapshot", sa.JSON, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),  # pending|approved|rejected
        sa.Column("result_text", sa.Text, nullable=True),
        sa.Column("decided_by", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column(
        "messages",
        sa.Column("review_status", sa.String(20), nullable=False, server_default="published"),
    )  # published|pending|rejected：挂件历史只返回 published
    op.create_index("ix_messages_review_status", "messages", ["review_status"])


def downgrade() -> None:
    op.drop_index("ix_messages_review_status", table_name="messages")
    op.drop_column("messages", "review_status")
    op.drop_table("pending_actions")
