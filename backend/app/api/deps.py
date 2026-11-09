"""认证与通用依赖。"""

import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token, hash_api_key
from app.db.session import get_session
from app.models.app import App
from app.models.platform import ApiKey, User
from app.models.platform import User


async def get_current_user(
    authorization: str = Header(default=""),
    session: AsyncSession = Depends(get_session),
) -> User:
    """JWT 认证（控制台用户）。"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少 Bearer token")
    payload = decode_token(authorization[7:])
    if not payload or "sub" not in payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token 无效或已过期")
    user = await session.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return user


async def get_app_by_api_key(
    authorization: str = Header(default=""),
    session: AsyncSession = Depends(get_session),
) -> App:
    """API Key 认证（开放接口）。key 格式 nx-xxx，库中只存 sha256。"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少 API Key")
    raw = authorization[7:]
    key_hash = hash_api_key(raw)
    row = (
        await session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API Key 无效")
    app = await session.get(App, row.app_id)
    if app is None or not app.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "应用不可用")
    return app
