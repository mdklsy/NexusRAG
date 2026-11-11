"""递归字符分块：按分隔符层级切分 + overlap 滑窗，保留标题层级元数据。"""

import math
import re
from dataclasses import dataclass, field

SEPARATORS = ["\n\n", "\n", "。", "！", "？", ". ", "! ", "? ", "; ", "；", "，", " ", ""]


@dataclass
class ChunkResult:
    content: str
    seq: int
    meta: dict = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """粗估 token：中文≈1字/token，英文≈4字符/token。取折中 len/1.5。"""
    return max(1, math.ceil(len(text) / 1.5))


def _split(text: str, sep: str) -> list[str]:
    if sep == "\n\n":
        return [p for p in re.split(r"\n\s*\n", text)]
    return text.split(sep)


def _rec(text: str, size: int, seps: list[str]) -> list[str]:
    """递归切分到 <=size 的块（overlap 在最内层硬切时生效）。"""
    if len(text) <= size:
        return [text]
    if not seps:
        step = max(1, size - 50)
        return [text[i : i + size] for i in range(0, len(text), step)]

    sep, rest = seps[0], seps[1:]
    parts = [p.strip() for p in _split(text, sep) if p.strip()]
    if len(parts) <= 1:
        return _rec(text, size, rest)

    # 先递归处理超长片段
    pieces: list[str] = []
    for p in parts:
        pieces.extend(_rec(p, size, rest) if len(p) > size else [p])

    # 贪心合并相邻片段到 size
    blocks: list[str] = []
    buf = ""
    for p in pieces:
        cand = f"{buf}{sep}{p}" if buf else p
        if len(cand) <= size:
            buf = cand
        else:
            if buf:
                blocks.append(buf)
            buf = p
    if buf:
        blocks.append(buf)
    return blocks


def chunk_text(
    text: str,
    size: int = 500,
    overlap: int = 50,
    meta: dict | None = None,
) -> list[ChunkResult]:
    """递归分块 + 尾部 overlap。size/overlap 单位为字符。"""
    size = max(100, int(size))
    overlap = max(0, min(int(overlap), size // 4))
    text = re.sub(r"[ \t]+\n", "\n", text.strip())
    if not text:
        return []

    blocks = _rec(text, size, SEPARATORS)

    # 相邻块间补 overlap：后一块头部带上前一块尾部（去掉重复正文）
    if overlap > 0 and len(blocks) > 1:
        overlapped = [blocks[0]]
        for prev, cur in zip(blocks, blocks[1:], strict=False):
            tail = prev[-overlap:]
            if not cur.startswith(tail):
                # 块边界在原文是分隔符处（段落/句子边界，piece 曾被 strip）；
                # cur 以结构性标记开头（围栏/标题/表格/列表）时补换行，
                # 防止 "## 标题```" 这类行被粘出、heading 元数据抓脏
                if re.match(r"^(```|#{1,6}\s|\||[-*+]\s|\d+[.、]\s)", cur):
                    tail += "\n"
                overlapped.append(tail + cur)
            else:
                overlapped.append(cur)
        blocks = overlapped

    # 标注邻近标题层级（markdown 标题）
    results: list[ChunkResult] = []
    last_heading = ""
    for _i, b in enumerate(blocks):
        b = b.strip()
        if not b:
            continue
        m = re.search(r"^#{1,6}\s+(.+)$", b, re.MULTILINE)
        if m:
            last_heading = m.group(1).strip()
        chunk_meta = dict(meta or {})
        if last_heading:
            chunk_meta["heading"] = last_heading
        results.append(ChunkResult(content=b, seq=len(results), meta=chunk_meta))
    return results
