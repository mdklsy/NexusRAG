"""对话路由：SSE 流式对话（JWT 或 API Key 双认证）+ 会话管理。"""

import json
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_by_api_key, get_current_user
from app.db.session import get_session
from app.models.app import App, Conversation, Message
from app.schemas import ChatIn, ConversationOut, MessageOut
from app.services.chat.orchestrator import run_chat

router = APIRouter(tags=["chat"])


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
            async for event in run_chat(session, app, conversation_id, body.question, history):
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
