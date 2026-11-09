"""评测路由：评测集 CRUD + 运行 + 结果查询。"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.session import get_session
from app.models.eval import EvalCase, EvalResult, EvalRun, EvalSet
from app.models.platform import User
from app.schemas import (
    EvalCaseOut,
    EvalRunOut,
    EvalSetCreate,
    EvalSetDetailOut,
    EvalSetOut,
)

router = APIRouter(tags=["evals"])
logger = logging.getLogger(__name__)


@router.post("/apps/{app_id}/eval-sets", response_model=EvalSetDetailOut, status_code=201)
async def create_eval_set(
    app_id: uuid.UUID,
    body: EvalSetCreate,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    if not body.cases:
        raise HTTPException(400, "至少包含一条用例")
    es = EvalSet(app_id=app_id, name=body.name, description=body.description)
    session.add(es)
    await session.flush()
    for c in body.cases:
        session.add(
            EvalCase(
                eval_set_id=es.id,
                question=c.question,
                expected_points=c.expected_points,
                expected_doc_name=c.expected_doc_name,
            )
        )
    await session.commit()
    await session.refresh(es)
    cases = await _load_cases(session, es.id)
    return EvalSetDetailOut(**EvalSetOut.model_validate(es).model_dump(), cases=cases)


@router.get("/apps/{app_id}/eval-sets", response_model=list[EvalSetOut])
async def list_eval_sets(
    app_id: uuid.UUID,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return (
        (
            await session.execute(
                select(EvalSet).where(EvalSet.app_id == app_id).order_by(EvalSet.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def _load_cases(session, eval_set_id) -> list[EvalCaseOut]:
    rows = (
        await session.execute(
            select(EvalCase).where(EvalCase.eval_set_id == eval_set_id).order_by(EvalCase.id)
        )
    ).scalars().all()
    return [EvalCaseOut.model_validate(r) for r in rows]


@router.get("/eval-sets/{eval_set_id}", response_model=EvalSetDetailOut)
async def get_eval_set(
    eval_set_id: uuid.UUID,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    es = await session.get(EvalSet, eval_set_id)
    if es is None:
        raise HTTPException(404, "评测集不存在")
    cases = await _load_cases(session, eval_set_id)
    return EvalSetDetailOut(**EvalSetOut.model_validate(es).model_dump(), cases=cases)


@router.delete("/eval-sets/{eval_set_id}", status_code=204)
async def delete_eval_set(
    eval_set_id: uuid.UUID,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    es = await session.get(EvalSet, eval_set_id)
    if es is None:
        raise HTTPException(404, "评测集不存在")
    await session.delete(es)
    await session.commit()


@router.post("/eval-sets/{eval_set_id}/run", response_model=EvalRunOut, status_code=201)
async def run_eval_set(
    eval_set_id: uuid.UUID,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    es = await session.get(EvalSet, eval_set_id)
    if es is None:
        raise HTTPException(404, "评测集不存在")
    case_count = len(
        (
            await session.execute(
                select(EvalCase.id).where(EvalCase.eval_set_id == eval_set_id)
            )
        ).all()
    )
    if case_count == 0:
        raise HTTPException(400, "评测集为空")

    run = EvalRun(eval_set_id=eval_set_id, total=case_count)
    session.add(run)
    await session.commit()
    await session.refresh(run)

    # 派发：优先 ARQ，失败回退进程内
    dispatched = False
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        from app.core.config import get_settings

        pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        try:
            await pool.enqueue_job("task_run_eval", str(run.id))
            dispatched = True
        finally:
            await pool.aclose()
    except Exception as e:  # noqa: BLE001
        logger.info("ARQ unavailable (%s), eval runs inline", e)
    if not dispatched:
        from app.services.evaluator import run_eval

        asyncio.create_task(run_eval(run.id))
    return run


@router.get("/eval-runs/{run_id}")
async def get_eval_run(
    run_id: uuid.UUID,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """运行状态 + 逐条结果（前端轮询）。"""
    run = await session.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(404, "运行不存在")
    results = (
        (
            await session.execute(
                select(EvalResult)
                .where(EvalResult.run_id == run_id)
                .order_by(EvalResult.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {
        **EvalRunOut.model_validate(run).model_dump(),
        "results": [
            {
                "question": r.question,
                "answer": r.answer,
                "retrieved_doc_names": r.retrieved_doc_names,
                "faithfulness": r.faithfulness,
                "relevance": r.relevance,
                "hit": r.hit,
                "elapsed_ms": r.elapsed_ms,
                "error": r.error,
            }
            for r in results
        ],
    }
