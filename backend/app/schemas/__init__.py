"""Pydantic 请求/响应模型。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.app import DEFAULT_LLM_CONFIG, DEFAULT_RETRIEVAL_CONFIG
from app.models.kb import DEFAULT_CHUNK_CONFIG


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth ----------
class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    name: str
    role: str = "editor"


class UserCreate(BaseModel):
    email: str
    name: str = ""
    password: str = Field(min_length=6)
    role: str = "editor"


class UserUpdate(BaseModel):
    name: str | None = None
    password: str | None = Field(default=None, min_length=6)
    role: str | None = None


class TokenOut(BaseModel):
    token: str
    user: UserOut


# ---------- KnowledgeBase ----------
class KBCreate(BaseModel):
    name: str = Field(max_length=200)
    description: str = ""
    chunk_config: dict = Field(default_factory=lambda: dict(DEFAULT_CHUNK_CONFIG))


class KBUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    chunk_config: dict | None = None


class KBOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    embedding_model: str
    embedding_dim: int
    chunk_config: dict
    doc_count: int
    chunk_count: int
    created_at: datetime


# ---------- Document ----------
class DocumentUrlIn(BaseModel):
    url: str


class DocumentOut(ORMModel):
    id: uuid.UUID
    kb_id: uuid.UUID
    name: str
    source_type: str
    source_url: str | None
    mime_type: str | None
    size_bytes: int
    status: str
    error: str | None
    chunk_count: int
    created_at: datetime


class ChunkOut(ORMModel):
    id: uuid.UUID
    seq: int
    content: str
    token_count: int
    meta: dict


# ---------- App ----------
class AppCreate(BaseModel):
    name: str = Field(max_length=200)
    description: str = ""
    icon: str = "🤖"
    system_prompt: str = ""
    llm_config: dict = Field(default_factory=lambda: dict(DEFAULT_LLM_CONFIG))
    retrieval_config: dict = Field(default_factory=lambda: dict(DEFAULT_RETRIEVAL_CONFIG))
    widget_config: dict = Field(default_factory=dict)
    kb_ids: list[uuid.UUID] = []


class AppUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    system_prompt: str | None = None
    llm_config: dict | None = None
    retrieval_config: dict | None = None
    widget_config: dict | None = None
    kb_ids: list[uuid.UUID] | None = None
    is_active: bool | None = None


class AppOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    icon: str
    system_prompt: str
    llm_config: dict
    retrieval_config: dict
    widget_config: dict = {}
    is_active: bool
    created_at: datetime


class AppDetailOut(AppOut):
    kb_ids: list[uuid.UUID] = []


# ---------- Tool（业务连接器） ----------
class ToolCreate(BaseModel):
    name: str = Field(max_length=100, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    display_name: str = ""
    description: str = ""
    type: str = Field(pattern=r"^(http_api|sql_db)$")
    config: dict = Field(default_factory=dict)
    parameters_schema: dict = Field(default_factory=dict)
    enabled: bool = True


class ToolUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    config: dict | None = None
    parameters_schema: dict | None = None
    enabled: bool | None = None


class ToolOut(ORMModel):
    id: uuid.UUID
    app_id: uuid.UUID
    name: str
    display_name: str
    description: str
    type: str
    config: dict
    enabled: bool
    created_at: datetime


class WidgetConfigOut(BaseModel):
    app_id: uuid.UUID
    title: str
    welcome: str
    theme: str
    bubble: str
    app_name: str


# ---------- Eval（评测） ----------
class EvalCaseIn(BaseModel):
    question: str = Field(min_length=1)
    expected_points: str = ""
    expected_doc_name: str = ""


class EvalCaseOut(ORMModel):
    id: uuid.UUID
    question: str
    expected_points: str
    expected_doc_name: str


class EvalSetCreate(BaseModel):
    name: str = Field(max_length=200)
    description: str = ""
    cases: list[EvalCaseIn]


class EvalSetOut(ORMModel):
    id: uuid.UUID
    app_id: uuid.UUID
    name: str
    description: str
    created_at: datetime


class EvalSetDetailOut(EvalSetOut):
    cases: list[EvalCaseOut] = []


class EvalRunOut(ORMModel):
    id: uuid.UUID
    eval_set_id: uuid.UUID
    status: str
    total: int
    done: int
    avg_faithfulness: float | None
    avg_relevance: float | None
    hit_rate: float | None
    error: str | None
    created_at: datetime


# ---------- WeChat（公众号） ----------
class WechatConfigCreate(BaseModel):
    name: str = ""
    wx_app_id: str = ""
    verify_token: str = Field(min_length=3)
    welcome_reply: str = ""


class WechatConfigUpdate(BaseModel):
    name: str | None = None
    wx_app_id: str | None = None
    verify_token: str | None = None
    welcome_reply: str | None = None
    enabled: bool | None = None


class WechatConfigOut(ORMModel):
    id: uuid.UUID
    app_id: uuid.UUID
    name: str
    wx_app_id: str
    verify_token: str
    welcome_reply: str
    enabled: bool


class ApiKeyOut(ORMModel):
    id: uuid.UUID
    app_id: uuid.UUID
    name: str
    is_active: bool
    scope: str = "full"
    last_used_at: datetime | None
    created_at: datetime


class ApiKeyCreated(BaseModel):
    key: str  # 明文仅此一次返回
    info: ApiKeyOut


# ---------- Retrieval（调试） ----------
class RetrievalIn(BaseModel):
    app_id: uuid.UUID | None = None
    kb_ids: list[uuid.UUID] = []
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = None
    use_kg: bool | None = None


class CitationOut(BaseModel):
    index: int
    chunk_id: str
    document_id: str
    document_name: str
    heading: str
    score: float
    snippet: str


class RetrievalOut(BaseModel):
    chunks: list[CitationOut]
    graph_facts: list[str]
    graph_entities: list[dict]
    context: str


# ---------- Chat ----------
class ChatMessageIn(BaseModel):
    role: str = "user"
    content: str


class ChatIn(BaseModel):
    app_id: uuid.UUID | None = None  # JWT 认证时必填；API Key 认证时忽略
    conversation_id: uuid.UUID | None = None
    messages: list[ChatMessageIn] = []
    query: str = ""  # 兼容：messages 为空时用 query

    @property
    def question(self) -> str:
        if self.messages:
            return self.messages[-1].content
        return self.query


class ConversationOut(ORMModel):
    id: uuid.UUID
    app_id: uuid.UUID
    title: str
    created_at: datetime


class MessageOut(ORMModel):
    id: uuid.UUID
    role: str
    content: str
    citations: list
    tokens_in: int
    tokens_out: int
    latency_ms: int
    created_at: datetime


# ---------- Dashboard ----------
class DashboardOverview(BaseModel):
    total_chats: int
    total_tokens_in: int
    total_tokens_out: int
    avg_latency_ms: int
    hit_rate: float
    total_documents: int
    total_chunks: int
    total_entities: int
    total_relations: int
    total_apps: int
    total_kbs: int


class TimeseriesPoint(BaseModel):
    date: str
    chats: int
    tokens: int
