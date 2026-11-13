"""人机协作全局路由：跨应用的审批单 / 待审核回答队列（控制台「人机协作」页数据源）。

与 /apps/{app_id}/approvals、/apps/{app_id}/reviews 的区别：这里不按应用隔离，
值班视角一次看到所有应用的待办；决策逻辑复用 services.approvals。
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.session import get_session
from app.models.app import App, Conversation, Message, PendingAction
from app.models.platform import User
from app.services import approvals

router = APIRouter(prefix="/hitl", tags=["human-in-loop"])


@router.get("/counts")
async def hitl_counts(
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """全局待办数（侧边栏角标 + 页签计数）。"""
    return await approvals.count_pending(session)


@router.get("/approvals")
async def list_approvals(
    status: str | None = "pending",
    app_id: uuid.UUID | None = None,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = await approvals.list_actions(session, app_id, status)
    return [
        {
            "id": str(row["action"].id),
            "app_id": str(row["action"].app_id),
            "app_name": row["app_name"],
            "conversation_id": str(row["action"].conversation_id),
            "tool_name": row["action"].tool_name,
            "args": row["action"].args,
            "status": row["action"].status,
            "result_text": row["action"].result_text,
            "created_at": row["action"].created_at,
        }
        for row in rows
    ]


class DecisionIn(BaseModel):
    approved: bool


@router.post("/approvals/{action_id}/decide")
async def decide_approval(
    action_id: uuid.UUID,
    body: DecisionIn,
    user: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    action = await session.get(PendingAction, action_id)
    if action is None:
        raise HTTPException(404, "审批单不存在")
    app = await session.get(App, action.app_id)
    try:
        action = await approvals.decide_action(session, app, action_id, body.approved, user.id)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    msg = await approvals.continue_after_decision(session, app, action)
    return {
        "status": action.status,
        "result_text": action.result_text,
        "followup_message_id": str(msg.id),
    }


@router.get("/reviews")
async def list_reviews(
    app_id: uuid.UUID | None = None,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = await approvals.list_pending_reviews(session, app_id)
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


class ReviewDecisionIn(BaseModel):
    action: str  # approve | replace | reject
    content: str | None = None  # action=replace 时的改写稿


@router.post("/reviews/{message_id}/decide")
async def decide_review(
    message_id: uuid.UUID,
    body: ReviewDecisionIn,
    user: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    msg = await session.get(Message, message_id)
    conv = await session.get(Conversation, msg.conversation_id) if msg else None
    if msg is None or conv is None:
        raise HTTPException(404, "消息不存在")
    if msg.review_status != "pending":
        raise HTTPException(409, f"该回答已处理（{msg.review_status}）")
    try:
        await approvals.decide_review(session, msg, body.action, body.content)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"review_status": msg.review_status}
