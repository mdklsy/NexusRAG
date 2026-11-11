"""对话路由：SSE 流式对话（JWT 或 API Key 双认证）+ 会话管理 + 挂件历史会话。"""

import hashlib
import hmac as hmac_mod
import json
import time
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_by_api_key, get_current_user
from app.db.session import get_session
from app.models.app import App, Conversation, Message
from app.schemas import ChatIn, ConversationOut, MessageOut
from app.services.chat.orchestrator import run_chat

router = APIRouter(tags=["chat"])

SIG_TTL_SECONDS = 86400  # 页面后端每次渲染重新签发，签给出的票据按天有效


def _verify_user_sig(app: App, end_user_id: str, ts: int, sig: str) -> None:
    """校验页面后端签发的终端用户票据：HMAC-SHA256(secret, f"{end_user_id}:{ts}")。

    secret 存应用 widget_config.widget_secret（页面后端持有，绝不进前端）——
    没有 secret 就无法为任意 end_user_id 伪造签名，历史会话因此按用户隔离。
    """
    secret = (app.widget_config or {}).get("widget_secret")
    if not secret:
        raise HTTPException(400, "应用未配置 widget_secret，无法使用终端用户历史")
    if abs(time.time() - ts) > SIG_TTL_SECONDS:
        raise HTTPException(401, "票据已过期，请刷新页面重新获取")
    expected = hmac_mod.new(
        secret.encode(), f"{end_user_id}:{ts}".encode(), hashlib.sha256
    ).hexdigest()
    if not hmac_mod.compare_digest(expected, sig):
        raise HTTPException(401, "终端用户票据校验失败")


async def _resolve_principal(
    body: ChatIn,
    authorization: str,
    session: AsyncSession,
) -> App:
    """API Key（nx- 开头）→ 应用直连；否则 JWT → 必须指定 app_id。"""
    token = authorization[7:] if authorization.startswith("Bearer ") else ""
    if token.startswith("nx-"):
        app = await get_app_by_api_key(authorization=authorization, session=session)
        if body.app_id and body.app_id != app.id:
            raise HTTPException(403, "API Key 与 app_id 不匹配")
        return app
    # JWT 认证（仅校验身份，用户对象不直接使用）
    await get_current_user(authorization=authorization, session=session)
    if body.app_id is None:
        raise HTTPException(400, "控制台调用必须提供 app_id")
    app = await session.get(App, body.app_id)
    if app is None:
        raise HTTPException(404, "应用不存在")
    return app


@router.post("/chat/stream")
async def chat_stream(
    body: ChatIn,
    authorization: str = Header(default=""),
    session: AsyncSession = Depends(get_session),
):
    app = await _resolve_principal(body, authorization, session)
    if not body.question:
        raise HTTPException(400, "消息不能为空")

    # 会话：无则创建
    conversation_id = body.conversation_id
    if conversation_id:
        conv = await session.get(Conversation, conversation_id)
        if conv is None or conv.app_id != app.id:
            raise HTTPException(404, "会话不存在")
    else:
        conv = Conversation(app_id=app.id)
        if body.end_user:
            conv.end_user_id = body.end_user.id
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        conversation_id = conv.id

    # 历史窗口
    window = int((app.retrieval_config or {}).get("history_window", 12))
    rows = (
        (
            await session.execute(
                select(Message.role, Message.content)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(window)
            )
        )
        .all()
    )
    history = [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    def sse(event: dict) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    async def event_stream() -> AsyncGenerator[str, None]:
        # 会话信息先行下发，便于调用方持久化 conversation_id
        yield sse({"type": "conversation", "conversation_id": str(conversation_id)})
        try:
            async for event in run_chat(
                session,
                app,
                conversation_id,
                body.question,
                history,
                end_user=body.end_user.model_dump() if body.end_user else None,
                metadata=body.metadata,
            ):
                yield sse(event)
        except Exception as e:  # noqa: BLE001
            yield sse({"type": "error", "message": f"{type(e).__name__}: {e}"})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/apps/{app_id}/conversations", response_model=list[ConversationOut])
async def list_conversations(
    app_id: uuid.UUID,
    _: object = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return (
        (
            await session.execute(
                select(Conversation)
                .where(Conversation.app_id == app_id)
                .order_by(Conversation.updated_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: uuid.UUID,
    _: object = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return (
        (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at, Message.id)
            )
        )
        .scalars()
        .all()
    )


# ---------- 挂件历史会话（终端用户身份由页面后端 HMAC 票据保证） ----------


@router.get("/chat/conversations")
async def widget_conversations(
    end_user_id: str,
    ts: int,
    sig: str,
    authorization: str = Header(default=""),
    session: AsyncSession = Depends(get_session),
):
    """按终端用户列其会话（nx- Key 认证 + 票据验签，防冒充他人拉历史）。"""
    app = await get_app_by_api_key(authorization=authorization, session=session)
    _verify_user_sig(app, end_user_id, ts, sig)
    rows = (
        (
            await session.execute(
                select(Conversation)
                .where(
                    Conversation.app_id == app.id,
                    Conversation.end_user_id == end_user_id,
                )
                .order_by(Conversation.updated_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(c.id),
            "title": c.title,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        }
        for c in rows
    ]


@router.get("/chat/conversations/{conversation_id}/messages")
async def widget_messages(
    conversation_id: uuid.UUID,
    end_user_id: str,
    ts: int,
    sig: str,
    limit: int = 30,
    before: uuid.UUID | None = None,
    authorization: str = Header(default=""),
    session: AsyncSession = Depends(get_session),
):
    """按终端用户取某会话的消息（归属校验：应用 + end_user 双匹配）。

    游标分页（挂件下拉懒加载）：不传 before 返回最新 limit 条（升序）；
    传 before=消息 id 则返回该消息之前的 limit 条。has_more 告知是否还有更早的。
    created_at 是事务时间（同事务插入的行相同），游标用 (created_at, id) 元组。
    """
    limit = max(1, min(limit, 100))
    app = await get_app_by_api_key(authorization=authorization, session=session)
    _verify_user_sig(app, end_user_id, ts, sig)
    conv = await session.get(Conversation, conversation_id)
    if (
        conv is None
        or conv.app_id != app.id
        or conv.end_user_id != end_user_id
    ):
        raise HTTPException(404, "会话不存在")

    filters = [Message.conversation_id == conversation_id]
    if before is not None:
        cursor = await session.get(Message, before)
        if cursor is None or cursor.conversation_id != conversation_id:
            raise HTTPException(404, "游标消息不存在")
        filters.append(
            tuple_(Message.created_at, Message.id)
            < tuple_(cursor.created_at, cursor.id)
        )
    rows = (
        (
            await session.execute(
                select(Message)
                .where(*filters)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    has_more = len(rows) > limit
    rows = list(reversed(rows[:limit]))
    return {
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "citations": m.citations or [],
                "created_at": m.created_at,
            }
            for m in rows
        ],
        "has_more": has_more,
    }
