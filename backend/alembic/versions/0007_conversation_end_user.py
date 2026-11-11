"""conversations 加终端用户标识（挂件历史会话按 end_user 隔离）。

Revision ID: 0007_conversation_end_user
Revises: 0006_system_settings
"""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("end_user_id", sa.String(length=128), nullable=True),
    )
    op.create_index("ix_conversations_end_user", "conversations", ["end_user_id"])


def downgrade() -> None:
    op.drop_index("ix_conversations_end_user", table_name="conversations")
    op.drop_column("conversations", "end_user_id")
