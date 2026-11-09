"""检索调试路由：给定 query 直观查看向量命中与 KG 子图召回。"""


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.models.app import App, AppKnowledgeBase
from app.models.kb import KnowledgeBase
from app.models.platform import User
from app.schemas import CitationOut, RetrievalIn, RetrievalOut
from app.services.retrieval import retrieve

router = APIRouter(prefix="/retrievals", tags=["retrieval"])


@router.post("", response_model=RetrievalOut)
async def run_retrieval(
    body: RetrievalIn,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    # 确定目标知识库：显式 kb_ids 优先，否则取 app 绑定
    if body.kb_ids:
        kbs = (
            (
                await session.execute(
                    select(KnowledgeBase).where(KnowledgeBase.id.in_(body.kb_ids))
                )
            )
            .scalars()
            .all()
        )
    elif body.app_id:
        kbs = (
            (
                await session.execute(
                    select(KnowledgeBase)
                    .join(AppKnowledgeBase, AppKnowledgeBase.kb_id == KnowledgeBase.id)
                    .where(AppKnowledgeBase.app_id == body.app_id)
                )
            )
            .scalars()
            .all()
        )
    else:
        raise HTTPException(400, "kb_ids 与 app_id 至少提供一个")
    if not kbs:
        raise HTTPException(404, "未找到可用的知识库")

    app_config: dict = {}
    if body.app_id:
        app = await session.get(App, body.app_id)
        app_config = (app.retrieval_config if app else {}) or {}
    config = dict(app_config)
    if body.top_k is not None:
        config["top_k"] = body.top_k
    if body.use_kg is not None:
        config["use_kg"] = body.use_kg

    result = await retrieve(session, list(kbs), body.query, config)
    citations = [
        CitationOut(**c) for c in result.build_context()[1]
    ]
    context, _ = result.build_context()
    return RetrievalOut(
        chunks=citations,
        graph_facts=result.graph_facts,
        graph_entities=[
            {"id": str(e.id), "name": e.name, "type": e.type, "mentions": e.mention_count}
            for e in result.graph_entities
        ],
        context=context,
    )
