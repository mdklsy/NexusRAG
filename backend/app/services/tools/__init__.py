"""业务系统连接器：工具加载、OpenAI schema 生成、HTTP/SQL 执行器。

向下打通用户业务系统的核心模块。执行器为纯函数，便于单测与替换。
"""

import json
import re

import httpx
from sqlalchemy import create_engine, text

from app.models.app import Tool

MAX_RESULT_CHARS = 4000
SQL_ROW_LIMIT = 20


class ToolError(Exception):
    """工具执行失败（会作为结果文本回给 LLM，让其向用户说明）。"""


# ---------- 加载与 schema ----------


async def get_app_tools(session, app_id) -> list[Tool]:
    from sqlalchemy import select

    rows = (
        await session.execute(
            select(Tool).where(Tool.app_id == app_id, Tool.enabled.is_(True))
        )
    ).scalars().all()
    return list(rows)


def slugify(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip()).strip("_").lower() or "tool"


def to_openai_tools(tools: list[Tool]) -> list[dict]:
    out = []
    for t in tools:
        params = t.parameters_schema or default_parameters_schema(t)
        out.append(
            {
                "type": "function",
                "function": {
                    "name": slugify(t.name),
                    "description": t.description or t.display_name or t.name,
                    "parameters": params,
                },
            }
        )
    return out


def default_parameters_schema(tool: Tool) -> dict:
    if tool.type == "sql_db":
        return {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "只读 SELECT 查询语句"}
            },
            "required": ["sql"],
        }
    return {
        "type": "object",
        "properties": {
            "path_params": {"type": "object", "description": "URL 路径参数"},
            "query": {"type": "object", "description": "URL 查询参数"},
            "body": {"type": "object", "description": "请求体（JSON）"},
        },
    }


# ---------- 执行器 ----------


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + "…(截断)"


def _safe_sql(sql: str) -> str:
    """仅允许单条只读 SELECT/WITH 查询。"""
    cleaned = re.sub(r"--[^\n]*|/\*.*?\*/", "", sql, flags=re.S).strip().rstrip(";").strip()
    if not re.match(r"^(select|with)\b", cleaned, re.IGNORECASE):
        raise ToolError("仅允许 SELECT / WITH 开头的只读查询")
    banned = re.search(
        r"\b(insert|update|delete|drop|alter|create|truncate|grant|copy|merge)\b",
        cleaned,
        re.IGNORECASE,
    )
    if banned:
        raise ToolError(f"检测到写操作关键字: {banned.group(1)}")
    if ";" in cleaned:
        raise ToolError("不允许多条语句")
    return cleaned


def execute_http_tool(tool: Tool, args: dict) -> str:
    cfg = tool.config or {}
    method = (cfg.get("method") or "GET").upper()
    url = str(cfg.get("url") or "")
    if not url.startswith(("http://", "https://")):
        raise ToolError(f"工具 URL 未配置: {tool.name}")

    path_params = args.get("path_params") or {}
    for key, value in path_params.items():
        url = url.replace("{" + str(key) + "}", str(value))

    headers = dict(cfg.get("headers") or {})
    payload = args.get("body")
    if payload is not None:
        headers.setdefault("Content-Type", "application/json")
        payload = json.dumps(payload, ensure_ascii=False)
    try:
        # 业务 API 多为内网地址：默认绕过系统代理直连（trust_env=False），
        # 需要代理的场景在工具 config.proxy 显式指定
        with httpx.Client(
            trust_env=False, proxy=cfg.get("proxy") or None, timeout=float(cfg.get("timeout") or 15)
        ) as client:
            resp = client.request(
                method,
                url,
                params=args.get("query") or None,
                content=payload,
                headers=headers,
            )
    except httpx.HTTPError as e:
        raise ToolError(f"请求失败: {e}") from e

    body = resp.text
    try:
        body = json.dumps(resp.json(), ensure_ascii=False)
    except ValueError:
        pass
    return f"HTTP {resp.status_code}\n{_truncate(body)}"


def execute_sql_tool(tool: Tool, args: dict) -> str:
    dsn = (tool.config or {}).get("dsn")
    if not dsn:
        raise ToolError(f"工具 DSN 未配置: {tool.name}")
    sql = args.get("sql")
    if not sql:
        raise ToolError("缺少 sql 参数")
    sql = _safe_sql(sql)

    try:
        engine = create_engine(dsn, pool_pre_ping=True)
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"连接失败（检查驱动是否安装）: {e}") from e
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            rows = [dict(r._mapping) for r in result.fetchmany(SQL_ROW_LIMIT)]
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"SQL 执行失败: {e}") from e
    finally:
        engine.dispose()

    # 序列化（datetime 等转字符串）
    def default(o):
        return str(o)

    return _truncate(json.dumps(rows, ensure_ascii=False, default=default))


def execute_tool(tool: Tool, args: dict) -> str:
    """统一入口：返回结果文本；ToolError 的 message 也会回给 LLM。"""
    if tool.type == "http_api":
        return execute_http_tool(tool, args)
    if tool.type == "sql_db":
        return execute_sql_tool(tool, args)
    raise ToolError(f"未知工具类型: {tool.type}")
