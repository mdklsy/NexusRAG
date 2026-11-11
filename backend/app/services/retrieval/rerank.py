"""重排：对检索候选二次排序。

- llm：零额外依赖，LLM 按相关度打分（默认候选 ≤10 条，成本可控）
- api：托管 Rerank API（SiliconFlow/Jina/Cohere 风格 /rerank，失败容错）
- cross_encoder：可选重依赖，安装 backend/pip install ".[rerank]" 后可用
"""

import json
import logging
import re

from app.services.retrieval.models import RetrievedChunk

logger = logging.getLogger(__name__)

RERANK_PROMPT = """对以下候选片段与问题的相关度打分（0-10，10 最相关）。
输出 JSON：{{"scores": [分数1, 分数2, ...]}}，顺序与输入一致，不要解释。

问题：{query}

候选片段：
{chunks}"""


def parse_scores(raw: str, expect: int) -> list[float] | None:
    """解析 LLM 打分输出。纯函数便于单测。"""
    text = re.sub(r"^```(json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end <= start:
            return None
        try:
            scores = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    else:
        scores = data.get("scores", [])
    try:
        result = [float(s) for s in scores][:expect]
    except (TypeError, ValueError):
        return None
    if len(result) < expect:
        result += [0.0] * (expect - len(result))
    return result


async def llm_rerank(llm, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """LLM 相关度重排；失败或解析异常时原样返回（不阻塞主链路）。"""
    if len(chunks) <= 1:
        return chunks
    listing = "\n".join(
        f"{i}. {c.document_name} | {c.content[:200]}" for i, c in enumerate(chunks, 1)
    )
    try:
        raw = await llm.chat_json(
            [{"role": "user", "content": RERANK_PROMPT.format(query=query, chunks=listing)}],
            max_tokens=256,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("llm rerank failed: %s", e)
        return chunks
    scores = parse_scores(raw, len(chunks))
    if scores is None:
        return chunks
    paired = sorted(zip(chunks, scores, strict=True), key=lambda x: -x[1])
    return [c for c, _ in paired]


async def cross_encoder_rerank(
    query: str, chunks: list[RetrievedChunk], model_name: str = "BAAI/bge-reranker-base"
) -> list[RetrievedChunk]:
    """Cross-Encoder 重排（可选依赖：pip install nexusrag[rerank]）。"""
    if len(chunks) <= 1:
        return chunks
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as e:
        raise RuntimeError(
            "cross_encoder 重排需要安装可选依赖：pip install '.[rerank]'"
        ) from e
    model = CrossEncoder(model_name, max_length=512)
    pairs = [(query, c.content[:1000]) for c in chunks]
    scores = model.predict(pairs)
    paired = sorted(zip(chunks, list(scores), strict=True), key=lambda x: -float(x[1]))
    return [c for c, _ in paired]


async def api_rerank(
    query: str,
    chunks: list[RetrievedChunk],
    override: dict | None = None,
) -> list[RetrievedChunk]:
    """托管 Rerank API（SiliconFlow/Jina/Cohere 风格 /rerank）；失败容错原样返回。

    override 为应用级覆盖（retrieval_config.rerank_config）：
    api_base / model 明文，api_key_enc 为应用密文——缺省回退全局（设置页/.env）。
    """
    if len(chunks) <= 1:
        return chunks
    from app.core import runtime_settings

    await runtime_settings.ensure_fresh()
    g = runtime_settings.get_global("rerank")
    ov = dict(override or {})
    if ov.get("api_key_enc"):
        from app.core.crypto import decrypt_secret

        try:
            ov["api_key"] = decrypt_secret(ov["api_key_enc"])
        except Exception:  # noqa: BLE001 解密失败回退全局
            ov["api_key"] = ""
    api_base = ov.get("api_base") or g["api_base"]
    model = ov.get("model") or g["model"]
    api_key = ov.get("api_key") or g["api_key"]
    if not (api_base and api_key):
        logger.warning("rerank=api 但托管重排未配置（设置页 / .env RERANK_API_*），跳过重排")
        return chunks
    try:
        import httpx

        async with httpx.AsyncClient(
            trust_env=False, timeout=15  # 绕过系统代理：直连托管 API
        ) as client:
            resp = await client.post(
                api_base.rstrip("/") + "/rerank",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "query": query,
                    "documents": [c.content[:1500] for c in chunks],
                    "top_n": len(chunks),
                },
            )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        # results: [{index, relevance_score}] → 按分数降序映射回候选
        ordered = sorted(results, key=lambda r: -float(r.get("relevance_score", 0)))
        return [chunks[r["index"]] for r in ordered if 0 <= r["index"] < len(chunks)]
    except Exception as e:  # noqa: BLE001 重排失败不阻塞主链路
        logger.warning("api rerank failed: %s", e)
        return chunks


async def rerank_chunks(
    llm,
    mode: str,
    query: str,
    chunks: list[RetrievedChunk],
    rerank_cfg: dict | None = None,
) -> list[RetrievedChunk]:
    if not chunks or mode in ("", "none", None):
        return chunks
    if mode == "llm":
        return await llm_rerank(llm, query, chunks)
    if mode == "cross_encoder":
        return await cross_encoder_rerank(query, chunks)
    if mode == "api":
        return await api_rerank(query, chunks, override=rerank_cfg)
    logger.warning("unknown rerank mode: %s, skip", mode)
    return chunks
