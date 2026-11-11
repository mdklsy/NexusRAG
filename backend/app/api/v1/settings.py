"""全局服务配置路由：对话模型 / 向量模型 / 重排服务的页面级管理（仅 admin）。

配置存 system_settings 表（api_key AES 加密），立即生效，无需重启；
未在页面设置的项目回退 .env。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core import runtime_settings
from app.db.session import get_session
from app.models.platform import User

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingUpdate(BaseModel):
    api_base: str | None = None
    model: str | None = None
    api_key: str = ""  # 空 = 保持不变


@router.get("")
async def get_settings_page(
    _: User = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    _ = session  # 依赖注入保持会话生命周期一致
    await runtime_settings.ensure_fresh()
    return {cat: runtime_settings.masked_status(cat) for cat in runtime_settings.CATEGORIES}


@router.put("/{category}")
async def update_settings(
    category: str,
    body: SettingUpdate,
    _: User = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_session),
):
    _ = session
    if category not in runtime_settings.CATEGORIES:
        raise HTTPException(404, f"未知配置类别 {category}")
    await runtime_settings.save_category(
        category, body.model_dump()
    )
    await runtime_settings.refresh()
    return runtime_settings.masked_status(category)

