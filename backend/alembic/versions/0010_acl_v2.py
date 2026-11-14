"""ACL v2：块级权限（覆盖模式）+ 属性声明。

Revision ID: 0010
Revises: 0009
"""

revision = "0010"
down_revision = "0009"

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "chunks",
        sa.Column("acl", sa.JSON, nullable=True),
    )  # NULL=继承文档规则；有值=覆盖（形状同 documents.acl：{"mode":"public"} 或
    # {"mode":"restricted","end_users":[...],"claims":[{"key","values":[...]}]}）


def downgrade() -> None:
    op.drop_column("chunks", "acl")
