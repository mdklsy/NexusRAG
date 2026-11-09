"""chunk_tokens 倒排索引（BM25 混合检索）

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chunk_tokens",
        sa.Column("chunk_id", sa.Uuid(), sa.ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("token", sa.String(120), primary_key=True),
        sa.Column("kb_id", sa.Uuid(), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_chunk_tokens_token", "chunk_tokens", ["token"])
    op.create_index("ix_chunk_tokens_kb_id", "chunk_tokens", ["kb_id"])


def downgrade() -> None:
    op.drop_index("ix_chunk_tokens_kb_id", table_name="chunk_tokens")
    op.drop_index("ix_chunk_tokens_token", table_name="chunk_tokens")
    op.drop_table("chunk_tokens")
