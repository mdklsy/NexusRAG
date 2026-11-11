"""二期集成测试：业务工具 function calling 循环 + SQL 安全校验 + 挂件端点。"""

import pytest

from app.core.security import generate_api_key
from app.db.session import session_scope
from app.models.app import App, Tool
from app.services.tools import ToolError, _safe_sql, to_openai_tools

pytestmark = pytest.mark.asyncio


# ---------- 纯函数：SQL 校验与 schema ----------


def test_safe_sql_allows_select_and_cte():
    assert _safe_sql("SELECT * FROM orders").startswith("SELECT")
    assert _safe_sql("  with t as (select 1) select * from t  ").startswith("with")


def test_safe_sql_blocks_writes():
    for bad in [
        "DELETE FROM orders",
        "UPDATE orders SET status=1",
        "INSERT INTO t VALUES (1)",
        "DROP TABLE orders",
        "SELECT 1; DELETE FROM orders",  # 多语句
        "SELECT pg_sleep(10); SELECT 1",
    ]:
        with pytest.raises(ToolError):
            _safe_sql(bad)


def test_safe_sql_strips_comments():
    # 注释里的 delete 不应误伤正常查询
    sql = _safe_sql("SELECT * FROM t -- delete comment")
    assert sql.startswith("SELECT")
    with pytest.raises(ToolError):
        _safe_sql("SELECT 1 /*x*/; DELETE FROM t")


def test_slugify_and_schema():
    t = Tool(
        app_id=None,
        name="Query Order!",
        description="查订单",
        type="http_api",
        config={},
        parameters_schema={},
    )
    tools = to_openai_tools([t])
    assert tools[0]["function"]["name"] == "query_order"
    assert tools[0]["function"]["parameters"]["type"] == "object"


# ---------- 集成：工具调用循环 ----------


class FakeToolLLM:
    """第一轮调用工具，拿到结果后作答。"""

    def __init__(self):
        self.calls = 0
        self.seen_tool_result = None

    async def chat_json(self, messages, temperature=0.0, max_tokens=4096):
        return '{"intent": "qa"}'

    async def chat_with_tools(self, messages, tools, temperature=0.3, max_tokens=2048):
        self.calls += 1
        if self.calls == 1:
            return "", [
                {
                    "id": "call_1",
                    "name": "query_order",
                    "arguments": '{"path_params": {"order_id": "A100"}}',
                }
            ], {"tokens_in": 20, "tokens_out": 5}
        # 第二轮：检查 tool 结果已进入上下文
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        self.seen_tool_result = tool_msgs[0]["content"] if tool_msgs else None
        return "订单 A100 已发货，预计明天送达。", None, {"tokens_in": 60, "tokens_out": 15}


async def test_tool_calling_loop(sqlite_env, monkeypatch):
    from app.models.app import Conversation
    from app.services.chat import orchestrator as orch

    fake_llm = FakeToolLLM()

    def fake_execute(tool, args, ctx=None):
        assert args == {"path_params": {"order_id": "A100"}}
        return '{"order_id": "A100", "status": "shipped"}'

    monkeypatch.setattr(orch, "execute_tool", fake_execute)
    monkeypatch.setattr(orch, "get_llm_client", lambda *_: fake_llm)

    async with session_scope() as session:
        app = App(name="带工具的应用", system_prompt="你是客服", retrieval_config={
            "top_k": 3, "score_threshold": 0, "use_kg": False, "intent_route": True
        })
        session.add(app)
        await session.flush()
        session.add(Tool(
            app_id=app.id, name="query_order", display_name="查订单",
            description="根据订单号查询订单状态",
            type="http_api",
            config={"method": "GET", "url": "https://api.example.com/orders/{order_id}"},
        ))
        conv = Conversation(app_id=app.id)
        session.add(conv)
        await session.commit()
        app_id, conv_id = app.id, conv.id

    async with session_scope() as session:
        app = await session.get(App, app_id)
        events = []
        async for ev in orch.run_chat(session, app, conv_id, "我的订单 A100 到哪了？", []):
            events.append(ev)

    types = [e["type"] for e in events]
    assert "tool_call" in types and "tool_result" in types
    tc = next(e for e in events if e["type"] == "tool_call")
    assert tc["name"] == "query_order"
    tr = next(e for e in events if e["type"] == "tool_result")
    assert tr["ok"] is True

    delta = "".join(e["content"] for e in events if e["type"] == "delta")
    assert "已发货" in delta

    # FakeLLM 第二轮收到了工具结果
    assert fake_llm.seen_tool_result and "shipped" in fake_llm.seen_tool_result

    # usage 事件聚合两轮 token
    usage = next(e for e in events if e["type"] == "usage")
    assert usage["tokens_in"] == 80 and usage["tokens_out"] == 20


async def test_tool_failure_feeds_error_to_llm(sqlite_env, monkeypatch):
    """工具执行异常不中断，错误文本回喂 LLM。"""

    class FailFirstLLM(FakeToolLLM):
        async def chat_with_tools(self, messages, tools, temperature=0.3, max_tokens=2048):
            self.calls += 1
            if self.calls == 1:
                return "", [
                    {"id": "c1", "name": "query_order", "arguments": "{}"}
                ], {"tokens_in": 1, "tokens_out": 1}
            tool_msgs = [m for m in messages if m.get("role") == "tool"]
            self.seen_tool_result = tool_msgs[0]["content"] if tool_msgs else None
            return "抱歉，查询系统暂时不可用。", None, {"tokens_in": 2, "tokens_out": 2}

    from app.models.app import Conversation
    from app.services.chat import orchestrator as orch

    fake_llm = FailFirstLLM()
    monkeypatch.setattr(
        orch, "execute_tool",
        lambda tool, args, ctx=None: (_ for _ in ()).throw(ToolError("连接超时")),
    )
    monkeypatch.setattr(orch, "get_llm_client", lambda *_: fake_llm)

    async with session_scope() as session:
        app = App(name="t2", retrieval_config={"intent_route": True, "use_kg": False})
        session.add(app)
        await session.flush()
        session.add(Tool(app_id=app.id, name="query_order", type="http_api",
                         config={"url": "https://x.io/{id}"}, description="d"))
        conv = Conversation(app_id=app.id)
        session.add(conv)
        await session.commit()
        app_id, conv_id = app.id, conv.id

    async with session_scope() as session:
        app = await session.get(App, app_id)
        events = []
        async for ev in orch.run_chat(session, app, conv_id, "查订单", []):
            events.append(ev)

    tr = next(e for e in events if e["type"] == "tool_result")
    assert tr["ok"] is False
    assert "连接超时" in fake_llm.seen_tool_result


# ---------- 集成：挂件端点 ----------


async def test_widget_config_endpoint(sqlite_env):
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    async with session_scope() as session:
        app = App(name="挂件应用", widget_config={
            "title": "在线客服", "welcome": "hi", "theme": "#722ed1", "bubble": "🛎️"
        })
        session.add(app)
        await session.flush()
        raw, key_hash = generate_api_key()
        from app.models.platform import ApiKey

        session.add(ApiKey(app_id=app.id, name="widget", key_hash=key_hash, scope="chat"))
        await session.commit()

    client = TestClient(fastapi_app)
    # 无 Key
    r0 = client.get("/api/v1/widget/config")
    assert r0.status_code == 401
    # 带 Key
    r = client.get("/api/v1/widget/config", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "在线客服"
    assert data["theme"] == "#722ed1"
    assert data["app_name"] == "挂件应用"
