"""users.role 权限 + is_admin 迁移

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(20), nullable=False, server_default="editor"),
    )
    # 原 is_admin=true 的用户升为 admin
    op.execute("UPDATE users SET role = 'admin' WHERE is_admin = true")
    op.drop_column("users", "is_admin")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE users SET is_admin = true WHERE role = 'admin'")
    op.drop_column("users", "role")
