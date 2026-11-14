"""洞察层：审核数据飞轮（决策挖掘/驳回转评测/质量统计）+ 知识缺口发现。

飞轮（形态①的延伸）：审核不是终点——改写对挖出提示词规则，驳回问题转评测用例，
统计进看板；让"人审"变成系统进化的原料。

缺口（知识治理）：hit=False 的问答对是知识库缺什么的直接证据，LLM 聚类成主题，
可起草候选答案供人工参考。
"""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app import App, Conversation, KnowledgeGap, Message, ReviewDecision

MINE_RULES_PROMPT = """你是提示词工程师。下面是 AI 客服回答被人工改写的对照记录（原文 → 改写稿）。
请提炼可复用的回答写作规则（≤8 条），每条规则要具体可执行（如"金额一律保留两位小数""先给结论再给解释"），不要空话。

{pairs}

只输出 JSON：{{"rules": [{{"rule": "规则内容", "examples": 出现次数}}]}}"""

GAP_CLUSTER_PROMPT = """你是知识库运营分析师。以下是智能客服中「检索未命中」的用户问题列表。
请把它们聚类成知识缺口主题（≤10 个），每个主题给一个简短名称，并汇总属于它的问题。

{questions}

只输出 JSON：{{"themes": [{{"theme": "主题名", "questions": ["属于该主题的问题"]}}]}}"""

GAP_DRAFT_PROMPT = """你是知识库运营。智能客服中有一类问题反复出现且知识库检索不到（知识缺口），主题：
「{theme}」

相关用户问题：
{questions}

请根据你的通用知识起草一份候选回答，供运营审核后决定是否补充进知识库。要求：
- 开头注明「（草稿，待运营确认后补充进知识库）」
- 结构清晰、可直接作为客服话术
- 如实说明这是基于通用知识的草稿，具体数字/政策以官方文档为准"""


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


# ---------- 审核数据飞轮 ----------


async def review_stats(session: AsyncSession, app_id, days: int = 30) -> dict:
    """审核动作统计 + 回答质量概览（改写率、无答案率）。"""
    since = _since(days)
    action_rows = (
        await session.execute(
            select(ReviewDecision.action, func.count())
            .where(ReviewDecision.app_id == app_id, ReviewDecision.decided_at >= since)
            .group_by(ReviewDecision.action)
        )
    ).all()
    counts = {action: n for action, n in action_rows}
    approved = counts.get("approve", 0)
    replaced = counts.get("replace", 0)
    rejected = counts.get("reject", 0)
    decided = approved + replaced + rejected

    question_q = (
        select(func.count())
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.app_id == app_id,
            Message.role == "user",
            Message.created_at >= since,
        )
    )
    total_questions = (await session.execute(question_q)).scalar_one()
    no_hit = (
        await session.execute(
            select(func.count())
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.app_id == app_id,
                Message.role == "assistant",
                Message.hit.is_(False),
                Message.created_at >= since,
            )
        )
    ).scalar_one()
    return {
        "days": days,
        "approved": approved,
        "replaced": replaced,
        "rejected": rejected,
        "decided": decided,
        "replace_rate": round(replaced / decided, 4) if decided else 0.0,
        "total_questions": total_questions,
        "no_hit": no_hit,
        "no_hit_rate": round(no_hit / total_questions, 4) if total_questions else 0.0,
    }


async def _replace_pairs(session: AsyncSession, app_id, limit: int = 30) -> list[tuple[str, str]]:
    rows = (
        await session.execute(
            select(ReviewDecision.content_before, ReviewDecision.content_after)
            .where(
                ReviewDecision.app_id == app_id,
                ReviewDecision.action == "replace",
                ReviewDecision.content_before.is_not(None),
            )
            .order_by(ReviewDecision.decided_at.desc())
            .limit(limit)
        )
    ).all()
    return [(b, a) for b, a in rows if b and a]


async def mine_rules(session: AsyncSession, app: App) -> list[dict]:
    """从改写对照记录挖掘提示词规则（LLM 按需调用，不落库）。"""
    from app.services.llm import get_llm_client

    pairs = await _replace_pairs(session, app.id)
    if not pairs:
        return []
    llm = get_llm_client(app.llm_config)
    pair_text = "\n\n".join(
        f"【原文】\n{b[:800]}\n\n【改写稿】\n{a[:800]}" for b, a in pairs
    )
    raw = await llm.chat_json(
        [{"role": "user", "content": MINE_RULES_PROMPT.format(pairs=pair_text)}],
        temperature=0.2,
        max_tokens=1500,
    )
    try:
        data = json.loads(raw)
        rules = data.get("rules") if isinstance(data, dict) else None
        if not isinstance(rules, list):
            raise ValueError("rules 不是列表")
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        raise ValueError(f"规则挖掘结果解析失败: {e}") from e
    return [
        {"rule": str(r.get("rule", "")).strip(), "examples": int(r.get("examples") or 0)}
        for r in rules
        if isinstance(r, dict) and str(r.get("rule", "")).strip()
    ][:8]


async def rejected_questions(
    session: AsyncSession, app_id, limit: int = 50
) -> list[dict]:
    """被驳回的回答 + 其对应的用户提问（评测用例原料）。"""
    rows = (
        await session.execute(
            select(Message, Conversation.id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.app_id == app_id,
                Message.role == "assistant",
                Message.review_status == "rejected",
            )
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    ).all()
    out = []
    for msg, _conv_id in rows:
        prev = (
            await session.execute(
                select(Message.content)
                .where(
                    Message.conversation_id == msg.conversation_id,
                    Message.role == "user",
                    Message.created_at <= msg.created_at,
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        out.append(
            {
                "message_id": str(msg.id),
                "question": prev or "（未找到对应提问）",
                "rejected_answer": msg.content,
                "created_at": msg.created_at,
            }
        )
    return out


async def to_eval_cases(session: AsyncSession, app: App, message_ids: list) -> dict:
    """驳回问题一键转评测集用例（回归防线）。"""
    from app.models.eval import EvalCase, EvalSet

    sets = (
        await session.execute(
            select(EvalSet).where(
                EvalSet.app_id == app.id, EvalSet.name == "审核驳回回归"
            )
        )
    ).scalars().all()
    rejected = {item["message_id"]: item for item in await rejected_questions(session, app.id, limit=500)}
    created = 0
    eval_set = sets[0] if sets else None
    new_pairs = []
    for mid in message_ids:
        item = rejected.get(str(mid))
        if item is None or item["question"].startswith("（未找到"):
            continue
        new_pairs.append(item["question"][:2000])
        created += 1
    if created:
        if eval_set is None:
            eval_set = EvalSet(app_id=app.id, name="审核驳回回归",
                               description="人机协作审核驳回的问题自动回流")
            session.add(eval_set)
            await session.flush()
        for q in new_pairs:
            session.add(EvalCase(eval_set_id=eval_set.id, question=q,
                                 expected_points="", expected_doc_name=""))
        await session.commit()
    else:
        eval_set = eval_set or EvalSet(app_id=app.id, name="审核驳回回归")
    return {"eval_set_id": str(eval_set.id), "created": created}


# ---------- 知识缺口发现 ----------


async def _unanswered_pairs(session: AsyncSession, app_id, days: int, limit: int = 300):
    """hit=False 的 assistant 消息与其前驱 user 提问。"""
    rows = (
        await session.execute(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.app_id == app_id,
                Message.role == "assistant",
                Message.hit.is_(False),
                Message.created_at >= _since(days),
            )
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    pairs = []
    for msg in rows:
        prev = (
            await session.execute(
                select(Message.content)
                .where(
                    Message.conversation_id == msg.conversation_id,
                    Message.role == "user",
                    Message.created_at <= msg.created_at,
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if prev:
            pairs.append(prev)
    return pairs


async def analyze_gaps(session: AsyncSession, app: App, days: int = 30) -> list[dict]:
    """聚类无答案问题成缺口主题；重建 open 状态的 gaps（resolved/drafted 保留）。"""
    from app.services.llm import get_llm_client

    questions = await _unanswered_pairs(session, app.id, days)
    if not questions:
        return []

    llm = get_llm_client(app.llm_config)
    q_text = "\n".join(f"- {q[:300]}" for q in questions[:300])
    raw = await llm.chat_json(
        [{"role": "user", "content": GAP_CLUSTER_PROMPT.format(questions=q_text)}],
        temperature=0.2,
        max_tokens=2000,
    )
    try:
        data = json.loads(raw)
        themes = data.get("themes") if isinstance(data, dict) else None
        if not isinstance(themes, list):
            raise ValueError("themes 不是列表")
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        raise ValueError(f"缺口聚类结果解析失败: {e}") from e

    # 清掉旧的 open，重建（resolved/drafted 不动）
    old_opens = (
        await session.execute(
            select(KnowledgeGap).where(
                KnowledgeGap.app_id == app.id, KnowledgeGap.status == "open"
            )
        )
    ).scalars().all()
    for g in old_opens:
        await session.delete(g)

    seen = set()
    out = []
    for t in themes:
        if not isinstance(t, dict):
            continue
        theme = str(t.get("theme", "")).strip()[:200]
        qs = [str(q) for q in (t.get("questions") or []) if str(q).strip()]
        if not theme or theme in seen:
            continue
        seen.add(theme)
        gap = KnowledgeGap(
            app_id=app.id,
            theme=theme,
            representative_questions=qs[:10],
            occurrences=len(qs) or 1,
            status="open",
        )
        session.add(gap)
        out.append(gap)
    await session.commit()
    for g in out:
        await session.refresh(g)
    return out


async def draft_gap(session: AsyncSession, app: App, gap: KnowledgeGap) -> KnowledgeGap:
    """为缺口主题起草候选答案（标记草稿属性，供运营参考）。"""
    from app.services.llm import get_llm_client

    llm = get_llm_client(app.llm_config)
    q_text = "\n".join(f"- {q[:300]}" for q in gap.representative_questions[:10])
    answer, _usage = await llm.chat(
        [{"role": "user", "content": GAP_DRAFT_PROMPT.format(theme=gap.theme, questions=q_text)}],
        temperature=0.4,
        max_tokens=1500,
    )
    gap.draft_answer = answer
    gap.status = "drafted"
    await session.commit()
    await session.refresh(gap)
    return gap


def serialize_gap(gap: KnowledgeGap) -> dict:
    return {
        "id": str(gap.id),
        "theme": gap.theme,
        "representative_questions": gap.representative_questions or [],
        "occurrences": gap.occurrences,
        "status": gap.status,
        "draft_answer": gap.draft_answer,
        "updated_at": gap.updated_at,
    }
