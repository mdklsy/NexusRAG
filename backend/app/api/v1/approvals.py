"""人机协作路由：工具调用审批 + 回答人工审核。

审批（形态①）：require_approval 工具被代理调用时落审批单，编辑者在控制台
通过/拒绝；通过则真执行并续跑同一会话向用户交代结果。
审核（形态④）：review_mode=on 的应用回答落 pending，编辑者通过（可改写）/
驳回后才（不）对终端用户可见。
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.session import get_session
from app.models.app import App
from app.models.platform import User
from app.services import approvals

router = APIRouter(prefix="/apps/{app_id}", tags=["human-in-loop"])


async def _get_app(app_id: uuid.UUID, session: AsyncSession) -> App:
    app = await session.get(App, app_id)
    if app is None:
        raise HTTPException(404, "应用不存在")
    return app


# ---------- 审批单 ----------


@router.get("/approvals")
async def list_approvals(
    app_id: uuid.UUID,
    status: str | None = None,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    app = await _get_app(app_id, session)
    rows = await approvals.list_actions(session, app.id, status)
    return [
        {
            "id": str(row["action"].id),
            "conversation_id": str(row["action"].conversation_id),
            "tool_name": row["action"].tool_name,
            "args": row["action"].args,
            "status": row["action"].status,
            "result_text": row["action"].result_text,
            "created_at": row["action"].created_at,
            "decided_at": row["action"].decided_at,
        }
        for row in rows
    ]


class DecisionIn(BaseModel):
    approved: bool


@router.post("/approvals/{action_id}/decide")
async def decide_approval(
    app_id: uuid.UUID,
    action_id: uuid.UUID,
    body: DecisionIn,
    user: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    app = await _get_app(app_id, session)
    try:
        action = await approvals.decide_action(session, app, action_id, body.approved, user.id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    # 续跑同一会话：模型基于执行结果生成对用户的交代
    msg = await approvals.continue_after_decision(session, app, action)
    return {
        "status": action.status,
        "result_text": action.result_text,
        "followup_message_id": str(msg.id),
    }


# ---------- 回答审核 ----------


@router.get("/reviews")
async def list_reviews(
    app_id: uuid.UUID,
    status: str = "pending",
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    app = await _get_app(app_id, session)
    if status == "pending":
        rows = await approvals.list_pending_reviews(session, app.id)
        return [
            {
                "message_id": str(row["message"].id),
                "app_id": str(row["app_id"]),
                "app_name": row["app_name"],
                "conversation_id": str(row["message"].conversation_id),
                "conversation_title": row["conversation_title"],
                "content": row["message"].content,
                "citations": row["message"].citations or [],
                "created_at": row["message"].created_at,
            }
            for row in rows
        ]
    return []


class ReviewDecisionIn(BaseModel):
    action: str  # approve | replace | reject
    content: str | None = None  # action=replace 时的改写稿


@router.post("/reviews/{message_id}/decide")
async def decide_review(
    app_id: uuid.UUID,
    message_id: uuid.UUID,
    body: ReviewDecisionIn,
    user: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    from app.models.app import Conversation, Message

    app = await _get_app(app_id, session)
    msg = await session.get(Message, message_id)
    conv = await session.get(Conversation, msg.conversation_id) if msg else None
    if msg is None or conv is None or conv.app_id != app.id:
        raise HTTPException(404, "消息不存在")
    if msg.review_status != "pending":
        raise HTTPException(409, f"该回答已处理（{msg.review_status}）")
    try:
        msg = await approvals.decide_review(session, msg, body.action, body.content)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"review_status": msg.review_status}
