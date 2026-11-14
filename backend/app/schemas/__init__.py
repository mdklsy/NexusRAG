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
    acl: dict | None = None  # None/{"mode":"public"}=公开；{"mode":"restricted","end_users":[...]}=白名单


class ClaimIn(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    values: list[str] = Field(min_length=1, max_length=100)


class DocumentAclIn(BaseModel):
    mode: str = Field(pattern="^(public|restricted)$")
    end_users: list[str] = Field(default_factory=list, max_length=500)
    claims: list[ClaimIn] = Field(default_factory=list, max_length=20)

    def to_acl(self) -> dict:
        if self.mode == "public":
            return {"mode": "public"}
        if not self.end_users and not self.claims:
            raise ValueError("受限模式至少需要一条授权规则（ID 白名单或属性声明）")
        return {"mode": "restricted", "end_users": self.end_users, "claims": [c.model_dump() for c in self.claims]}


class ChunkAclIn(BaseModel):
    mode: str = Field(pattern="^(inherit|public|restricted)$")
    end_users: list[str] = Field(default_factory=list, max_length=500)
    claims: list[ClaimIn] = Field(default_factory=list, max_length=20)

    def to_acl(self) -> dict | None:
        if self.mode == "inherit":
            return None
        doc_in = DocumentAclIn(
            mode=self.mode, end_users=self.end_users, claims=self.claims
        )
        return doc_in.to_acl()


class ChunkOut(ORMModel):
    id: uuid.UUID
    seq: int
    content: str
    token_count: int
    meta: dict
    acl: dict | None = None  # None=继承文档规则


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
    pending_approvals: int = 0  # 人机协作：待审批工具调用数
    pending_reviews: int = 0  # 人机协作：待人工审核回答数


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
    avg_context_sufficiency: float | None = None
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


class EndUserIn(BaseModel):
    """终端用户身份；页面后端签发的 HMAC 票据随请求携带（验签见 chat.py）。

    id 用于会话归属与工具模板 {{end_user.id}}；token 等敏感凭据放 metadata，
    只在服务端注入工具请求，不进 Prompt。
    """

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(default="", max_length=200)
    # 属性声明（ACL v2）：对接方系统作为身份事实源传入（dept/tier 等）；
    # 挂件浏览器场景不可信，应用配置了 widget_secret 时必须随 sig/ts 验签
    attributes: dict | None = None
    sig: str = Field(default="", max_length=200)
    ts: int = Field(default=0)


class ChatIn(BaseModel):
    app_id: uuid.UUID | None = None  # JWT 认证时必填；API Key 认证时忽略
    conversation_id: uuid.UUID | None = None
    messages: list[ChatMessageIn] = []
    query: str = ""  # 兼容：messages 为空时用 query
    end_user: EndUserIn | None = None  # 终端用户身份（历史会话归属 + 工具模板）
    metadata: dict = Field(default_factory=dict)  # 业务参数（token/order_id 等），仅服务端可见

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


class WidgetConversationOut(BaseModel):
    """挂件历史会话列表项（按 end_user 隔离）。"""

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class MessageOut(ORMModel):
    id: uuid.UUID
    role: str
    content: str
    citations: list
    tokens_in: int
    tokens_out: int
    latency_ms: int
    created_at: datetime
    review_status: str = "published"
    cards: list | None = None  # 生成式 UI 卡片（工具 nexus_card）



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
    cached_chats: int = 0  # 语义缓存命中次数
    cached_tokens: int = 0  # 缓存命中的对话不再消耗的 token 估算


class TimeseriesPoint(BaseModel):
    date: str
    chats: int
    tokens: int
