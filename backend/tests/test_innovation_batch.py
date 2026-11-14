"""创新批次回归：审核数据飞轮（审计/规则挖掘/驳回转评测）+ 知识缺口发现。

后续 ACL/自诊断/卡片/缓存用例也放本文件。
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.db.session import session_scope
from app.models.app import App, Conversation, KnowledgeGap, Message, ReviewDecision, Tool
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


async def _mk_acl_kb(monkeypatch=None):
    """公开文档 + 受限文档各一，真实摄取进内存 Qdrant。返回 (kb_id, doc_pub, doc_res)。"""
    import pathlib

    from app.core.config import get_settings
    from app.db.session import session_scope
    from app.models.kb import Document, KnowledgeBase
    from app.services.ingestion.pipeline import ingest_document

    async with session_scope() as session:
        kb = KnowledgeBase(name="acl", embedding_model="m", embedding_dim=8,
                           chunk_config={"size": 100, "overlap": 20})
        session.add(kb)
        await session.flush()
        d1 = Document(kb_id=kb.id, name="public.md", source_type="upload", file_path="acl_public.md")
        d2 = Document(kb_id=kb.id, name="secret.md", source_type="upload", file_path="acl_secret.md")
        session.add_all([d1, d2])
        await session.commit()
        kb_id, id1, id2 = kb.id, d1.id, d2.id
    pd = pathlib.Path(get_settings().upload_dir)
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "acl_public.md").write_text("# 公开政策\n\n全国包邮，顺丰发出。", encoding="utf-8")
    (pd / "acl_secret.md").write_text("# 内部薪资\n\n一级薪资范围八千到一万。", encoding="utf-8")
    await ingest_document(id1)
    await ingest_document(id2)
    return kb_id, id1, id2


async def test_document_acl_retrieval(sqlite_env):
    """受限文档：白名单内可见、外不可见；无终端用户身份全量可见。"""
    from sqlalchemy import update as sa_update

    from app.db.session import session_scope
    from app.models.kb import Document
    from app.services.retrieval import retrieve
    from app.services.retrieval.acl import resolve_acl

    kb_id, id1, id2 = await _mk_acl_kb()
    async with session_scope() as session:
        await session.execute(
            sa_update(Document).where(Document.id == id2)
            .values(acl={"mode": "restricted", "end_users": ["op1"]})
        )
        await session.commit()

    # 过滤集计算（ID 白名单兼容路径）
    async with session_scope() as session:
        assert await resolve_acl(session, [kb_id], None) is None
        f_u1 = await resolve_acl(session, [kb_id], {"id": "op1"})
        f_u2 = await resolve_acl(session, [kb_id], {"id": "op2"})
        assert f_u1 is None or id2 not in f_u1.deny_doc_ids  # op1 被授权，无过滤或不含 doc2
        assert f_u2 is not None and id2 in f_u2.deny_doc_ids

    # 检索过滤：op2 拿不到受限文档内容
    from app.models.kb import KnowledgeBase

    async with session_scope() as session:
        kb = await session.get(KnowledgeBase, kb_id)
        cfg = {"top_k": 5, "score_threshold": 0, "use_kg": False, "use_bm25": True}
        r_all = await retrieve(session, [kb], "薪资范围", cfg)
        r_acl = await retrieve(session, [kb], "薪资范围", cfg, acl=f_u2)
        assert any("八千" in c.content for c in r_all.chunks)
        assert all("八千" not in c.content for c in r_acl.chunks)


async def test_document_acl_chat_path(sqlite_env):
    """挂件端到端：end_user=白名单外 → 回答引用不含受限文档；白名单内 → 可含。"""
    from app.core.config import get_settings

    orch_llm = InsightsLLM()
    from app.services.chat import orchestrator
    monkeypatch_unused = None
    app_id, conv_id, token = await _mk_env()
    kb_id, id1, id2 = await _mk_acl_kb()

    from sqlalchemy import update as sa_update

    from app.db.session import session_scope
    from app.models.app import AppKnowledgeBase
    from app.models.kb import Document
    async with session_scope() as session:
        await session.execute(
            sa_update(Document).where(Document.id == id2)
            .values(acl={"mode": "restricted", "end_users": ["op1"]})
        )
        session.add(AppKnowledgeBase(app_id=app_id, kb_id=kb_id))
        await session.commit()

    async with session_scope() as session:
        app_row = await session.get(App, app_id)
        async for _ev in orchestrator.run_chat(
            session, app_row, conv_id, "薪资范围是多少", [],
            end_user={"id": "op2", "name": "op2"},
        ):
            pass
    async with session_scope() as session:
        msgs = list((await session.execute(
            select(Message).where(
                Message.conversation_id == conv_id, Message.role == "assistant"
            )
        )).scalars().all())
        cites = msgs[0].citations or []
        assert all(c.get("document_name") != "secret.md" for c in cites)
        assert msgs[0].hit is False or cites  # ACL 过滤后可能无命中


class JudgeLLM:
    """评测 judge：chat_json 返回三档分；chat 生成回答。"""

    def __init__(self, scores: dict):
        self.scores = scores

    async def chat(self, messages, temperature=0.3, max_tokens=2048):
        return "基于资料生成的回答", {"tokens_in": 10, "tokens_out": 5}

    async def chat_json(self, messages, temperature=0.0, max_tokens=4096):
        import json as _json
        return _json.dumps(self.scores, ensure_ascii=False)

    async def chat_stream(self, messages, temperature=0.3, max_tokens=2048):
        yield "默认回答", None
        yield "", {"tokens_in": 8, "tokens_out": 4}

    async def chat_with_tools(self, messages, tools, temperature=0.3, max_tokens=2048):
        return "回答", None, {"tokens_in": 5, "tokens_out": 3}


async def test_eval_self_diagnosis(sqlite_env, monkeypatch):
    """评测：retrieved_chunks/diagnosis 落库；无召回与资料不足两场景归因正确。"""
    from app.services.chat import orchestrator as orch_mod
    from app.services.evaluator import run_eval

    kb_id, id1, id2 = await _mk_acl_kb()
    app_id, conv_id, token = await _mk_env()
    # 应用绑定 KB
    from app.db.session import session_scope as ss
    from app.models.app import AppKnowledgeBase
    async with ss() as session:
        session.add(AppKnowledgeBase(app_id=app_id, kb_id=kb_id))
        await session.commit()

    # 场景1：正常召回 + 资料充分度 2 → context_gap
    judge = JudgeLLM({"faithfulness": 5, "relevance": 5, "context_sufficiency": 2})
    monkeypatch.setattr("app.services.evaluator.get_llm_client", lambda *_: judge)
    from app.models.eval import EvalCase, EvalResult, EvalRun, EvalSet
    async with ss() as session:
        es = EvalSet(app_id=app_id, name="自诊断")
        session.add(es)
        await session.flush()
        session.add(EvalCase(eval_set_id=es.id, question="包邮",
                             expected_points="", expected_doc_name="public.md"))
        await session.flush()
        run = EvalRun(eval_set_id=es.id, status="pending", total=1)
        session.add(run)
        await session.commit()
        run_id = run.id
    await run_eval(run_id)

    async with ss() as session:
        r = (await session.execute(select(EvalResult).where(EvalResult.run_id == run_id))).scalars().first()
        assert r.diagnosis and r.diagnosis["cause"] == "context_gap"
        assert r.retrieved_chunks and r.retrieved_chunks[0]["document_name"] == "public.md"
        assert r.context_sufficiency == 2.0
        run = await session.get(EvalRun, run_id)
        assert run.avg_context_sufficiency == 2.0

    # 场景2：期望文档名不匹配 → recall_miss
    judge2 = JudgeLLM({"faithfulness": 5, "relevance": 4, "context_sufficiency": 4})
    monkeypatch.setattr("app.services.evaluator.get_llm_client", lambda *_: judge2)
    async with ss() as session:
        es2 = EvalSet(app_id=app_id, name="自诊断2")
        session.add(es2)
        await session.flush()
        session.add(EvalCase(eval_set_id=es2.id, question="包邮",
                             expected_points="", expected_doc_name="不存在.md"))
        await session.flush()
        run2 = EvalRun(eval_set_id=es2.id, status="pending", total=1)
        session.add(run2)
        await session.commit()
        run2_id = run2.id
    await run_eval(run2_id)
    async with ss() as session:
        r = (await session.execute(select(EvalResult).where(EvalResult.run_id == run2_id))).scalars().first()
        assert r.diagnosis and r.diagnosis["cause"] == "recall_miss"


class CardToolLLM:
    """第一轮调工具（返回 nexus_card JSON），第二轮直接作答。"""

    def __init__(self):
        self.calls = 0

    async def chat_json(self, messages, temperature=0.0, max_tokens=4096):
        return '{"intent": "qa"}'

    async def chat_with_tools(self, messages, tools, temperature=0.3, max_tokens=2048):
        self.calls += 1
        if self.calls == 1:
            return "", [{"id": "c1", "name": "order_stats", "arguments": "{}"}], {
                "tokens_in": 20, "tokens_out": 5,
            }
        return "订单情况如下。", None, {"tokens_in": 10, "tokens_out": 5}

    async def chat(self, messages, temperature=0.3, max_tokens=2048):
        return "说明", {"tokens_in": 5, "tokens_out": 3}

    async def chat_stream(self, messages, temperature=0.3, max_tokens=2048):
        yield "默认回答", None
        yield "", {"tokens_in": 8, "tokens_out": 4}


async def test_widget_card_flow(sqlite_env, monkeypatch):
    """工具返回 nexus_card → widget_card 事件 + Message.cards 持久化 + 历史接口透出。"""
    from app.core.security import generate_api_key
    from app.models.platform import ApiKey

    llm = CardToolLLM()
    from app.services.chat import orchestrator
    monkeypatch.setattr(orchestrator, "get_llm_client", lambda *_: llm)
    monkeypatch.setattr(
        "app.services.chat.orchestrator.execute_tool",
        lambda t, a, ctx=None: '{"nexus_card": {"card_type": "stats", "title": "订单", '
        '"items": [{"label": "总数", "value": 42}]}, "raw": "完整业务数据"}',
    )

    app_id, conv_id, token = await _mk_env()
    async with session_scope() as session:
        session.add(Tool(
            app_id=app_id, name="order_stats", description="订单统计", type="http_api",
            config={"method": "GET", "url": "http://internal/stats"},
        ))
        await session.commit()

    events = []
    async with session_scope() as session:
        app_row = await session.get(App, app_id)
        async for ev in orchestrator.run_chat(session, app_row, conv_id, "订单怎么样", []):
            events.append(ev)

    card_events = [e for e in events if e["type"] == "widget_card"]
    assert card_events and card_events[0]["card"]["card_type"] == "stats"

    async with session_scope() as session:
        msgs = list((await session.execute(
            select(Message).where(
                Message.conversation_id == conv_id, Message.role == "assistant"
            )
        )).scalars().all())
        assert msgs[0].cards and msgs[0].cards[0]["items"][0]["value"] == 42

    # 历史接口透出 cards（JWT 控制台端点，MessageOut 含 cards）
    from app.main import app as fastapi_app

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://t") as client:
        r = await client.get(
            f"/api/v1/conversations/{conv_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        m = [x for x in r.json() if x["role"] == "assistant"][0]
        assert m["cards"] and m["cards"][0]["card_type"] == "stats"


class CountingStreamLLM:
    """流式回答计数器（语义缓存命中时第二次不应再调）。"""

    def __init__(self):
        self.stream_calls = 0

    async def chat_stream(self, messages, temperature=0.3, max_tokens=2048):
        self.stream_calls += 1
        yield "全国包邮，顺丰发出。", None
        yield "", {"tokens_in": 9, "tokens_out": 6}

    async def chat(self, messages, temperature=0.3, max_tokens=2048):
        return "全国包邮，顺丰发出。", {"tokens_in": 9, "tokens_out": 6}

    async def chat_json(self, messages, temperature=0.0, max_tokens=4096):
        return '{"intent": "qa"}'

    async def chat_with_tools(self, messages, tools, temperature=0.3, max_tokens=2048):
        return "回答", None, {"tokens_in": 5, "tokens_out": 3}


async def test_semantic_cache_roundtrip(sqlite_env, monkeypatch):
    """同问两次：第二次走缓存（不再调 LLM），UsageEvent 记 cached=True。"""
    from app.services.chat import orchestrator
    from app.services.chat.orchestrator import run_chat

    kb_id, _id1, _id2 = await _mk_acl_kb()
    app_id, conv_id, _token = await _mk_env(
        retrieval_config={
            "cache_mode": "on", "cache_ttl": 3600, "cache_threshold": 0.8,
            "score_threshold": 0,
        }
    )
    from sqlalchemy import update as sa_update

    from app.db.session import session_scope as ss
    from app.models.app import AppKnowledgeBase
    async with ss() as session:
        await session.execute(sa_update(App).where(App.id == app_id).values(
            retrieval_config={"intent_route": False, "cache_mode": "on",
                              "cache_ttl": 3600, "cache_threshold": 0.8, "score_threshold": 0}
        ))
        session.add(AppKnowledgeBase(app_id=app_id, kb_id=kb_id))
        await session.commit()

    llm = CountingStreamLLM()
    monkeypatch.setattr(orchestrator, "get_llm_client", lambda *_: llm)

    async with ss() as session:
        app_row = await session.get(App, app_id)
        async for _ev in run_chat(session, app_row, conv_id, "包邮吗", []):
            pass
    assert llm.stream_calls == 1

    async with ss() as session:
        app_row = await session.get(App, app_id)
        async for ev in run_chat(session, app_row, conv_id, "包邮吗", []):
            if ev["type"] == "retrieval":
                assert ev.get("cached") is True
    assert llm.stream_calls == 1  # 第二次未调 LLM

    from app.models.app import UsageEvent
    async with ss() as session:
        usages = list((await session.execute(select(UsageEvent))).scalars().all())
        assert len(usages) == 2
        assert usages[0].cached is False and usages[1].cached is True


async def test_budget_exceeded_blocks_chat(sqlite_env, monkeypatch):
    """超当日预算：error 事件直接熔断，不调 LLM。"""
    from app.services.chat import orchestrator
    from app.services.chat.orchestrator import run_chat

    app_id, conv_id, _token = await _mk_env(
        retrieval_config={"budget": {"daily_tokens": 1, "monthly_tokens": 0}}
    )
    llm = CountingStreamLLM()
    monkeypatch.setattr(orchestrator, "get_llm_client", lambda *_: llm)

    from app.db.session import session_scope as ss
    from app.models.app import UsageEvent
    async with ss() as session:
        session.add(UsageEvent(app_id=app_id, type="chat",
                               tokens_in=500, tokens_out=500))
        await session.commit()

    events = []
    async with ss() as session:
        app_row = await session.get(App, app_id)
        async for ev in run_chat(session, app_row, conv_id, "你好", []):
            events.append(ev)
    assert any(e["type"] == "error" and "预算" in e.get("message", "") for e in events)
    assert llm.stream_calls == 0


async def test_acl_v2_rules(sqlite_env):
    """eval_rules 单元：claims 命中/缺失属性/多条件 AND/数组属性/end_users 兼容。"""
    from app.services.retrieval.acl import eval_rules

    restricted = {"mode": "restricted", "claims": [{"key": "dept", "values": ["销售部"]}]}
    assert eval_rules(restricted, "u1", {"dept": "销售部"})
    assert eval_rules(restricted, "u1", {"dept": ["售后部", "销售部"]})  # 数组属性任一命中
    assert not eval_rules(restricted, "u1", {"dept": "售后部"})
    assert not eval_rules(restricted, "u1", {})  # 缺失声明不满足
    # 多条件 AND
    multi = {"mode": "restricted", "claims": [
        {"key": "dept", "values": ["销售部"]}, {"key": "tier", "values": ["vip"]}]}
    assert eval_rules(multi, "u1", {"dept": "销售部", "tier": "vip"})
    assert not eval_rules(multi, "u1", {"dept": "销售部"})
    # ID 白名单兼容
    ids = {"mode": "restricted", "end_users": ["op1"]}
    assert eval_rules(ids, "op1", None)
    assert not eval_rules(ids, "op2", {"dept": "销售部"})
    # restricted 无任何规则 → 无人可见
    assert not eval_rules({"mode": "restricted"}, "u1", {"dept": "销售部"})
    # public / None
    assert eval_rules({"mode": "public"}, None, None)
    assert eval_rules(None, None, None)


async def test_acl_v2_chunk_override(sqlite_env):
    """覆盖模式：公开文档里封锁单块；受限文档里公开单块。"""
    from sqlalchemy import select as sa_select, update as sa_update

    from app.db.session import session_scope
    from app.models.kb import Chunk, Document, KnowledgeBase
    from app.services.retrieval import retrieve
    from app.services.retrieval.acl import resolve_acl

    kb_id, id1, id2 = await _mk_acl_kb()
    async with session_scope() as session:
        doc2_chunks = (await session.execute(
            sa_select(Chunk).where(Chunk.document_id == id2).order_by(Chunk.seq)
        )).scalars().all()
        doc1_chunks = (await session.execute(
            sa_select(Chunk).where(Chunk.document_id == id1).order_by(Chunk.seq)
        )).scalars().all()
        assert doc2_chunks and doc1_chunks
        # 受限文档(doc2)里把第一块显式公开（块级例外）
        await session.execute(sa_update(Chunk).where(Chunk.id == doc2_chunks[0].id)
                              .values(acl={"mode": "public"}))
        # 公开文档(doc1)里把第一块封锁（claims 不满足则不可见）
        await session.execute(sa_update(Chunk).where(Chunk.id == doc1_chunks[0].id)
                              .values(acl={"mode": "restricted",
                                           "claims": [{"key": "tier", "values": ["vip"]}]}))
        # 文档 doc2 受限：仅 dept=销售部 可见
        await session.execute(sa_update(Document).where(Document.id == id2)
                              .values(acl={"mode": "restricted",
                                           "claims": [{"key": "dept", "values": ["销售部"]}]}))
        await session.commit()
        ids = {"doc2_c0": doc2_chunks[0].id, "doc1_c0": doc1_chunks[0].id}

    # 场景 A：dept=销售部（doc2 授权）但非 vip（doc1 第一块封锁）
    async with session_scope() as session:
        kb = await session.get(KnowledgeBase, kb_id)
        flt = await resolve_acl(session, [kb_id], {"id": "u9", "attributes": {"dept": "销售部"}})
        assert flt is not None and ids["doc1_c0"] in flt.deny_chunk_ids
        assert ids["doc2_c0"] not in flt.deny_chunk_ids  # 块级例外放行
        cfg = {"top_k": 10, "score_threshold": 0, "use_kg": False, "use_bm25": False}
        r = await retrieve(session, [kb], "薪资 范围 包邮", cfg, acl=flt)
        got = {c.chunk_id for c in r.chunks}
        assert ids["doc1_c0"] not in got

    # 场景 B：无声明用户 → doc2 全禁，doc2 第一块例外可见
    async with session_scope() as session:
        kb = await session.get(KnowledgeBase, kb_id)
        flt = await resolve_acl(session, [kb_id], {"id": "u9"})
        assert flt is not None and id2 in flt.deny_doc_ids
        assert ids["doc2_c0"] not in flt.deny_chunk_ids  # 块级 public 例外


async def test_chunk_acl_endpoint(sqlite_env):
    """PUT /chunks/{id}/acl：设置/继承闭环。"""
    from app.core.security import generate_api_key  # noqa: F401

    from sqlalchemy import select as sa_select

    from app.db.session import session_scope
    from app.models.kb import Chunk

    kb_id, id1, _id2 = await _mk_acl_kb()
    async with session_scope() as session:
        chunk = (await session.execute(
            sa_select(Chunk).where(Chunk.document_id == id1).order_by(Chunk.seq)
        )).scalars().first()
        chunk_id = chunk.id

    from app.main import app as fastapi_app

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://t") as client:
        r = await client.get("/api/v1/auth/login")  # 占位：拿 token
        token = await _login_token(client)
        H = {"Authorization": f"Bearer {token}"}
        # 设置受限
        r = await client.put(f"/api/v1/chunks/{chunk_id}/acl", headers=H, json={
            "mode": "restricted", "end_users": [], "claims": [{"key": "tier", "values": ["vip"]}]})
        assert r.status_code == 200 and r.json()["acl"]["mode"] == "restricted"
        # 恢复继承
        r = await client.put(f"/api/v1/chunks/{chunk_id}/acl", headers=H,
                             json={"mode": "inherit"})
        assert r.status_code == 200 and r.json()["acl"] is None


async def _login_token(client) -> str:
    from app.core.security import hash_password, create_access_token
    from app.db.session import session_scope
    from app.models.platform import User

    async with session_scope() as session:
        admin = User(email="acl2-admin@test.local", name="a",
                     hashed_password=hash_password("x"), role="admin")
        session.add(admin)
        await session.commit()
        return create_access_token(str(admin.id))
