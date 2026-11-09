"""tools + widget_config + api_key scope

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tools",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("app_id", sa.Uuid(), sa.ForeignKey("apps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("config", JSONB(), nullable=False, server_default="{}"),
        sa.Column("parameters_schema", JSONB(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("app_id", "name", name="uq_tools_app_name"),
    )
    op.create_index("ix_tools_app_id", "tools", ["app_id"])
    op.add_column("apps", sa.Column("widget_config", JSONB(), nullable=False, server_default="{}"))
    op.add_column("api_keys", sa.Column("scope", sa.String(20), nullable=False, server_default="full"))


def downgrade() -> None:
    op.drop_column("api_keys", "scope")
    op.drop_column("apps", "widget_config")
    op.drop_index("ix_tools_app_id", table_name="tools")
    op.drop_table("tools")
