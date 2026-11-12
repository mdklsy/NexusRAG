"""业务工具（连接器）路由。"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.session import get_session
from app.models.app import Tool
from app.models.platform import User
from app.schemas import ToolCreate, ToolOut, ToolUpdate
from app.services.tools import introspect_schema

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/apps/{app_id}/tools", tags=["tools"])


def _apply_introspection(tool: Tool) -> None:
    """自动拉取表结构写入 config.schema。失败不阻塞保存（NL2SQL 仍可用纯描述模式）。"""
    dsn = (tool.config or {}).get("dsn")
    if not dsn:
        return
    try:
        tool.config = {**(tool.config or {}), "schema": introspect_schema(dsn)}
    except Exception as e:  # noqa: BLE001 连不上/驱动缺——保存继续，可稍后手动刷新
        logger.warning("sql_db 内省失败（%s）: %s", tool.name, e)


@router.get("", response_model=list[ToolOut])
async def list_tools(
    app_id: uuid.UUID,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return (
        (
            await session.execute(
                select(Tool).where(Tool.app_id == app_id).order_by(Tool.created_at)
            )
        )
        .scalars()
        .all()
    )


@router.post("", response_model=ToolOut, status_code=201)
async def create_tool(
    app_id: uuid.UUID,
    body: ToolCreate,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    # config 基本校验
    if body.type == "http_api" and not (body.config or {}).get("url"):
        raise HTTPException(400, "http_api 工具必须在 config.url 提供接口地址")
    if body.type == "sql_db" and not (body.config or {}).get("dsn"):
        raise HTTPException(400, "sql_db 工具必须在 config.dsn 提供数据库连接串")
    tool = Tool(app_id=app_id, **body.model_dump())
    if tool.type == "sql_db":
        await asyncio.to_thread(_apply_introspection, tool)  # 同步连库，别卡事件循环
    session.add(tool)
    try:
        await session.commit()
    except Exception as e:  # noqa: BLE001 唯一约束冲突
        await session.rollback()
        raise HTTPException(409, f"创建失败（name 可能重复）: {e}") from e
    await session.refresh(tool)
    return tool


@router.put("/{tool_id}", response_model=ToolOut)
async def update_tool(
    app_id: uuid.UUID,
    tool_id: uuid.UUID,
    body: ToolUpdate,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    tool = await session.get(Tool, tool_id)
    if tool is None or tool.app_id != app_id:
        raise HTTPException(404, "工具不存在")
    data = body.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(tool, field, value)
    # dsn 变更 → 表结构自动重拉
    if tool.type == "sql_db" and "config" in data and (tool.config or {}).get("dsn"):
        await asyncio.to_thread(_apply_introspection, tool)
    await session.commit()
    await session.refresh(tool)
    return tool


@router.post("/{tool_id}/introspect", response_model=ToolOut)
async def introspect_tool(
    app_id: uuid.UUID,
    tool_id: uuid.UUID,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    """手动刷新 sql_db 工具的表结构（表结构随业务演进后重新内省）。"""
    tool = await session.get(Tool, tool_id)
    if tool is None or tool.app_id != app_id:
        raise HTTPException(404, "工具不存在")
    if tool.type != "sql_db":
        raise HTTPException(400, "仅 sql_db 工具支持表结构内省")
    try:
        schema = await asyncio.to_thread(introspect_schema, tool.config["dsn"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"表结构拉取失败（检查连接串与网络）: {e}") from e
    tool.config = {**(tool.config or {}), "schema": schema}
    await session.commit()
    await session.refresh(tool)
    return tool


@router.delete("/{tool_id}", status_code=204)
async def delete_tool(
    app_id: uuid.UUID,
    tool_id: uuid.UUID,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    await session.execute(
        delete(Tool).where(Tool.id == tool_id, Tool.app_id == app_id)
    )
    await session.commit()
