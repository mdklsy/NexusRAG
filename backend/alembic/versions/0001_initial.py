"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-09

首版全量建表：直接绑定 ORM metadata 渲染，保证与模型一致。
"""

from alembic import op

from app.db.base import Base
import app.models  # noqa: F401  注册全部模型

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
