"""人机协作：工具调用审批门 + 答案人工审核。

审批门（形态①）：工具配置 require_approval=true 时，代理调用该工具不真执行，
而是落一张审批单；人在控制台通过/拒绝后，系统续跑同一会话向用户交代结果。

答案审核（形态④）：应用 retrieval_config.review_mode="on" 时，回答不再直接
流给用户，而是缓冲落库为 pending 状态，人在控制台通过（可改写）后才对终端
用户可见。

信息补齐（形态②）：纯提示词规则（缺参先问、不编造），见 orchestrator。
"""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app import App, Message, PendingAction, Tool


class ApprovalGate:
    """工具审批闸。挂在编排器的工具执行收口处，单代理/多代理共用。

    intercept 返回 None = 放行（正常执行）；返回 (action_id, 文本) = 拦截，
    文本回喂 LLM 让它告知用户"已提交人工审批"。
    """

    def __init__(self, session: AsyncSession, app_id, conversation_id, ctx: dict | None):
        self.session = session
        self.app_id = app_id
        self.conversation_id = conversation_id
        self.ctx = ctx or {}

    async def intercept(self, tool: Tool, args: dict):
        if not (tool.config or {}).get("require_approval"):
            return None
        action = PendingAction(
            app_id=self.app_id,
            conversation_id=self.conversation_id,
            tool_name=tool.name,
            args=args,
            ctx_snapshot=self.ctx,
        )
        self.session.add(action)
        await self.session.flush()
        return str(action.id)


def _fmt_args(args: dict) -> str:
    try:
        return json.dumps(args, ensure_ascii=False)[:500]
    except (TypeError, ValueError):
        return str(args)[:500]


async def decide_action(
    session: AsyncSession, app: App, action_id, approved: bool, decided_by
) -> PendingAction:
    """审批决策：改状态；通过则真执行工具（带审批时的上下文快照）。"""
    from app.services.tools import ToolError, execute_tool

    action = await session.get(PendingAction, action_id)
    if action is None or action.app_id != app.id:
        raise LookupError("审批单不存在")
    if action.status != "pending":
        raise ValueError(f"该审批单已处理（{action.status}）")

    tool = (
        (
            await session.execute(
                select(Tool).where(Tool.app_id == app.id, Tool.name == action.tool_name)
            )
        )
        .scalars()
        .first()
    )
    result_text = ""
    if approved:
        if tool is None:
            result_text = f"执行失败：工具 {action.tool_name} 已不存在"
        else:
            try:
                result_text = await _run_tool_in_thread(
                    execute_tool, tool, action.args, action.ctx_snapshot
                )
            except ToolError as e:
                result_text = f"工具执行失败: {e}"
            except Exception as e:  # noqa: BLE001
                result_text = f"工具执行异常: {type(e).__name__}: {e}"
    else:
        result_text = "人工审批拒绝，未执行"

    action.status = "approved" if approved else "rejected"
    action.result_text = result_text
    action.decided_by = decided_by
    action.decided_at = action.decided_at or _now()
    await session.commit()
    return action


async def _run_tool_in_thread(fn, *args):
    """execute_tool 是同步函数（内网 HTTP/SQL），放线程池避免卡事件循环。"""
    import asyncio

    return await asyncio.to_thread(fn, *args)


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


async def continue_after_decision(
    session: AsyncSession, app: App, action: PendingAction
) -> Message:
    """审批决策后续跑：把执行结果交给模型生成对用户的交代，落为 assistant 消息。"""
    from app.services.llm import get_llm_client

    approved = action.status == "approved"
    llm = get_llm_client(app.llm_config)
    system = (
        (app.system_prompt or "")
        + "\n\n你是业务助手。当前任务是向用户交代一个工具调用的审批与执行结果："
        + "简洁说明审批情况与执行结果，如实转述失败/拒绝原因，不编造数据。"
    )
    verdict = "已通过" if approved else "已拒绝（未执行）"
    user = (
        f"你在上一轮发起的工具调用「{action.tool_name}」（参数：{_fmt_args(action.args)}）"
        f"人工审批{verdict}。\n执行结果：\n{action.result_text or '（无返回）'}\n"
        "请据此向用户交代结果与后续建议。"
    )
    answer, usage = await llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.3,
        max_tokens=1024,
    )
    msg = Message(
        conversation_id=action.conversation_id,
        role="assistant",
        content=f"🔔 审批结果（工具「{action.tool_name}」{verdict}）\n\n{answer}",
        tokens_in=usage.get("tokens_in", 0),
        tokens_out=usage.get("tokens_out", 0),
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return msg


async def list_actions(
    session: AsyncSession, app_id=None, status: str | None = None, limit: int = 200
):
    """审批单列表；app_id=None 时跨应用（全局人机协作页）。"""
    stmt = (
        select(PendingAction, App.name)
        .join(App, App.id == PendingAction.app_id)
        .order_by(PendingAction.created_at.desc())
        .limit(limit)
    )
    if app_id:
        stmt = stmt.where(PendingAction.app_id == app_id)
    if status:
        stmt = stmt.where(PendingAction.status == status)
    return [{"action": a, "app_name": n} for a, n in (await session.execute(stmt)).all()]


async def list_pending_reviews(session: AsyncSession, app_id=None, limit: int = 200):
    """待人工审核的回答（review_status=pending 的 assistant 消息）；app_id=None 跨应用。"""
    from app.models.app import Conversation

    stmt = (
        select(Message, Conversation.title, App.name, Conversation.app_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(App, App.id == Conversation.app_id)
        .where(
            Message.role == "assistant",
            Message.review_status == "pending",
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    if app_id:
        stmt = stmt.where(Conversation.app_id == app_id)
    rows = (await session.execute(stmt)).all()
    return [
        {"message": m, "conversation_title": t, "app_name": n, "app_id": aid}
        for m, t, n, aid in rows
    ]


async def count_pending(session: AsyncSession) -> dict:
    """全局待办数（侧边栏角标）：待审批工具调用 + 待人工审核回答。"""
    from sqlalchemy import func

    approvals = (
        await session.execute(
            select(func.count()).select_from(PendingAction).where(PendingAction.status == "pending")
        )
    ).scalar_one()
    from app.models.app import Conversation

    reviews = (
        await session.execute(
            select(func.count())
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.role == "assistant", Message.review_status == "pending")
        )
    ).scalar_one()
    return {"approvals": approvals, "reviews": reviews}


async def decide_review(
    session: AsyncSession,
    msg: Message,
    action: str,
    content: str | None,
    *,
    app_id=None,
    editor_id=None,
):
    """答案审核决策：approve=放行原文；replace=改写后放行；reject=驳回（永不可见）。

    同时落 ReviewDecision 审计行（改写前的原文必须留存——它是规则挖掘的原料）。
    """
    from app.models.app import ReviewDecision

    if action == "approve":
        msg.review_status = "published"
    elif action == "replace":
        if not (content or "").strip():
            raise ValueError("改写内容不能为空")
        msg.review_status = "published"
    elif action == "reject":
        msg.review_status = "rejected"
    else:
        raise ValueError("action 仅支持 approve | replace | reject")
    content_before = msg.content if action in ("replace", "reject") else None
    if action == "replace":
        msg.content = content
    session.add(
        ReviewDecision(
            app_id=app_id,
            message_id=msg.id,
            action=action,
            editor_id=editor_id,
            content_before=content_before,
            content_after=content if action == "replace" else None,
        )
    )
    await session.commit()
    return msg
