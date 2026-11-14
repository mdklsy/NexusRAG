"""创新批次回归：审核数据飞轮（审计/规则挖掘/驳回转评测）+ 知识缺口发现。

后续 ACL/自诊断/卡片/缓存用例也放本文件。
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.db.session import session_scope
from app.models.app import App, Conversation, KnowledgeGap, Message, ReviewDecision
from app.models.eval import EvalCase, EvalSet
from app.models.platform import User

pytestmark = pytest.mark.asyncio


class InsightsLLM:
    """chat_json 返回可配置 JSON；chat/chat_stream 给默认回答。"""

    def __init__(self, json_payload: dict | None = None):
        self.json_payload = json_payload or {}
        self.chat_calls = 0

    async def chat_json(self, messages, temperature=0.0, max_tokens=4096):
        return json.dumps(self.json_payload, ensure_ascii=False)

    async def chat(self, messages, temperature=0.3, max_tokens=2048):
        self.chat_calls += 1
        return "草稿回答内容", {"tokens_in": 5, "tokens_out": 3}

    async def chat_stream(self, messages, temperature=0.3, max_tokens=2048):
        yield "默认回答", None
        yield "", {"tokens_in": 8, "tokens_out": 4}

    async def chat_with_tools(self, messages, tools, temperature=0.3, max_tokens=2048):
        return "回答", None, {"tokens_in": 5, "tokens_out": 3}


async def _mk_env(retrieval_config=None):
    async with session_scope() as session:
        app = App(
            name="洞察测试",
            system_prompt="你是客服。",
            retrieval_config={"intent_route": False, **(retrieval_config or {})},
        )
        session.add(app)
        await session.flush()
        conv = Conversation(app_id=app.id, end_user_id="u1", title="会话A")
        session.add(conv)
        admin = User(email="insights-admin@test.local", name="a",
                     hashed_password=hash_password("x"), role="admin")
        session.add(admin)
        await session.commit()
        return app.id, conv.id, create_access_token(str(admin.id))


async def _add_qa_pair(conv_id, question, answer, *, hit=None, review_status="published"):
    """一对 user/assistant 消息（assistant 带检索命中标记与审核状态）。"""
    async with session_scope() as session:
        session.add(Message(conversation_id=conv_id, role="user", content=question))
        session.add(Message(
            conversation_id=conv_id, role="assistant", content=answer,
            hit=hit, review_status=review_status,
        ))
        await session.commit()


async def test_review_flywheel(sqlite_env, monkeypatch):
    """replace 决策审计留存原文；规则挖掘；驳回问题一键转评测用例。"""
    app_id, conv_id, token = await _mk_env()
    await _add_qa_pair(conv_id, "退款政策是什么", "15天退款", review_status="pending")

    orch_llm = InsightsLLM()
    from app.services.chat import orchestrator
    monkeypatch.setattr(orchestrator, "get_llm_client", lambda *_: orch_llm)
    monkeypatch.setattr("app.services.tools.execute_tool", lambda t, a, ctx=None: "x")

    from app.main import app as fastapi_app

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://t") as client:
        H = {"Authorization": f"Bearer {token}"}

        # 1) 改写决策 → 审计行留存原文
        r = await client.get(f"/api/v1/apps/{app_id}/reviews", headers=H)
        mid = r.json()[0]["message_id"]
        r = await client.post(f"/api/v1/apps/{app_id}/reviews/{mid}/decide", headers=H,
                              json={"action": "replace", "content": "退款周期为7天，请在订单页操作。"})
        assert r.status_code == 200

        async with session_scope() as session:
            rows = list((await session.execute(select(ReviewDecision))).scalars().all())
            assert len(rows) == 1 and rows[0].action == "replace"
            assert rows[0].content_before == "15天退款"
            assert "7天" in (rows[0].content_after or "")
            msg = await session.get(Message, rows[0].message_id)
            assert msg.content.startswith("退款周期")

        # 2) 规则挖掘：LLM 返回规则 JSON → 接口透出
        mine_llm = InsightsLLM({"rules": [{"rule": "退款周期必须写7天", "examples": 3}]})
        monkeypatch.setattr("app.services.llm.get_llm_client", lambda *_: mine_llm)
        r = await client.post(f"/api/v1/apps/{app_id}/insights/mine-rules", headers=H, json={})
        assert r.status_code == 200 and r.json()["rules"][0]["rule"].startswith("退款周期")

        # 3) 驳回（走决策 API → 驳回审计）→ 转评测
        await _add_qa_pair(conv_id, "发货多久", "3天发货", review_status="pending")
        r = await client.get(f"/api/v1/apps/{app_id}/reviews", headers=H)
        rmid = r.json()[0]["message_id"]
        r = await client.post(f"/api/v1/apps/{app_id}/reviews/{rmid}/decide", headers=H,
                              json={"action": "reject"})
        assert r.status_code == 200
        r = await client.get(f"/api/v1/apps/{app_id}/insights/rejected", headers=H)
        items = r.json()
        assert len(items) == 1 and items[0]["question"] == "发货多久"
        r = await client.post(f"/api/v1/apps/{app_id}/insights/rejected/to-eval", headers=H,
                              json={"message_ids": [items[0]["message_id"]]})
        assert r.status_code == 200 and r.json()["created"] == 1

        async with session_scope() as session:
            cases = list((await session.execute(select(EvalCase))).scalars().all())
            assert len(cases) == 1 and cases[0].question == "发货多久"
            sets = list((await session.execute(select(EvalSet))).scalars().all())
            assert sets[0].name == "审核驳回回归"

        # 4) 统计端点
        r = await client.get(f"/api/v1/apps/{app_id}/insights/stats", headers=H)
        s = r.json()
        assert s["replaced"] == 1 and s["rejected"] == 1 and s["decided"] == 2


async def test_knowledge_gap_discovery(sqlite_env, monkeypatch):
    """空知识库提问 → hit=False 落库；聚类分析 → 缺口主题；起草 → drafted。"""
    orch_llm = InsightsLLM()
    from app.services.chat import orchestrator
    monkeypatch.setattr(orchestrator, "get_llm_client", lambda *_: orch_llm)
    monkeypatch.setattr("app.services.tools.execute_tool", lambda t, a, ctx=None: "x")

    app_id, conv_id, token = await _mk_env()
    # 空知识库：qa 意图 → 检索必然无命中
    async with session_scope() as session:
        app_row = await session.get(App, app_id)
        async for _ev in orchestrator.run_chat(session, app_row, conv_id, "发票怎么开", []):
            pass

    async with session_scope() as session:
        msgs = list((await session.execute(
            select(Message).where(
                Message.conversation_id == conv_id, Message.role == "assistant"
            )
        )).scalars().all())
        assert msgs and msgs[0].hit is False

    analyze_llm = InsightsLLM({"themes": [{"theme": "发票开具", "questions": ["发票怎么开"]}]})
    monkeypatch.setattr("app.services.llm.get_llm_client", lambda *_: analyze_llm)

    from app.main import app as fastapi_app

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://t") as client:
        H = {"Authorization": f"Bearer {token}"}
        r = await client.post(f"/api/v1/apps/{app_id}/insights/gaps/analyze",
                              headers=H, json={"days": 30})
        assert r.status_code == 200 and r.json()[0]["theme"] == "发票开具"
        gap_id = r.json()[0]["id"]

        r2 = await client.post(f"/api/v1/apps/{app_id}/insights/gaps/{gap_id}/draft", headers=H)
        assert r2.status_code == 200 and r2.json()["status"] == "drafted"
        assert r2.json()["draft_answer"]

        r3 = await client.post(f"/api/v1/apps/{app_id}/insights/gaps/{gap_id}/resolve", headers=H)
        assert r3.status_code == 200 and r3.json()["status"] == "resolved"

        # resolved 的缺口在重建 open 时保留
        r4 = await client.post(f"/api/v1/apps/{app_id}/insights/gaps/analyze",
                               headers=H, json={"days": 30})
        async with session_scope() as session:
            gaps = list((await session.execute(select(KnowledgeGap))).scalars().all())
            statuses = {g.status for g in gaps}
            assert "resolved" in statuses
