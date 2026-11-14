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

SCORE_PROMPT = """你是问答系统的质量评审员。根据以下信息给回答打三个维度的分（1-5 整数）：

1. faithfulness 忠实度：回答是否完全基于【参考资料】，无编造（5=完全忠实，1=大量编造）
2. relevance 相关性：是否切中【问题】并覆盖【期望要点】（5=完全切中，1=答非所问）
3. context_sufficiency 资料充分度：【参考资料】是否包含回答【问题】所需的全部信息（5=完全充分，1=资料里根本没有答案）

【问题】{question}
【期望要点】{points}
【参考资料】{context}
【回答】{answer}

输出 JSON：{{"faithfulness": 5, "relevance": 5, "context_sufficiency": 5}}，不要解释。"""


def parse_scores(raw: str) -> tuple[float | None, float | None, float | None]:
    """解析三档分：忠实度/相关性/资料充分度。"""
    text = re.sub(r"^```(json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None, None, None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None, None, None
    try:
        f = float(data.get("faithfulness"))
        r = float(data.get("relevance"))
        cs = float(data.get("context_sufficiency", 5))
        return (min(5.0, max(1.0, f)), min(5.0, max(1.0, r)), min(5.0, max(1.0, cs)))
    except (TypeError, ValueError):
        return None, None, None


def diagnose(
    *,
    has_chunks: bool,
    retrieved_names: list[str],
    retrieved_chunks: list[dict],
    expected_doc_name: str,
    faithfulness: float | None,
    relevance: float | None,
    context_sufficiency: float | None,
) -> dict | None:
    """检索失败归因（确定性规则）：从打分与召回证据推断失败环节与修复建议。

    cause: no_recall(召回空) / recall_miss(期望文档没召回) / ranking(期望文档召回但排序差)
           / context_gap(资料不足以回答，多为分块割裂或文档缺失) / generation(资料够但回答不忠实)
    """
    if not has_chunks:
        return {"cause": "no_recall", "detail": "检索没有任何命中",
                "suggestion": "检查文档是否摄取完成；降低 score_threshold 或提高 top_k"}
    expected = (expected_doc_name or "").strip().lower()
    if expected and not any(expected in (n or "").lower() for n in retrieved_names):
        return {"cause": "recall_miss", "detail": f"期望文档「{expected_doc_name}」未进入召回",
                "suggestion": "检查该文档摄取状态与分块质量；尝试同义改写评测问题"}
    if expected:
        best_rank = next(
            (i + 1 for i, c in enumerate(retrieved_chunks)
             if expected in (c.get("document_name") or "").lower()),
            None,
        )
        if best_rank is not None and best_rank > 3:
            return {"cause": "ranking", "detail": f"期望文档召回但仅排第 {best_rank} 位",
                    "suggestion": "启用或调整 rerank 模型提升目标文档排序"}
    if context_sufficiency is not None and context_sufficiency < 3:
        return {"cause": "context_gap", "detail": "召回的资料不足以回答该问题",
                "suggestion": "多为分块割裂或关键文档缺失：调整 chunk size/overlap，或补充文档"}
    if faithfulness is not None and faithfulness < 3:
        return {"cause": "generation", "detail": "资料充分但回答不忠实（可能编造）",
                "suggestion": "收紧系统提示词（仅根据资料回答）或降低 temperature"}
    if relevance is not None and relevance < 3:
        return {"cause": "generation", "detail": "回答未切中问题要点",
                "suggestion": "检查期望要点表述；问题较长时开启多轮改写"}
    return None  # 各项正常，无需归因


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
    cs_scores: list[float] = []
    hits: list[bool] = []
    errors = 0

    for case in cases:
        started = time.monotonic()
        answer, doc_names, faithfulness, relevance, hit, err = "", [], None, None, None, None
        context_sufficiency: float | None = None
        retrieved_chunks: list[dict] = []
        diagnosis: dict | None = None
        try:
            async with session_scope() as session:
                app_row = await session.get(App, app_id)
                kbs = await get_app_knowledge_bases(session, app_id)
                result = await retrieve(
                    session, kbs, case.question, app_row.retrieval_config or {}
                )
                context, _ = result.build_context(max_chunks=6)
                doc_names = list(dict.fromkeys(c.document_name for c in result.chunks))
                retrieved_chunks = [
                    {"chunk_id": str(c.chunk_id), "document_name": c.document_name,
                     "heading": c.heading, "score": round(c.score, 4)}
                    for c in result.chunks[:6]
                ]
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
            faithfulness, relevance, context_sufficiency = parse_scores(raw)
            diagnosis = diagnose(
                has_chunks=bool(result.chunks),
                retrieved_names=doc_names,
                retrieved_chunks=retrieved_chunks,
                expected_doc_name=case.expected_doc_name,
                faithfulness=faithfulness,
                relevance=relevance,
                context_sufficiency=context_sufficiency,
            )
        except Exception as e:  # noqa: BLE001 单条失败不中断整体
            err = f"{type(e).__name__}: {e}"
            errors += 1
            logger.warning("eval case failed: %s", err)

        elapsed = int((time.monotonic() - started) * 1000)
        if faithfulness is not None:
            f_scores.append(faithfulness)
        if relevance is not None:
            r_scores.append(relevance)
        if context_sufficiency is not None:
            cs_scores.append(context_sufficiency)
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
                    retrieved_chunks=retrieved_chunks,
                    diagnosis=diagnosis,
                    faithfulness=faithfulness,
                    relevance=relevance,
                    context_sufficiency=context_sufficiency,
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
        run.avg_context_sufficiency = sum(cs_scores) / len(cs_scores) if cs_scores else None
        run.hit_rate = sum(hits) / len(hits) if hits else None
        if errors and errors == run.total:
            run.status = "failed"
            run.error = "全部用例执行失败（检查 LLM 配置与知识库绑定）"
        await session.commit()
