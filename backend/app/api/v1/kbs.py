"""知识库路由。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.core.config import get_settings
from app.db.session import get_session
from app.models.kb import KnowledgeBase
from app.models.platform import User
from app.schemas import KBCreate, KBOut, KBUpdate
from app.services.ingestion.vectorstore import get_vector_store
from app.services.kg.graph_store import get_graph_store

router = APIRouter(prefix="/kbs", tags=["knowledge-bases"])


@router.get("", response_model=list[KBOut])
async def list_kbs(
    _: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    stmt = select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc())
    return (await session.execute(stmt)).scalars().all()


@router.post("", response_model=KBOut, status_code=201)
async def create_kb(
    body: KBCreate,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    s = get_settings()
    kb = KnowledgeBase(
        name=body.name,
        description=body.description,
        embedding_model=s.embedding_model,
        embedding_dim=s.embedding_dim,
        chunk_config=body.chunk_config,
    )
    session.add(kb)
    await session.commit()
    await session.refresh(kb)
    return kb


@router.get("/{kb_id}", response_model=KBOut)
async def get_kb(
    kb_id: uuid.UUID,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    return kb


@router.put("/{kb_id}", response_model=KBOut)
async def update_kb(
    kb_id: uuid.UUID,
    body: KBUpdate,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(kb, field, value)
    await session.commit()
    await session.refresh(kb)
    return kb


@router.delete("/{kb_id}", status_code=204)
async def delete_kb(
    kb_id: uuid.UUID,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    await session.delete(kb)
    await session.commit()
    # 图数据与向量集合同步清理（尽力而为）
    await get_graph_store().delete_by_kb(kb_id)
    await get_vector_store().delete_collection(kb_id)


@router.get("/{kb_id}/kg-stats")
async def kg_stats(
    kb_id: uuid.UUID,
    _: User = Depends(get_current_user),
):
    return await get_graph_store().kb_stats(kb_id)
