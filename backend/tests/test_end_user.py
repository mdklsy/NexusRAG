"""终端用户能力回归：业务参数模板注入、HMAC 票据、历史会话隔离。"""

import hashlib
import hmac as hmac_mod
import time

import pytest

from app.services.tools import ToolError, _render_business_templates


def test_render_templates_basic():
    ctx = {"end_user": {"id": "u123", "name": "张三"}, "metadata": {"token": "tk-abc"}}
    assert _render_business_templates("{{end_user.id}}", ctx) == "u123"
    assert _render_business_templates("Bearer {{meta.token}}", ctx) == "Bearer tk-abc"
    assert (
        _render_business_templates("x={{end_user.id}}&n={{end_user.name}}", ctx)
        == "x=u123&n=张三"
    )
    # 无模板原样返回
    assert _render_business_templates("plain", ctx) == "plain"


def test_render_templates_missing_raises():
    with pytest.raises(ToolError):
        _render_business_templates("{{meta.token}}", {})
    with pytest.raises(ToolError):
        _render_business_templates("{{end_user.id}}", {"metadata": {"a": 1}})
    with pytest.raises(ToolError):
        _render_business_templates("{{unknown.x}}", {"end_user": {"id": "u1"}})


async def test_widget_history_flow(sqlite_env):
    """票据验签 + 会话隔离：只看自己的、伪造签名 401、过期票据 401、跨用户拉会话 404。"""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select

    from app.core.security import generate_api_key
    from app.db.session import session_scope
    from app.main import app as fastapi_app
    from app.models.app import App, Conversation
    from app.models.platform import ApiKey

    secret = "sec-" + "y" * 16
    async with session_scope() as session:
        app = App(
            name="挂件历史测试", widget_config={"widget_secret": secret},
            retrieval_config={"intent_route": False},
        )
        session.add(app)
        await session.flush()
        session.add(Conversation(app_id=app.id, end_user_id="alice", title="A 的会话"))
        session.add(Conversation(app_id=app.id, end_user_id="bob", title="B 的会话"))
        raw, key_hash = generate_api_key()
        session.add(ApiKey(app_id=app.id, name="w", key_hash=key_hash, scope="chat"))
        await session.commit()
        app_id = app.id

    ts = int(time.time())
    sig_alice = hmac_mod.new(secret.encode(), f"alice:{ts}".encode(), hashlib.sha256).hexdigest()
    qs = f"end_user_id=alice&ts={ts}&sig={sig_alice}"

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        # 1. 只看到自己的会话
        r = await client.get(
            f"/api/v1/chat/conversations?{qs}",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 200
        assert [c["title"] for c in r.json()] == ["A 的会话"]

        # 2. 冒充他人（用 alice 的签名查 bob）→ 401
        r = await client.get(
            f"/api/v1/chat/conversations?end_user_id=bob&ts={ts}&sig={sig_alice}",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 401

        # 3. 过期票据 → 401
        old_ts = ts - 90000
        stale_sig = hmac_mod.new(secret.encode(), f"alice:{old_ts}".encode(), hashlib.sha256).hexdigest()
        r = await client.get(
            f"/api/v1/chat/conversations?end_user_id=alice&ts={old_ts}&sig={stale_sig}",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 401

    # 4. alice 拉自己会话的消息 OK；bob 的签名拉 alice 的会话 → 404
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(Conversation).where(
                        Conversation.end_user_id == "alice",
                        Conversation.app_id == app_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        alice_cid = rows[0].id

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.get(
            f"/api/v1/chat/conversations/{alice_cid}/messages?{qs}",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 200
        assert r.json() == {"messages": [], "has_more": False}

        sig_bob = hmac_mod.new(secret.encode(), f"bob:{ts}".encode(), hashlib.sha256).hexdigest()
        qs_bob = f"end_user_id=bob&ts={ts}&sig={sig_bob}"
        r = await client.get(
            f"/api/v1/chat/conversations/{alice_cid}/messages?{qs_bob}",
            headers={"Authorization": f"Bearer {raw}"},
        )
        assert r.status_code == 404


async def test_widget_messages_pagination(sqlite_env):
    """下拉懒加载分页：默认取最新一页；before 游标取更早；翻完 has_more=False。"""
    from datetime import datetime, timedelta, timezone as dt_tz

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select

    from app.core.security import generate_api_key
    from app.db.session import session_scope
    from app.main import app as fastapi_app
    from app.models.app import App, Conversation, Message
    from app.models.platform import ApiKey

    secret = "sec-" + "z" * 16
    async with session_scope() as session:
        app = App(
            name="挂件分页测试", widget_config={"widget_secret": secret},
            retrieval_config={"intent_route": False},
        )
        session.add(app)
        await session.flush()
        conv = Conversation(app_id=app.id, end_user_id="carol", title="分页会话")
        session.add(conv)
        await session.flush()
        # 35 条消息；created_at 是事务时间（同事务相同），必须显式错开保证时序
        base = datetime(2026, 11, 11, 12, 0, 0, tzinfo=dt_tz.utc)
        for i in range(35):
            session.add(
                Message(
                    conversation_id=conv.id,
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"消息{i}",
                    created_at=base + timedelta(seconds=i),
                )
            )
        raw, key_hash = generate_api_key()
        session.add(ApiKey(app_id=app.id, name="w", key_hash=key_hash, scope="chat"))
        await session.commit()
        conv_id = conv.id

    ts = int(time.time())
    sig = hmac_mod.new(secret.encode(), f"carol:{ts}".encode(), hashlib.sha256).hexdigest()
    qs = f"end_user_id=carol&ts={ts}&sig={sig}"

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        auth = {"Authorization": f"Bearer {raw}"}
        url = f"/api/v1/chat/conversations/{conv_id}/messages?{qs}"

        # 第一页：最新 30 条（升序），还有更早的
        r = await client.get(url, headers=auth)
        assert r.status_code == 200
        page1 = r.json()
        assert page1["has_more"] is True
        assert len(page1["messages"]) == 30
        assert page1["messages"][0]["content"] == "消息5"
        assert page1["messages"][-1]["content"] == "消息34"

        # 第二页：第一页最旧一条之前的 5 条，翻到底
        cursor = page1["messages"][0]["id"]
        r = await client.get(f"{url}&before={cursor}", headers=auth)
        page2 = r.json()
        assert page2["has_more"] is False
        assert [m["content"] for m in page2["messages"]] == [f"消息{i}" for i in range(5)]

        # limit 钳制与合法游标但跨会话的消息 → 404
        r = await client.get(f"{url}&before=00000000-0000-0000-0000-000000000000", headers=auth)
        assert r.status_code == 404
        r = await client.get(f"{url}&limit=0", headers=auth)
        assert r.status_code == 200 and len(r.json()["messages"]) == 1
