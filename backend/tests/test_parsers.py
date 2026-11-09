"""解析器单测：不依赖网络的格式。"""

import io

from openpyxl import Workbook

from app.services.ingestion.parsers import ParseError, parse_bytes, parse_xlsx


def test_parse_txt():
    data = "普通文本内容".encode()
    assert parse_bytes(data, "a.txt") == "普通文本内容"


def test_parse_markdown():
    data = "# 标题\n\n正文".encode()
    assert "标题" in parse_bytes(data, "a.md")


def test_parse_html_extracts_main_text():
    html = (
        "<html><body><article><h1>标题</h1><p>正文内容若干。</p>"
        "</article><footer>页脚</footer></body></html>"
    ).encode()
    text = parse_bytes(html, "a.html")
    assert "正文内容" in text
    assert "页脚" not in text


def test_parse_xlsx():
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["名称", "数值"])
    ws.append(["退款政策", "7天无理由"])
    buf = io.BytesIO()
    wb.save(buf)
    text = parse_xlsx(buf.getvalue())
    assert "Sheet1" in text
    assert "7天无理由" in text


def test_binary_garbage_raises():
    try:
        parse_bytes(b"\xff\xfe\x00\x01\x02", "unknown.bin")
        raise AssertionError("should raise ParseError")
    except ParseError:
        pass
