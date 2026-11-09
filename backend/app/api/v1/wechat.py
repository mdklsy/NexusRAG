"""微信公众号路由：绑定配置 CRUD + 消息回调。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.session import get_session
from app.models.app import App, Conversation
from app.models.platform import User
from app.models.wechat import WechatConfig
from app.schemas import WechatConfigCreate, WechatConfigOut, WechatConfigUpdate
from app.services.chat.orchestrator import run_chat
from app.services.wechat import (
    WECHAT_TIMEOUT_REPLY,
    build_text_reply,
    check_signature,
    parse_inbound,
    strip_markdown,
)

router = APIRouter(prefix="/wechat", tags=["wechat"])


# ---------- 配置管理（控制台） ----------


@router.get("/apps/{app_id}/config", response_model=WechatConfigOut | None)
async def get_config(
    app_id: uuid.UUID,
    _: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    row = (
        await session.execute(select(WechatConfig).where(WechatConfig.app_id == app_id))
    ).scalar_one_or_none()
    return row


@router.post("/apps/{app_id}/config", response_model=WechatConfigOut, status_code=201)
async def create_config(
    app_id: uuid.UUID,
    body: WechatConfigCreate,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    app = await session.get(App, app_id)
    if app is None:
        raise HTTPException(404, "应用不存在")
    exists = (
        await session.execute(select(WechatConfig).where(WechatConfig.app_id == app_id))
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "该应用已绑定公众号配置")
    cfg = WechatConfig(
        app_id=app_id,
        name=body.name,
        wx_app_id=body.wx_app_id,
        verify_token=body.verify_token,
        welcome_reply=body.welcome_reply,
    )
    session.add(cfg)
    await session.commit()
    await session.refresh(cfg)
    return cfg


@router.put("/configs/{config_id}", response_model=WechatConfigOut)
async def update_config(
    config_id: uuid.UUID,
    body: WechatConfigUpdate,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    cfg = await session.get(WechatConfig, config_id)
    if cfg is None:
        raise HTTPException(404, "配置不存在")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(cfg, field, value)
    await session.commit()
    await session.refresh(cfg)
    return cfg


@router.delete("/configs/{config_id}", status_code=204)
async def delete_config(
    config_id: uuid.UUID,
    _: User = Depends(require_role("editor")),
    session: AsyncSession = Depends(get_session),
):
    cfg = await session.get(WechatConfig, config_id)
    if cfg is None:
        raise HTTPException(404, "配置不存在")
    await session.delete(cfg)
    await session.commit()


# ---------- 微信服务器回调（匿名，签名校验） ----------


async def _load_config(session: AsyncSession, config_id: uuid.UUID) -> WechatConfig | None:
    cfg = await session.get(WechatConfig, config_id)
    if cfg is None or not cfg.enabled:
        return None
    return cfg


@router.get("/configs/{config_id}/callback")
async def verify(
    config_id: uuid.UUID,
    msg_signature: str = "",
    signature: str = "",
    timestamp: str = "",
    nonce: str = "",
    echostr: str = "",
    session: AsyncSession = Depends(get_session),
):
    """公众号后台「服务器配置」启用校验。"""
    cfg = await _load_config(session, config_id)
    if cfg is None:
        raise HTTPException(404, "配置不存在或已停用")
    sig = msg_signature or signature
    if check_signature(cfg.verify_token, sig, timestamp, nonce):
        return PlainTextResponse(echostr)
    return PlainTextResponse("invalid signature", status_code=403)


@router.post("/configs/{config_id}/callback")
async def callback(
    config_id: uuid.UUID,
    request: Request,
    signature: str = "",
    timestamp: str = "",
    nonce: str = "",
    session: AsyncSession = Depends(get_session),
):
    """接收粉丝消息 → 走应用对话编排 → 被动回复 XML。

    公众号要求 15s 内响应；orchestrator 全流程（意图/检索/工具/生成）尽力在此完成，
    异常时回复兜底话术避免微信重试风暴。
    """
    cfg = await _load_config(session, config_id)
    if cfg is None:
        return PlainTextResponse("not found", status_code=404)
    if not check_signature(cfg.verify_token, signature, timestamp, nonce):
        return PlainTextResponse("invalid signature", status_code=403)

    xml_text = (await request.body()).decode("utf-8", errors="ignore")
    msg = parse_inbound(xml_text)
    if msg is None or msg.msg_type != "text" or not msg.content:
        return PlainTextResponse("success")

    app = await session.get(App, cfg.app_id)
    if app is None or not app.is_active:
        return PlainTextResponse(
            build_text_reply(msg.to_user, msg.from_user, "服务暂不可用")
        )

    # 每个粉丝一个会话（title 标记来源；run_chat 只在标题为「新对话」时改写标题）
    conv = (
        (
            await session.execute(
                select(Conversation)
                .where(
                    Conversation.app_id == app.id,
                    Conversation.title == f"wx:{msg.from_user}",
                )
                .order_by(Conversation.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if conv is None:
        conv = Conversation(app_id=app.id, title=f"wx:{msg.from_user}")
        session.add(conv)
        await session.commit()
        await session.refresh(conv)

    answer_parts: list[str] = []
    try:
        async for event in run_chat(session, app, conv.id, msg.content, []):
            if event["type"] == "delta":
                answer_parts.append(event["content"])
    except Exception:  # noqa: BLE001
        answer_parts = [WECHAT_TIMEOUT_REPLY]
    answer = strip_markdown("".join(answer_parts)) or WECHAT_TIMEOUT_REPLY
    return PlainTextResponse(
        build_text_reply(msg.to_user, msg.from_user, answer),
        media_type="application/xml",
    )
