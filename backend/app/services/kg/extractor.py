"""KG 三元组抽取（LLM 驱动）。"""

import json
import re
from dataclasses import dataclass

from app.services.llm import LLMClient, get_llm_client

EXTRACT_PROMPT = """你是一个知识图谱信息抽取专家。从下面的文本中抽取实体关系三元组。

实体类型参考：人物 / 组织 / 公司 / 产品 / 地点 / 时间 / 概念 / 技术 / 事件 / 指标 / 其他

输出 JSON 格式：
{{"triples": [
  {{"source": {{"name": "实体名", "type": "类型"}},
   "predicate": "关系",
   "target": {{"name": "实体名", "type": "类型"}}}}
]}}

规则：
1. 只抽取文本中明确陈述的事实，不要推断或编造
2. predicate 用简短的关系描述（如：属于、位于、创立了、包含、使用、导致、是）
3. 实体名保持原文表述，去掉代词（他/她/它/该公司等）
4. 无可抽取内容时输出 {{"triples": []}}

文本：
{chunk}"""


@dataclass
class Triple:
    source_name: str
    source_type: str
    predicate: str
    target_name: str
    target_type: str


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    # 去掉 markdown fences
    text = re.sub(r"^```(json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 容错：截取首个 { 到最后一个 }
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def parse_triples(raw: str) -> list[Triple]:
    """解析 LLM 输出为 Triple 列表（纯函数，便于单测）。"""
    data = _parse_json(raw)
    triples: list[Triple] = []
    for t in data.get("triples", []):
        try:
            src, tgt = t["source"], t["target"]
            triple = Triple(
                source_name=str(src["name"]).strip()[:300],
                source_type=str(src.get("type", "OTHER")).strip()[:50] or "OTHER",
                predicate=str(t["predicate"]).strip()[:200],
                target_name=str(tgt["name"]).strip()[:300],
                target_type=str(tgt.get("type", "OTHER")).strip()[:50] or "OTHER",
            )
        except (KeyError, TypeError):
            continue
        if triple.source_name and triple.target_name and triple.predicate:
            triples.append(triple)
    return triples


async def extract_triples(llm: LLMClient, chunk_text: str) -> list[Triple]:
    """对单个 chunk 抽取三元组。"""
    if len(chunk_text) < 30:
        return []
    raw = await llm.chat_json(
        [{"role": "user", "content": EXTRACT_PROMPT.format(chunk=chunk_text[:3000])}],
        max_tokens=2048,
    )
    return parse_triples(raw)


def link_query_entities(query: str, entity_names: list[tuple[str, int]]) -> list[str]:
    """实体链接（轻量）：实体名出现在 query 中即命中，按 mention 排序。

    entity_names: [(name, mention_count), ...] 纯函数便于单测。
    """
    q = query.lower()
    hits = [(name, cnt) for name, cnt in entity_names if name.lower() in q and len(name) >= 2]
    hits.sort(key=lambda x: -x[1])
    return [name for name, _ in hits]


def get_extractor_client() -> LLMClient:
    return get_llm_client()
