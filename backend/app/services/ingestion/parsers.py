"""文档解析：各种格式 → 纯文本（尽力保留段落结构）。"""

import io
from pathlib import Path

import httpx
from docx import Document as DocxDocument
from openpyxl import load_workbook
from pypdf import PdfReader
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from app.core.config import get_settings

USER_AGENT = "Mozilla/5.0 (compatible; NexusRAGBot/0.1; +https://github.com/nexusrag)"


class ParseError(Exception):
    pass


def parse_pdf(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n\n".join(p.strip() for p in pages if p.strip())
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"PDF 解析失败: {e}") from e


def parse_docx(data: bytes) -> str:
    try:
        doc = DocxDocument(io.BytesIO(data))
        parts = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                style = (para.style.name or "").lower()
                prefix = "# " if "heading 1" in style else "## " if "heading" in style else ""
                parts.append(prefix + text)
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n\n".join(parts)
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"DOCX 解析失败: {e}") from e


def parse_xlsx(data: bytes) -> str:
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        parts = []
        for ws in wb.worksheets:
            parts.append(f"# Sheet: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n\n".join(parts)
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"XLSX 解析失败: {e}") from e


def parse_html(data: bytes) -> str:
    try:
        tree = HTMLParser(data.decode("utf-8", errors="ignore"))
        for node in tree.css("script, style, nav, footer, header, noscript"):
            node.decompose()
        main = tree.css_first("article, main, .content, #content") or tree.body
        if main is None:
            raise ParseError("HTML 中未找到正文")
        return main.text(separator="\n", strip=True)
    except ParseError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"HTML 解析失败: {e}") from e


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def parse_bytes(data: bytes, filename: str, mime_type: str | None = None) -> str:
    """按扩展名/ mime 选择解析器。"""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf" or mime_type == "application/pdf":
        return parse_pdf(data)
    if ext in (".docx",) or mime_type == DOCX_MIME:
        return parse_docx(data)
    if ext in (".xlsx",) or mime_type == XLSX_MIME:
        return parse_xlsx(data)
    if ext in (".html", ".htm"):
        return parse_html(data)
    # md / txt / csv 及未知文本类
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ParseError(f"不支持的文件类型或编码: {filename}") from e


async def fetch_url(url: str) -> tuple[str, str]:
    """抓取网页，返回 (标题, 正文)。"""
    get_settings()
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=30, headers={"User-Agent": USER_AGENT}
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as e:
        raise ParseError(f"网页抓取失败: {e}") from e
    text = parse_html(resp.content)
    tree = HTMLParser(resp.content.decode("utf-8", errors="ignore"))
    title_node = tree.css_first("title")
    title = title_node.text(strip=True) if title_node else url
    if len(text.strip()) < 20:
        raise ParseError("网页正文过短，可能被反爬或为动态渲染页面")
    return title, text
