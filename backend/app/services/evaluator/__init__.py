"""评测运行器：逐用例检索 → 生成 → LLM 打分（忠实度/相关性）→ 汇总。

Ragas 风格的轻量实现：不依赖 ragas 库，评分维度与思路一致。
"""

import json
import logging
import re
import time
import uuid

from sqlalchemy import select

from app.db.session import session_scope
from app.models.app import App
from app.models.eval import EvalCase, EvalResult, EvalRun, EvalSet
from app.services.llm import get_llm_client
from app.services.retrieval import get_app_knowledge_bases, retrieve

logger = logging.getLogger(__name__)

SCORE_PROMPT = """你是问答系统的质量评审员。根据以下信息给回答打两个维度的分（1-5 整数）：

1. faithfulness 忠实度：回答是否完全基于【参考资料】，无编造（5=完全忠实，1=大量编造）
2. relevance 相关性：是否切中【问题】并覆盖【期望要点】（5=完全切中，1=答非所问）

【问题】{question}
【期望要点】{points}
【参考资料】{context}
【回答】{answer}

输出 JSON：{{"faithfulness": 5, "relevance": 5}}，不要解释。"""


def parse_scores(raw: str) -> tuple[float | None, float | None]:
    text = re.sub(r"^```(json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None, None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None, None
    try:
        f = float(data.get("faithfulness"))
        r = float(data.get("relevance"))
        return (min(5.0, max(1.0, f)), min(5.0, max(1.0, r)))
    except (TypeError, ValueError):
        return None, None


def check_hit(expected_doc_name: str, retrieved_names: list[str]) -> bool | None:
    """期望文档是否在检索结果中（子串模糊匹配）。无期望则返回 None。"""
    if not expected_doc_name:
        return None
    exp = expected_doc_name.strip().lower()
    return any(exp in name.lower() for name in retrieved_names)


async def run_eval(run_id: uuid.UUID) -> None:
    from app.core import runtime_settings

    await runtime_settings.ensure_fresh()
    """执行整个评测运行。由 API 派发（ARQ 或 inline）。"""
    async with session_scope() as session:
        run = await session.get(EvalRun, run_id)
        if run is None:
            return
        run.status = "running"
        await session.commit()
        eval_set_id = run.eval_set_id

        cases = (
            (
                await session.execute(
                    select(EvalCase)
                    .where(EvalCase.eval_set_id == eval_set_id)
                    .order_by(EvalCase.id)
                )
            )
            .scalars()
            .all()
        )
        es = await session.get(EvalSet, eval_set_id)
        app = await session.get(App, es.app_id) if es else None
        if app is None:
            run.status = "failed"
            run.error = "应用不存在"
            await session.commit()
            return
        app_id = app.id
        run.total = len(cases)
        await session.commit()

    llm = get_llm_client(app.llm_config)
    f_scores: list[float] = []
    r_scores: list[float] = []
    hits: list[bool] = []
    errors = 0

    for case in cases:
        started = time.monotonic()
        answer, doc_names, faithfulness, relevance, hit, err = "", [], None, None, None, None
        try:
            async with session_scope() as session:
                app_row = await session.get(App, app_id)
                kbs = await get_app_knowledge_bases(session, app_id)
                result = await retrieve(
                    session, kbs, case.question, app_row.retrieval_config or {}
                )
                context, _ = result.build_context(max_chunks=6)
                doc_names = list(dict.fromkeys(c.document_name for c in result.chunks))
                hit = check_hit(case.expected_doc_name, doc_names)

            if result.chunks:
                answer, _ = await llm.chat(
                    [
                        {
                            "role": "system",
                            "content": "仅根据参考资料回答问题，资料不足时如实说明。",
                        },
                        {
                            "role": "user",
                            "content": f"【参考资料】\n{context}\n\n【问题】{case.question}",
                        },
                    ]
                )
            else:
                answer = "（未检索到相关资料）"

            raw = await llm.chat_json(
                [
                    {
                        "role": "user",
                        "content": SCORE_PROMPT.format(
                            question=case.question,
                            points=case.expected_points or "（未指定）",
                            context=context or "（无）",
                            answer=answer,
                        ),
                    }
                ],
                max_tokens=100,
            )
            faithfulness, relevance = parse_scores(raw)
        except Exception as e:  # noqa: BLE001 单条失败不中断整体
            err = f"{type(e).__name__}: {e}"
            errors += 1
            logger.warning("eval case failed: %s", err)

        elapsed = int((time.monotonic() - started) * 1000)
        if faithfulness is not None:
            f_scores.append(faithfulness)
        if relevance is not None:
            r_scores.append(relevance)
        if hit is not None:
            hits.append(hit)

        async with session_scope() as session:
            session.add(
                EvalResult(
                    run_id=run_id,
                    case_id=case.id,
                    question=case.question,
                    answer=answer[:4000],
                    retrieved_doc_names=doc_names,
                    faithfulness=faithfulness,
                    relevance=relevance,
                    hit=hit,
                    elapsed_ms=elapsed,
                    error=err,
                )
            )
            run = await session.get(EvalRun, run_id)
            run.done += 1
            await session.commit()

    async with session_scope() as session:
        run = await session.get(EvalRun, run_id)
        run.status = "completed"
        run.avg_faithfulness = sum(f_scores) / len(f_scores) if f_scores else None
        run.avg_relevance = sum(r_scores) / len(r_scores) if r_scores else None
        run.hit_rate = sum(hits) / len(hits) if hits else None
        if errors and errors == run.total:
            run.status = "failed"
            run.error = "全部用例执行失败（检查 LLM 配置与知识库绑定）"
        await session.commit()
