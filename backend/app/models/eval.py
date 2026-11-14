"""评测域模型：评测集 / 用例 / 运行 / 结果。"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.kb import JSONType


class EvalSet(TimestampMixin, Base):
    __tablename__ = "eval_sets"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("apps.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")


class EvalCase(Base):
    __tablename__ = "eval_cases"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    eval_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_sets.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    expected_points: Mapped[str] = mapped_column(
        Text, default=""
    )  # 期望要点，供 LLM 判分参考
    expected_doc_name: Mapped[str] = mapped_column(String(500), default="")  # 期望命中的文档名


class EvalRun(TimestampMixin, Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    eval_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_sets.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending/running/completed/failed
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    avg_faithfulness: Mapped[float | None] = mapped_column(Float)
    avg_relevance: Mapped[float | None] = mapped_column(Float)
    avg_context_sufficiency: Mapped[float | None] = mapped_column(Float)  # 资料充分度（自诊断用）
    hit_rate: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)


class EvalResult(Base):
    __tablename__ = "eval_results"
    __table_args__ = (Index("ix_eval_results_run", "run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE")
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("eval_cases.id", ondelete="SET NULL")
    )
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")
    retrieved_doc_names: Mapped[list] = mapped_column(JSONType, default=list)
    faithfulness: Mapped[float | None] = mapped_column(Float)
    relevance: Mapped[float | None] = mapped_column(Float)
    context_sufficiency: Mapped[float | None] = mapped_column(Float)  # 资料是否足以回答
    retrieved_chunks: Mapped[list | None] = mapped_column(JSONType, nullable=True)  # [{chunk_id,document_name,heading,score}]
    diagnosis: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # {cause,detail,suggestion}
    hit: Mapped[bool | None] = mapped_column(Boolean)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
