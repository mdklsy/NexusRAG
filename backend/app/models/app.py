"""应用域模型：应用、应用-知识库绑定、对话、消息、用量事件。"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, TenantMixin, TimestampMixin
from app.models.kb import JSONType

DEFAULT_LLM_CONFIG = {"model": "", "temperature": 0.3, "max_tokens": 2048}
DEFAULT_RETRIEVAL_CONFIG = {
    "top_k": 5,
    "score_threshold": 0.35,
    "use_kg": True,
    "kg_hops": 1,
    "kg_top_entities": 3,
    "history_window": 12,
    "intent_route": True,
    "use_bm25": True,   # 混合检索：向量 + BM25，RRF 融合
    "rerank": "none",   # none | llm | cross_encoder
}
DEFAULT_WIDGET_CONFIG = {"title": "", "welcome": "", "theme": "#1677ff", "bubble": "💬"}
DEFAULT_TOOL_CONFIG = {"timeout": 15}


class App(TenantMixin, TimestampMixin, Base):
    __tablename__ = "apps"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(10), default="🤖")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    llm_config: Mapped[dict] = mapped_column(JSONType, default=DEFAULT_LLM_CONFIG)
    retrieval_config: Mapped[dict] = mapped_column(
        JSONType, default=DEFAULT_RETRIEVAL_CONFIG
    )
    widget_config: Mapped[dict] = mapped_column(
        JSONType, default=DEFAULT_WIDGET_CONFIG
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Tool(TimestampMixin, Base):
    """业务系统连接器：LLM 通过 function calling 调用。

    type = http_api：config = {method, url, headers{}, timeout}
                          LLM args = {path_params{}, query{}, body{}}
    type = sql_db  ：config = {dsn, timeout}（仅允许 SELECT）
                          LLM args = {sql}
    """

    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("app_id", "name", name="uq_tools_app_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("apps.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))  # 同时作为 function name（slug 化）
    display_name: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")  # LLM 看到的用途说明
    type: Mapped[str] = mapped_column(String(20))  # http_api | sql_db
    config: Mapped[dict] = mapped_column(JSONType, default=DEFAULT_TOOL_CONFIG)
    parameters_schema: Mapped[dict] = mapped_column(
        JSONType, default=dict
    )  # JSON Schema，空则按类型自动生成
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AppKnowledgeBase(Base):
    __tablename__ = "app_knowledge_bases"
    __table_args__ = (UniqueConstraint("app_id", "kb_id", name="uq_app_kb"),)

    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("apps.id", ondelete="CASCADE"), primary_key=True
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True
    )


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("apps.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), default="新对话")
    end_user_id: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    meta: Mapped[dict] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), default=dict)


class Message(TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation", "conversation_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONType, default=list)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    # 人工审核状态：published=已发布（默认）| pending=待审核（挂件不可见）| rejected=被驳回（挂件不可见）
    review_status: Mapped[str] = mapped_column(String(20), default="published", server_default="published", index=True)
    # 检索是否命中（仅 assistant 消息，intent=qa 时记录）：知识缺口发现的信号源
    hit: Mapped[bool | None] = mapped_column(Boolean)
    # 生成式 UI 卡片（工具响应携带 nexus_card 时收集），挂件渲染成结构化组件
    cards: Mapped[list | None] = mapped_column(JSONType, nullable=True)


class PendingAction(TimestampMixin, Base):
    """工具调用人工审批单：代理要调敏感工具时先落单，人通过后才真执行。"""

    __tablename__ = "pending_actions"
    __table_args__ = (Index("ix_pending_actions_status", "app_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("apps.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    tool_name: Mapped[str] = mapped_column(String(120))
    args: Mapped[dict] = mapped_column(JSONType, default=dict)
    # 审批续跑所需的业务上下文快照（end_user/metadata）——metadata 不落会话，只能这里快照
    ctx_snapshot: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected
    result_text: Mapped[str | None] = mapped_column(Text, default=None)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class UsageEvent(Base):
    """用量事件：看板数据来源。type = chat | retrieval。"""

    __tablename__ = "usage_events"
    __table_args__ = (Index("ix_usage_events_app_created", "app_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    app_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(20))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    hit: Mapped[bool | None] = mapped_column(Boolean)  # 检索是否命中（chat 也记录）
    cached: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # 语义缓存命中
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class ReviewDecision(Base):
    """回答审核决策审计：飞轮数据源（改写对挖掘、驳回转评测、质量统计）。"""

    __tablename__ = "review_decisions"
    __table_args__ = (Index("ix_review_decisions_app_time", "app_id", "decided_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    app_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"))
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(10))  # approve | replace | reject
    editor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    content_before: Mapped[str | None] = mapped_column(Text)  # replace 前的原始回答
    content_after: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class KnowledgeGap(TimestampMixin, Base):
    """知识缺口：无答案问题经 LLM 聚类出的主题，提示知识库缺什么。"""

    __tablename__ = "knowledge_gaps"
    __table_args__ = (Index("ix_knowledge_gaps_app_status", "app_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    app_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"))
    theme: Mapped[str] = mapped_column(String(200))
    representative_questions: Mapped[list] = mapped_column(JSONType, default=list)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | drafted | resolved
    draft_answer: Mapped[str | None] = mapped_column(Text)
