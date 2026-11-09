"""eval 表 + wechat_configs

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _uuid_pk():
    return sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True)


def upgrade() -> None:
    op.create_table(
        "eval_sets",
        _uuid_pk(),
        sa.Column("app_id", sa.Uuid(), sa.ForeignKey("apps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_eval_sets_app_id", "eval_sets", ["app_id"])

    op.create_table(
        "eval_cases",
        _uuid_pk(),
        sa.Column("eval_set_id", sa.Uuid(), sa.ForeignKey("eval_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_points", sa.Text(), nullable=False, server_default=""),
        sa.Column("expected_doc_name", sa.String(500), nullable=False, server_default=""),
    )
    op.create_index("ix_eval_cases_eval_set_id", "eval_cases", ["eval_set_id"])

    op.create_table(
        "eval_runs",
        _uuid_pk(),
        sa.Column("eval_set_id", sa.Uuid(), sa.ForeignKey("eval_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_faithfulness", sa.Float()),
        sa.Column("avg_relevance", sa.Float()),
        sa.Column("hit_rate", sa.Float()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_eval_runs_eval_set_id", "eval_runs", ["eval_set_id"])

    op.create_table(
        "eval_results",
        _uuid_pk(),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("eval_cases.id", ondelete="SET NULL")),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("retrieved_doc_names", JSONB(), nullable=False, server_default="[]"),
        sa.Column("faithfulness", sa.Float()),
        sa.Column("relevance", sa.Float()),
        sa.Column("hit", sa.Boolean()),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_eval_results_run", "eval_results", ["run_id"])

    op.create_table(
        "wechat_configs",
        _uuid_pk(),
        sa.Column("app_id", sa.Uuid(), sa.ForeignKey("apps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False, server_default=""),
        sa.Column("wx_app_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("verify_token", sa.String(200), nullable=False),
        sa.Column("aes_key_enc", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("welcome_reply", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("app_id", name="uq_wechat_config_app"),
    )


def downgrade() -> None:
    op.drop_table("wechat_configs")
    op.drop_index("ix_eval_results_run", table_name="eval_results")
    op.drop_table("eval_results")
    op.drop_index("ix_eval_runs_eval_set_id", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index("ix_eval_cases_eval_set_id", table_name="eval_cases")
    op.drop_table("eval_cases")
    op.drop_index("ix_eval_sets_app_id", table_name="eval_sets")
    op.drop_table("eval_sets")
