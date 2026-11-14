"""洞察路由：审核数据飞轮（统计/规则挖掘/驳回转评测）+ 知识缺口（分析/草稿/解决）。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.session import get_session
from app.models.app import App, KnowledgeGap
from app.models.platform import User
from app.services import insights

router = APIRouter(prefix="/apps/{app_id}/insights", tags=["insights"])


async def _get_app(app_id: uuid.UUID, session: AsyncSession) -> App:
    app = await session.get(App, app_id)
    if app is None:
        raise HTTPException(404, "应用不存在")
    return app


@router.get("/stats")
async def get_stats(
    app_id: uuid.UUID,
    days: int = 30,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    app = await _get_app(app_id, session)
    return await insights.review_stats(session, app.id, days)


class MineRulesIn(BaseModel):
    pass


@router.post("/mine-rules")
async def post_mine_rules(
    app_id: uuid.UUID,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    """从审核改写对照挖掘提示词规则（LLM 按需调用）。"""
    app = await _get_app(app_id, session)
    try:
        rules = await insights.mine_rules(session, app)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"rules": rules}


@router.get("/rejected")
async def get_rejected(
    app_id: uuid.UUID,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    app = await _get_app(app_id, session)
    return await insights.rejected_questions(session, app.id)


class ToEvalIn(BaseModel):
    message_ids: list[uuid.UUID]


@router.post("/rejected/to-eval")
async def post_to_eval(
    app_id: uuid.UUID,
    body: ToEvalIn,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    app = await _get_app(app_id, session)
    return await insights.to_eval_cases(session, app, body.message_ids)


@router.get("/gaps")
async def get_gaps(
    app_id: uuid.UUID,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    app = await _get_app(app_id, session)
    rows = (
        (
            await session.execute(
                select(KnowledgeGap)
                .where(KnowledgeGap.app_id == app.id)
                .order_by(KnowledgeGap.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [insights.serialize_gap(g) for g in rows]


class AnalyzeIn(BaseModel):
    days: int = 30


@router.post("/gaps/analyze")
async def post_analyze_gaps(
    app_id: uuid.UUID,
    body: AnalyzeIn | None = None,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    """聚类近期无答案问题 → 重建 open 状态的知识缺口。"""
    app = await _get_app(app_id, session)
    try:
        gaps = await insights.analyze_gaps(session, app, (body or AnalyzeIn()).days)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return [insights.serialize_gap(g) for g in gaps]


@router.post("/gaps/{gap_id}/draft")
async def post_draft_gap(
    app_id: uuid.UUID,
    gap_id: uuid.UUID,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    app = await _get_app(app_id, session)
    gap = await session.get(KnowledgeGap, gap_id)
    if gap is None or gap.app_id != app.id:
        raise HTTPException(404, "缺口不存在")
    gap = await insights.draft_gap(session, app, gap)
    return insights.serialize_gap(gap)


@router.post("/gaps/{gap_id}/resolve")
async def post_resolve_gap(
    app_id: uuid.UUID,
    gap_id: uuid.UUID,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    app = await _get_app(app_id, session)
    gap = await session.get(KnowledgeGap, gap_id)
    if gap is None or gap.app_id != app.id:
        raise HTTPException(404, "缺口不存在")
    gap.status = "resolved"
    await session.commit()
    await session.refresh(gap)
    return insights.serialize_gap(gap)
