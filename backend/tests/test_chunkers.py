"""分块器单测。"""

from app.services.ingestion.chunkers import chunk_text, estimate_tokens


def test_short_text_single_chunk():
    results = chunk_text("你好世界", size=500, overlap=50)
    assert len(results) == 1
    assert results[0].content == "你好世界"
    assert results[0].seq == 0


def test_long_text_split_respects_size():
    text = "段落内容。" * 300  # 1500 字
    results = chunk_text(text, size=200, overlap=0)
    assert len(results) > 1
    for r in results:
        # 硬切路径允许 == size；分隔符切分应 <= size
        assert len(r.content) <= 200 + 50


def test_paragraph_boundary_preferred():
    text = "第一段内容" + "。" * 60 + "\n\n" + "第二段内容" + "。" * 60
    results = chunk_text(text, size=100, overlap=0)
    assert len(results) == 2
    assert results[0].content.startswith("第一段")
    assert results[1].content.startswith("第二段")


def test_overlap_appended():
    text = "\n\n".join(f"第{i}段" + "内容" * 40 for i in range(5))
    results = chunk_text(text, size=100, overlap=20)
    assert len(results) >= 2
    # 后一块应包含前一块尾部若干字符（overlap 衔接）
    if len(results) >= 2:
        prev_tail = results[0].content[-20:]
        assert results[1].content.startswith(prev_tail[:5])


def test_heading_meta_propagates():
    text = "# 公司简介\n\n我们是测试公司。\n\n" + "业务内容。" * 100
    results = chunk_text(text, size=150, overlap=0)
    assert results[0].meta.get("heading") == "公司简介"
    assert all(r.meta.get("heading") == "公司简介" for r in results)


def test_empty_text():
    assert chunk_text("", size=500, overlap=50) == []
    assert chunk_text("   \n\n  ", size=500, overlap=50) == []


def test_seq_numbers_continuous():
    text = "内容。" * 500
    results = chunk_text(text, size=200, overlap=30)
    assert [r.seq for r in results] == list(range(len(results)))


def test_estimate_tokens():
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcd") == 3  # ceil(4/1.5)
    assert estimate_tokens("中文文本") == 3
