"""中文分词（jieba）+ 倒排索引构建。"""

import re

try:
    import jieba

    _jieba_available = True
except ImportError:  # pragma: no cover
    _jieba_available = False

STOPWORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "那", "他", "她", "它", "们", "什么",
    "怎么", "哪些", "如何", "可以", "能", "还是", "以及", "因为", "所以",
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "for",
    "and", "or", "on", "with", "by", "it", "this", "that", "be", "as", "at",
}

_PURE_ASCII_WORD = re.compile(r"^[a-zA-Z0-9_\-]+$")


def tokenize(text: str) -> list[str]:
    """分词 + 过滤：去停用词、单字汉字、超长词；统一小写。"""
    if not text:
        return []
    if _jieba_available:
        words = jieba.lcut(text)
    else:  # 无 jieba 时退化为 n-gram 切分（仅供极端环境）
        words = re.split(r"[\s，。！？；、,.!?;:\n]+", text)

    out: list[str] = []
    for w in words:
        w = w.strip().lower()
        if not w or len(w) > 40:
            continue
        if w in STOPWORDS:
            continue
        # 单个汉字/单字母无区分度
        if len(w) == 1:
            continue
        out.append(w)
    return out
