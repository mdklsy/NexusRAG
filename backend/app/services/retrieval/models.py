"""检索层公共数据类型（独立模块避免循环导入）。"""

import uuid
from dataclasses import dataclass, field

from app.services.kg.graph_store import GraphEntity, SubGraph

# chunk 正文进入 Prompt 前的结构卫生：文档内容是用户可上传的，
# 若与 Prompt 自身的分隔符/标记撞形（如正文含 --- 或 【参考资料】），
# 轻则混淆结构，重则被当成指令层内容（Prompt 注入面）。
_MARKER_ESCAPES = {
    "---": "___",
    "【参考资料】": "〖参考资料〗",
    "【知识图谱事实】": "〖知识图谱事实〗",
    "# 用户问题": "＃用户问题",
}


def _sanitize_chunk_text(text: str) -> str:
    for k, v in _MARKER_ESCAPES.items():
        text = text.replace(k, v)
    return text


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    content: str
    score: float
    seq: int = 0
    heading: str = ""
    updated_at: str = ""  # 文档更新时间（YYYY-MM-DD），供时效性判断与展示


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    graph_entities: list[GraphEntity] = field(default_factory=list)
    graph_facts: list[str] = field(default_factory=list)
    subgraph: SubGraph | None = None

    @property
    def hit(self) -> bool:
        return bool(self.chunks)

    def build_context(self, max_chunks: int = 8, max_chars: int = 6000) -> tuple[str, list[dict]]:
        """构建 LLM 上下文块 + 引用列表。返回 (context_text, citations)。"""
        parts: list[str] = []
        citations: list[dict] = []
        used = 0
        for i, c in enumerate(self.chunks[:max_chunks], start=1):
            body = _sanitize_chunk_text(c.content[:1200])
            if used + len(body) > max_chars:
                break
            used += len(body)
            head = f"[{i}] ({c.document_name}"
            if c.updated_at:
                head += f" · 更新 {c.updated_at}"
            if c.heading:
                head += f" · {c.heading}"
            head += ")"
            parts.append(f"{head}\n{body}")
            citations.append(
                {
                    "index": i,
                    "chunk_id": str(c.chunk_id),
                    "document_id": str(c.document_id),
                    "document_name": c.document_name,
                    "heading": c.heading,
                    "updated_at": c.updated_at,
                    "score": round(c.score, 4),
                    "snippet": c.content[:200],
                }
            )
        context = "\n\n".join(parts)
        if self.graph_facts:
            facts = "\n".join(f"- {f}" for f in self.graph_facts)
            context += f"\n\n【知识图谱事实】\n{facts}"
        return context, citations
