"""应用路由：CRUD、知识库绑定、API Key 管理。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.security import generate_api_key
from app.db.session import get_session
from app.models.app import App, AppKnowledgeBase
from app.models.platform import ApiKey, User
from app.schemas import ApiKeyCreated, ApiKeyOut, AppCreate, AppDetailOut, AppOut, AppUpdate

router = APIRouter(prefix="/apps", tags=["apps"])


async def _load_kb_ids(session: AsyncSession, app_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.execute(
        select(AppKnowledgeBase.kb_id).where(AppKnowledgeBase.app_id == app_id)
    )
    return [r[0] for r in rows.all()]


async def _set_kb_bindings(session: AsyncSession, app_id: uuid.UUID, kb_ids: list[uuid.UUID]):
    await session.execute(
        delete(AppKnowledgeBase).where(AppKnowledgeBase.app_id == app_id)
    )
    for kb_id in kb_ids:
        session.add(AppKnowledgeBase(app_id=app_id, kb_id=kb_id))


@router.get("", response_model=list[AppOut])
async def list_apps(
    _: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    return (
        (await session.execute(select(App).order_by(App.created_at.desc()))).scalars().all()
    )


@router.post("", response_model=AppDetailOut, status_code=201)
async def create_app(
    body: AppCreate,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    app = App(
        name=body.name,
        description=body.description,
        icon=body.icon,
        system_prompt=body.system_prompt,
        llm_config=body.llm_config,
        retrieval_config=body.retrieval_config,
        widget_config=body.widget_config,
    )
    session.add(app)
    await session.flush()
    await _set_kb_bindings(session, app.id, body.kb_ids)
    await session.commit()
    await session.refresh(app)
    return AppDetailOut(**AppOut.model_validate(app).model_dump(), kb_ids=body.kb_ids)


@router.get("/{app_id}", response_model=AppDetailOut)
async def get_app(
    app_id: uuid.UUID,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    app = await session.get(App, app_id)
    if app is None:
        raise HTTPException(404, "应用不存在")
    kb_ids = await _load_kb_ids(session, app_id)
    return AppDetailOut(**AppOut.model_validate(app).model_dump(), kb_ids=kb_ids)


@router.put("/{app_id}", response_model=AppDetailOut)
async def update_app(
    app_id: uuid.UUID,
    body: AppUpdate,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    app = await session.get(App, app_id)
    if app is None:
        raise HTTPException(404, "应用不存在")
    data = body.model_dump(exclude_unset=True)
    kb_ids = data.pop("kb_ids", None)
    for field, value in data.items():
        setattr(app, field, value)
    if kb_ids is not None:
        await _set_kb_bindings(session, app_id, kb_ids)
    await session.commit()
    await session.refresh(app)
    final_kb_ids = await _load_kb_ids(session, app_id)
    return AppDetailOut(**AppOut.model_validate(app).model_dump(), kb_ids=final_kb_ids)


@router.delete("/{app_id}", status_code=204)
async def delete_app(
    app_id: uuid.UUID,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    app = await session.get(App, app_id)
    if app is None:
        raise HTTPException(404, "应用不存在")
    await session.delete(app)  # API Key/绑定/对话级联删除
    await session.commit()


# ---------- API Keys ----------


@router.post("/{app_id}/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    app_id: uuid.UUID,
    name: str = "default",
    scope: str = "full",  # full | chat（挂件用）
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    app = await session.get(App, app_id)
    if app is None:
        raise HTTPException(404, "应用不存在")
    if scope not in ("full", "chat"):
        raise HTTPException(400, "scope 仅支持 full | chat")
    raw, key_hash = generate_api_key()
    key = ApiKey(app_id=app_id, name=name, key_hash=key_hash, scope=scope)
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return ApiKeyCreated(key=raw, info=ApiKeyOut.model_validate(key))


@router.get("/{app_id}/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(
    app_id: uuid.UUID,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return (
        (
            await session.execute(
                select(ApiKey).where(ApiKey.app_id == app_id).order_by(ApiKey.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


@router.delete("/{app_id}/api-keys/{key_id}", status_code=204)
async def delete_api_key(
    app_id: uuid.UUID,
    key_id: uuid.UUID,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await session.execute(
        delete(ApiKey).where(ApiKey.id == key_id, ApiKey.app_id == app_id)
    )
    await session.commit()
