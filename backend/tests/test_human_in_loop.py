"""人机协作回归：工具审批门（拦截→审批→续跑）、答案审核（缓冲→改写放行→挂件可见性）。"""

import hashlib
import hmac as hmac_mod
import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token, generate_api_key, hash_password
from app.db.session import session_scope
from app.models.app import App, Conversation, Message, PendingAction, Tool
from app.models.platform import ApiKey, User

pytestmark = pytest.mark.asyncio


class ApprovalLLM:
    """第一轮调 require_approval 工具 → 收到拦截文本 → 直接作答。"""

    def __init__(self):
        self.calls = 0
        self.seen_tool_result = None

    async def chat_json(self, messages, temperature=0.0, max_tokens=4096):
        return '{"intent": "qa"}'

    async def chat_with_tools(self, messages, tools, temperature=0.3, max_tokens=2048):
        self.calls += 1
        if self.calls == 1:
            return "", [{"id": "c1", "name": "refund", "arguments": '{"order_id": "A1"}'}], {
                "tokens_in": 20, "tokens_out": 5,
            }
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        self.seen_tool_result = tool_msgs[-1]["content"] if tool_msgs else None
        return "已提交人工审批，请稍候。", None, {"tokens_in": 10, "tokens_out": 5}

    async def chat(self, messages, temperature=0.3, max_tokens=2048):
        return "处理结果说明。", {"tokens_in": 5, "tokens_out": 3}

    async def chat_stream(self, messages, temperature=0.3, max_tokens=2048):
        yield "默认回答", None
        yield "", {"tokens_in": 8, "tokens_out": 4}


async def _mk_env(tool_config=None, retrieval_config=None):
    """建应用 + 敏感工具 + 会话 + admin 用户，返回 (app_id, conv_id, admin_token)。"""
    async with session_scope() as session:
        app = App(
            name="人机协作测试",
            retrieval_config={"intent_route": False, **(retrieval_config or {})},
        )
        session.add(app)
        await session.flush()
        session.add(Tool(
            app_id=app.id, name="refund", description="退款（敏感）", type="http_api",
            config=tool_config or {"method": "GET", "url": "http://internal/refund",
                                   "require_approval": True},
        ))
        conv = Conversation(app_id=app.id, end_user_id="op", title="审批会话")
        session.add(conv)
        admin = User(email="hitl-admin@test.local", name="a",
                     hashed_password=hash_password("x"), role="admin")
        session.add(admin)
        await session.commit()
        token = create_access_token(str(admin.id))
        return app.id, conv.id, token


def _orch():
    from app.services.chat import orchestrator

    return orchestrator


async def test_approval_gate_intercepts(sqlite_env, monkeypatch):
    """require_approval 工具：不真执行、落审批单、LLM 收到拦截文本并告知用户。"""
    from app.models.platform import ApiKey

    orch = _orch()
    executed = []
    monkeypatch.setattr("app.services.tools.execute_tool",
                        lambda t, a, ctx=None: executed.append(a) or "ok")
    fake = ApprovalLLM()
    monkeypatch.setattr(orch, "get_llm_client", lambda *_: fake)

    app_id, conv_id, _ = await _mk_env()
    events = []
    async with session_scope() as session:
        app_row = await session.get(App, app_id)
        async for ev in orch.run_chat(session, app_row, conv_id, "帮我退款订单A1", [],
                                      end_user={"id": "op", "name": "op"}):
            events.append(ev)

    # 拦截：没真执行，审批单已落库
    assert executed == []
    async with session_scope() as session:
        actions = list((await session.execute(select(PendingAction))).scalars().all())
        assert len(actions) == 1
        assert actions[0].status == "pending" and actions[0].tool_name == "refund"
        assert actions[0].ctx_snapshot.get("end_user") == {"id": "op", "name": "op"}

    # 事件流：approval_request 出现；回喂 LLM 的工具结果是拦截文本；答案告知用户
    kinds = [e["type"] for e in events]
    assert "approval_request" in kinds
    assert "人工审批" in (fake.seen_tool_result or "")
    answer = "".join(e["content"] for e in events if e["type"] == "delta")
    assert "审批" in answer


async def test_approval_decide_and_followup(sqlite_env, monkeypatch):
    """审批通过 → 真执行 → 续跑生成交代消息；重复决策 409；拒绝则不执行。"""
    orch = _orch()
    executed = []
    monkeypatch.setattr("app.services.tools.execute_tool",
                        lambda t, a, ctx=None: executed.append((t.name, a)) or "退款成功")
    fake = ApprovalLLM()
    monkeypatch.setattr(orch, "get_llm_client", lambda *_: fake)
    # 续跑的 get_llm_client（services.llm 命名空间）也换成假的
    monkeypatch.setattr("app.services.llm.get_llm_client", lambda *_: fake)

    app_id, conv_id, token = await _mk_env()
    async with session_scope() as session:
        session.add(PendingAction(
            app_id=app_id, conversation_id=conv_id, tool_name="refund",
            args={"order_id": "A1"}, ctx_snapshot={"end_user": {"id": "op"}},
        ))
        await session.commit()

    transport = ASGITransport(app=sqlite_env if False else None) if False else None
    from app.main import app as fastapi_app

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://t") as client:
        H = {"Authorization": f"Bearer {token}"}
        r = await client.get(f"/api/v1/apps/{app_id}/approvals?status=pending", headers=H)
        assert r.status_code == 200 and len(r.json()) == 1
        aid = r.json()[0]["id"]

        r2 = await client.post(f"/api/v1/apps/{app_id}/approvals/{aid}/decide",
                               headers=H, json={"approved": True})
        assert r2.status_code == 200
        assert r2.json()["status"] == "approved" and executed and executed[0][0] == "refund"
        assert "followup_message_id" in r2.json()

        r3 = await client.post(f"/api/v1/apps/{app_id}/approvals/{aid}/decide",
                               headers=H, json={"approved": True})
        assert r3.status_code == 409

        # 拒绝路径：再落一张单，拒绝 → 不执行
        async with session_scope() as session:
            session.add(PendingAction(
                app_id=app_id, conversation_id=conv_id, tool_name="refund",
                args={"order_id": "A2"}, ctx_snapshot={},
            ))
            await session.commit()
        r4 = await client.get(f"/api/v1/apps/{app_id}/approvals?status=pending", headers=H)
        aid2 = r4.json()[0]["id"]
        before = len(executed)
        r5 = await client.post(f"/api/v1/apps/{app_id}/approvals/{aid2}/decide",
                               headers=H, json={"approved": False})
        assert r5.status_code == 200 and r5.json()["status"] == "rejected"
        assert len(executed) == before  # 拒绝不执行

    # 续跑消息落库（两条交代：通过 + 拒绝）
    async with session_scope() as session:
        msgs = list((await session.execute(
            select(Message).where(Message.conversation_id == conv_id, Message.role == "assistant")
        )).scalars().all())
        joined = "".join(m.content for m in msgs)
        assert "审批结果" in joined and "refund" in joined


async def test_review_mode_buffers_answer(sqlite_env, monkeypatch):
    """review_mode=on：回答不直发、落 pending；改写放行后挂件历史可见。"""
    orch = _orch()
    monkeypatch.setattr("app.services.tools.execute_tool", lambda t, a, ctx=None: "x")
    fake = ApprovalLLM()
    monkeypatch.setattr(orch, "get_llm_client", lambda *_: fake)

    app_id, conv_id, token = await _mk_env(
        tool_config={"method": "GET", "url": "http://internal/x"},
        retrieval_config={"review_mode": "on"},
    )
    events = []
    async with session_scope() as session:
        app_row = await session.get(App, app_id)
        async for ev in orch.run_chat(session, app_row, conv_id, "你好", []):
            events.append(ev)

    assert any(e["type"] == "review_pending" for e in events)
    async with session_scope() as session:
        msgs = list((await session.execute(
            select(Message).where(Message.conversation_id == conv_id, Message.role == "assistant")
        )).scalars().all())
        assert msgs and msgs[0].review_status == "pending"
        mid = msgs[0].id

    from app.main import app as fastapi_app

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://t") as client:
        H = {"Authorization": f"Bearer {token}"}
        r = await client.get(f"/api/v1/apps/{app_id}/reviews", headers=H)
        assert r.status_code == 200 and len(r.json()) == 1

        r2 = await client.post(f"/api/v1/apps/{app_id}/reviews/{mid}/decide",
                               headers=H, json={"action": "replace", "content": "审核后的官方回复"})
        assert r2.status_code == 200 and r2.json()["review_status"] == "published"

    async with session_scope() as session:
        m = await session.get(Message, mid)
        assert m.review_status == "published" and m.content == "审核后的官方回复"

    # 挂件历史端点只回 published（需给应用配 widget_secret 签票据）
    secret = "sec-hitl"
    async with session_scope() as session:
        app_row = await session.get(App, app_id)
        wc = dict(app_row.widget_config or {})
        wc["widget_secret"] = secret
        app_row.widget_config = wc
        key_raw, key_hash = generate_api_key()
        session.add(ApiKey(app_id=app_id, name="w2", key_hash=key_hash, scope="chat"))
        await session.commit()
    ts = int(time.time())
    sig = hmac_mod.new(secret.encode(), f"op:{ts}".encode(), hashlib.sha256).hexdigest()
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://t") as client:
        r = await client.get(
            f"/api/v1/chat/conversations/{conv_id}/messages?end_user_id=op&ts={ts}&sig={sig}",
            headers={"Authorization": f"Bearer {key_raw}"},
        )
        assert r.status_code == 200
        contents = [m["content"] for m in r.json()["messages"]]
        assert any("审核后的官方回复" in c for c in contents)
        assert not any("默认回答" in c for c in contents)  # 未审核版本永不可见
