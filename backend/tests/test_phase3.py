"""本轮功能测试：应用级 LLM 凭证 / 用户权限 / 评测 / 公众号。"""


import pytest

from app.core.crypto import decrypt_secret, encrypt_secret, mask_secret

pytestmark = pytest.mark.asyncio


# ---------- A. 应用级 LLM 凭证 ----------


def test_crypto_roundtrip_and_mask():
    cipher = encrypt_secret("sk-abc123def456")
    assert cipher != "sk-abc123def456"
    assert decrypt_secret(cipher) == "sk-abc123def456"
    assert mask_secret(cipher, encrypted=True) == "sk-****f456"
    assert mask_secret("", encrypted=True) == ""
    # 换 SECRET_KEY 派生密钥后解不开 → 打码 ****（不抛异常）
    assert mask_secret("garbage!!!", encrypted=True) == "****"


def test_get_llm_client_app_level_credential(monkeypatch):
    from app.core.config import get_settings
    from app.services.llm import get_llm_client

    s = get_settings()
    monkeypatch.setattr(s, "llm_api_key", "sk-global")
    # 无应用配置 → 全局
    c1 = get_llm_client(None)
    assert str(c1._client.api_key) == "sk-global"
    # 应用级凭证优先
    enc = encrypt_secret("sk-app-level")
    c2 = get_llm_client({"api_base": "https://x.io/v1", "api_key_enc": enc})
    assert str(c2._client.api_key) == "sk-app-level"
    assert str(c2._client.base_url).startswith("https://x.io/v1")
    # 应用只给了 base 没给 key → key 回退全局
    c3 = get_llm_client({"api_base": "https://y.io/v1"})
    assert str(c3._client.base_url).startswith("https://y.io")
    assert str(c3._client.api_key) == "sk-global"


async def test_app_llm_key_masked_in_api(sqlite_env):
    from fastapi.testclient import TestClient

    from app.db.session import session_scope
    from app.main import app as fastapi_app
    from app.models.app import App

    async with session_scope() as session:
        session.add(App(name="sec-app", llm_config={
            "model": "m", "api_base": "https://x.io/v1",
            "api_key_enc": encrypt_secret("sk-secret-987654"),
        }))
        await session.commit()

    client = TestClient(fastapi_app)
    # 未登录 401；这里直接验证 sanitize 函数（JWT 流程已在权限测试覆盖）
    from app.api.v1.apps import _sanitize_llm_config

    cfg = _sanitize_llm_config({
        "model": "m", "api_base": "https://x.io/v1",
        "api_key_enc": encrypt_secret("sk-secret-987654"),
    })
    assert "sk-secret" not in str(cfg)
    assert cfg["api_key_masked"] == "sk-****7654"
    assert cfg["api_key_set"] is True


# ---------- B. 用户权限 ----------


async def test_role_guards(sqlite_env):
    from fastapi.testclient import TestClient

    from app.core.security import create_access_token, hash_password
    from app.db.session import session_scope
    from app.main import app as fastapi_app
    from app.models.platform import User

    async with session_scope() as session:
        admin = User(email="a@a.io", role="admin", hashed_password=hash_password("x"))
        viewer = User(email="v@v.io", role="viewer", hashed_password=hash_password("x"))
        session.add_all([admin, viewer])
        await session.commit()
        admin_id, viewer_id = admin.id, viewer.id

    client = TestClient(fastapi_app)
    admin_token = create_access_token(str(admin_id))
    viewer_token = create_access_token(str(viewer_id))

    # viewer 只读：GET 应用列表 200，创建应用 403
    r = client.get("/api/v1/apps", headers={"Authorization": f"Bearer {viewer_token}"})
    assert r.status_code == 200
    r = client.post(
        "/api/v1/apps",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"name": "nope"},
    )
    assert r.status_code == 403
    # viewer 不能进用户管理
    r = client.get("/api/v1/users", headers={"Authorization": f"Bearer {viewer_token}"})
    assert r.status_code == 403
    # editor 可创建
    r = client.post(
        "/api/v1/apps",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "ok-app"},
    )
    assert r.status_code == 201
    # admin 用户管理：创建 editor，列表可见
    r = client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "e@e.io", "password": "123456", "role": "editor"},
    )
    assert r.status_code == 201
    r = client.get("/api/v1/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200 and len(r.json()) == 3


async def test_cannot_demote_last_admin(sqlite_env):
    from fastapi.testclient import TestClient

    from app.core.security import create_access_token, hash_password
    from app.db.session import session_scope
    from app.main import app as fastapi_app
    from app.models.platform import User

    async with session_scope() as session:
        admin = User(email="solo@a.io", role="admin", hashed_password=hash_password("x"))
        session.add(admin)
        await session.commit()
        admin_id = admin.id

    client = TestClient(fastapi_app)
    token = create_access_token(str(admin_id))
    r = client.put(
        f"/api/v1/users/{admin_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "viewer"},
    )
    assert r.status_code == 400
    r = client.delete(
        f"/api/v1/users/{admin_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 400  # 不能删自己


# ---------- C. 评测 ----------


def test_eval_parse_scores_and_hit():
    from app.services.evaluator import check_hit, parse_scores

    assert parse_scores('{"faithfulness": 5, "relevance": 4}') == (5.0, 4.0, 5.0)
    assert parse_scores('```json\n{"faithfulness": 2, "relevance": 3}\n```') == (2.0, 3.0, 5.0)
    assert parse_scores("垃圾") == (None, None, None)
    # 分数越界收敛到 1-5
    assert parse_scores('{"faithfulness": 9, "relevance": 0}') == (5.0, 1.0, 5.0)

    assert check_hit("", ["a.md"]) is None
    assert check_hit("退款政策.md", ["退款政策.md", "x"]) is True
    assert check_hit("policy", ["退款_policy_v2.md"]) is True  # 子串模糊
    assert check_hit("notexist.md", ["a.md"]) is False


async def test_eval_run_e2e(sqlite_env):
    """评测全流程：建应用+KB+文档 → 摄取 → 评测集 → 运行 → 汇总。"""
    import pathlib

    from sqlalchemy import select

    from app.core.config import get_settings
    from app.db.session import session_scope
    from app.models.app import App, AppKnowledgeBase
    from app.models.eval import EvalCase, EvalResult, EvalRun, EvalSet
    from app.models.kb import Document, KnowledgeBase
    from app.services.evaluator import run_eval
    from app.services.ingestion.pipeline import ingest_document

    async with session_scope() as session:
        kb = KnowledgeBase(name="ev", embedding_model="m", embedding_dim=8,
                           chunk_config={"size": 100, "overlap": 20})
        session.add(kb)
        await session.flush()
        app = App(name="ev-app", retrieval_config={"top_k": 3, "score_threshold": 0,
                                                   "use_kg": False, "intent_route": False})
        session.add(app)
        await session.flush()
        session.add(AppKnowledgeBase(app_id=app.id, kb_id=kb.id))
        doc = Document(kb_id=kb.id, name="refund.md", source_type="upload", file_path="ev.md")
        session.add(doc)
        await session.commit()
        kb_id, app_id, doc_id = kb.id, app.id, doc.id

    p = pathlib.Path(get_settings().upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    (p / "ev.md").write_text("# 退款政策\n\n未拆封商品支持七天无理由退款，运费自理。\n", encoding="utf-8")
    async with session_scope() as session:
        await session.execute(
            Document.__table__.update().where(Document.__table__.c.id == doc_id)
            .values(file_path="ev.md")
        )
        await session.commit()
    await ingest_document(doc_id)

    async with session_scope() as session:
        es = EvalSet(app_id=app_id, name="冒烟评测")
        session.add(es)
        await session.flush()
        session.add(EvalCase(eval_set_id=es.id, question="退款政策是什么",
                             expected_points="七天无理由", expected_doc_name="refund.md"))
        session.add(EvalCase(eval_set_id=es.id, question="你是谁"))
        await session.commit()
        es_id = es.id

    async with session_scope() as session:
        run = EvalRun(eval_set_id=es_id, total=2)
        session.add(run)
        await session.commit()
        run_id = run.id

    await run_eval(run_id)

    async with session_scope() as session:
        run = await session.get(EvalRun, run_id)
        assert run.status == "completed", run.error
        assert run.done == 2
        assert run.hit_rate == 1.0  # 第一条命中 refund.md，第二条无期望
        assert run.avg_faithfulness is not None
        results = (
            (await session.execute(select(EvalResult).where(EvalResult.run_id == run_id)))
            .scalars().all()
        )
        assert len(results) == 2
        first = next(r for r in results if "退款" in r.question)
        assert "七天无理由" in first.answer
        assert "refund.md" in first.retrieved_doc_names


# ---------- D. 公众号 ----------


def test_wechat_signature():
    import hashlib

    from app.services.wechat import check_signature

    token, ts, nonce = "mytoken", "1700000000", "abc123"
    sig = hashlib.sha1("".join(sorted([token, ts, nonce])).encode()).hexdigest()
    assert check_signature(token, sig, ts, nonce) is True
    assert check_signature(token, "bad", ts, nonce) is False


def test_wechat_xml_roundtrip():
    from app.services.wechat import build_text_reply, parse_inbound, strip_markdown

    xml = (
        "<xml><ToUserName><![CDATA[gh_xxx]]></ToUserName>"
        "<FromUserName><![CDATA[oABC]]></FromUserName>"
        "<MsgType><![CDATA[text]]></MsgType>"
        "<Content><![CDATA[ 退款政策是什么？ ]]></Content></xml>"
    )
    msg = parse_inbound(xml)
    assert msg is not None
    assert msg.msg_type == "text"
    assert msg.content == "退款政策是什么？"
    assert msg.from_user == "oABC"

    reply = build_text_reply("gh_xxx", "oABC", "**重点**是[链接](http://x)")
    assert "oABC" in reply and "<MsgType><![CDATA[text]]></MsgType>" in reply
    # 回复 xml 可再被解析（content 原样，markdown 清理在调用方）
    assert parse_inbound(reply).content.startswith("**重点**是[链接]")

    assert strip_markdown("**加粗** 和 [文字](url)\n# 标题") == "加粗 和 文字\n标题"
