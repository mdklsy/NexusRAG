"""用户管理（仅 admin）。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.security import hash_password
from app.db.session import get_session
from app.models.platform import User
from app.schemas import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
async def list_users(
    _: User = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    return (
        (await session.execute(select(User).order_by(User.created_at))).scalars().all()
    )


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    _: User = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    exists = await session.execute(select(User).where(User.email == body.email))
    if exists.scalar_one_or_none():
        raise HTTPException(409, "邮箱已存在")
    if body.role not in ("admin", "editor", "viewer"):
        raise HTTPException(400, "role 仅支持 admin | editor | viewer")
    user = User(
        email=body.email,
        name=body.name,
        role=body.role,
        hashed_password=hash_password(body.password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    actor: User = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    data = body.model_dump(exclude_unset=True)

    # 防止把最后一个 admin 降级/删除
    if data.get("role") and data["role"] != "admin" and user.role == "admin":
        admins = await session.scalar(
            select(func.count()).select_from(User).where(User.role == "admin")
        )
        if (admins or 0) <= 1:
            raise HTTPException(400, "不能降级最后一个管理员")

    if data.get("password"):
        user.hashed_password = hash_password(data.pop("password"))
    if data.get("role"):
        if data["role"] not in ("admin", "editor", "viewer"):
            raise HTTPException(400, "role 仅支持 admin | editor | viewer")
        user.role = data["role"]
    if data.get("name") is not None:
        user.name = data["name"]
    await session.commit()
    await session.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    actor: User = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    if user_id == actor.id:
        raise HTTPException(400, "不能删除自己")
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    if user.role == "admin":
        admins = await session.scalar(
            select(func.count()).select_from(User).where(User.role == "admin")
        )
        if (admins or 0) <= 1:
            raise HTTPException(400, "不能删除最后一个管理员")
    await session.delete(user)
    await session.commit()
