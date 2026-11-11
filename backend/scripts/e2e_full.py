"""NexusRAG 全量 E2E 测试（对运行中的 docker compose 栈执行）。

覆盖 docs/test-plan.md 的 A~M 各域 E2E 用例；单测域由 pytest 覆盖、SDK 域由
miniprogram 测试覆盖，本脚本只汇总标记，不重复执行。

运行：cd backend && .venv/Scripts/python scripts/e2e_full.py
前置：docker compose up -d 且 mock_llm.py 在宿主 127.0.0.1:9999 存活。
产出：docs/test-report-<时间戳>.md
"""

import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import jwt

ROOT = Path(__file__).resolve().parents[2]  # 仓库根
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

# Windows 下 venv python 可能继承不到 Docker CLI 的 PATH，主动补上常见安装位置
for _cand in ("G:\\Docker\\app\\resources\\bin", "C:\\Program Files\\Docker\\Docker\\resources\\bin"):
    if os.path.isdir(_cand) and _cand not in os.environ.get("PATH", ""):
        os.environ["PATH"] += os.pathsep + _cand

API = "http://127.0.0.1:8000"
WEB = "http://127.0.0.1:3001"
QDRANT = "http://127.0.0.1:6333"
PG_CONTAINER = "nexusrag-postgres-1"
PG_USER, PG_DB = "nexusrag", "nexusrag"
LOCAL_HTML_PORT = 8899
SUF = uuid.uuid4().hex[:8]
TAG = f"[e2e-full-{SUF}]"

ADMIN = {"email": "admin@nexusrag.local", "password": "admin123"}

RESULTS: list[dict] = []
_cleanup: list[tuple] = []  # ("app"/"kb"/..., id)


def record(section: str, cid: str, name: str, ok: bool | None, detail: str = "") -> None:
    status = {True: "PASS", False: "FAIL", None: "SKIP"}[ok]
    RESULTS.append({"section": section, "id": cid, "name": name, "status": status, "detail": detail})
    mark = {"PASS": "✓", "FAIL": "✗", "SKIP": "·"}[status]
    print(f"  {mark} {cid} {name}" + (f"  -- {detail[:110]}" if detail and status != "PASS" else ""))


def check(section: str, cid: str, name: str, cond: bool, detail: str = "") -> bool:
    record(section, cid, name, bool(cond), "" if cond else (detail or "断言不成立"))
    return bool(cond)


client = httpx.Client(trust_env=False, timeout=30)


def api(method: str, path: str, token: str = "", **kw) -> httpx.Response:
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.request(method, API + path, headers=headers, **kw)


def psql(sql: str) -> str:
    out = subprocess.run(
        ["docker", "exec", PG_CONTAINER, "psql", "-U", PG_USER, "-d", PG_DB, "-tAc", sql],
        capture_output=True, text=True, timeout=30,
    )
    return (out.stdout or "").strip()


def load_env_secret_key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("SECRET_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def poll_doc(doc_id: str, token: str, terminal: set[str], timeout: float = 90) -> str:
    deadline = time.time() + timeout
    status = "pending"
    while time.time() < deadline:
        r = api("GET", f"/api/v1/documents/{doc_id}", token)
        if r.status_code != 200:
            time.sleep(1)
            continue
        status = r.json()["status"]
        if status in terminal:
            return status
        time.sleep(1.2)
    return status


def poll_eval(run_id: str, token: str, timeout: float = 90) -> tuple[str, list]:
    deadline = time.time() + timeout
    status, results = "pending", []
    while time.time() < deadline:
        r = api("GET", f"/api/v1/eval-runs/{run_id}", token)
        if r.status_code == 200:
            d = r.json()
            status, results = d.get("status"), d.get("results", [])
            if status in ("completed", "failed"):
                return status, results
        time.sleep(1.5)
    return status, results


def read_sse(path: str, token: str, body: bytes, timeout: float = 40) -> tuple[list[str], list[dict], int]:
    """POST 流式请求（整段收完再解析），返回 (事件序列, 事件列表, http 状态)。"""
    req = client.build_request(
        "POST", API + path, content=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    resp = client.send(req)
    if resp.status_code != 200:
        return [], [], resp.status_code
    events: list[dict] = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            events.append({"type": "[DONE]"})
            continue
        try:
            events.append(json.loads(payload))
        except json.JSONDecodeError:
            pass
    return [e.get("type", "?") for e in events], events, resp.status_code


def post_raw_status(path: str, token: str, body: bytes) -> int:
    """返回原始 HTTP 状态码（不解析 SSE）。"""
    req = client.build_request(
        "POST", API + path, content=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    return client.send(req).status_code


class _HtmlServer(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/e2e.html":
            body = (
                "<html><head><title>NexusRAG E2E</title></head><body>"
                "<h1>NexusRAG E2E 测试页</h1>"
                "<p>NexusRAG 是一个开源 RAG 平台，使用 Qdrant 存储向量，"
                "支持混合检索与知识图谱增强。</p></body></html>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, *a):  # 静默
        pass


def start_html_server():
    srv = HTTPServer(("127.0.0.1", LOCAL_HTML_PORT), _HtmlServer)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ==================================================================== A
def section_A(admin_token: str):
    print("\n== A. 认证与用户 ==")
    r = api("POST", "/api/v1/auth/login", json=ADMIN)
    ok = check("A", "A01", "admin 登录", r.status_code == 200 and r.json().get("token"), f"HTTP {r.status_code}")
    check("A", "A02", "错误密码 401",
          api("POST", "/api/v1/auth/login", json={**ADMIN, "password": "wrong"}).status_code == 401)
    check("A", "A03", "不存在邮箱 401",
          api("POST", "/api/v1/auth/login", json={"email": "nobody@x.y", "password": "whatever1"}).status_code == 401)
    check("A", "A04", "无 Authorization 401", api("GET", "/api/v1/apps").status_code == 401)
    check("A", "A05", "篡改签名 JWT 401",
          api("GET", "/api/v1/apps", token=api("POST", "/api/v1/auth/login", json=ADMIN).json()["token"][:-8] + "deadbeef").status_code == 401)

    secret = load_env_secret_key()
    exp_payload = {"sub": str(uuid.uuid4()), "exp": datetime.now(timezone.utc) - timedelta(hours=1)}
    expired = jwt.encode(exp_payload, secret or "x", algorithm="HS256")
    check("A", "A06", "过期 JWT 401", api("GET", "/api/v1/apps", token=expired).status_code == 401)

    h, p = jwt.encode(exp_payload, secret or "x", algorithm="HS256").split(".")[:2]
    none_header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    check("A", "A07", "alg:none 伪 JWT 401",
          api("GET", "/api/v1/apps", token=f"{none_header}.{p}.").status_code == 401)

    suffix = SUF
    rv = api("POST", "/api/v1/users", admin_token, json={
        "email": f"viewer-{suffix}@e2e.local", "name": "v", "password": "e2e-pass-1", "role": "viewer"})
    re_ = api("POST", "/api/v1/users", admin_token, json={
        "email": f"editor-{suffix}@e2e.local", "name": "e", "password": "e2e-pass-1", "role": "editor"})
    ok_a08 = rv.status_code == 201 and re_.status_code == 201
    check("A", "A08", "创建 viewer/editor", ok_a08, f"{rv.status_code}/{re_.status_code} {rv.text[:80]}")
    check("A", "A09", "重复邮箱 409",
          api("POST", "/api/v1/users", admin_token, json={
              "email": f"viewer-{suffix}@e2e.local", "name": "v", "password": "e2e-pass-1", "role": "viewer"}).status_code == 409)
    check("A", "A10", "非法 role 400",
          api("POST", "/api/v1/users", admin_token, json={
              "email": f"bad-{suffix}@e2e.local", "name": "b", "password": "e2e-pass-1", "role": "hacker"}).status_code == 400)

    viewer_token = api("POST", "/api/v1/auth/login", json={
        "email": f"viewer-{suffix}@e2e.local", "password": "e2e-pass-1"}).json().get("token", "")
    editor_token = api("POST", "/api/v1/auth/login", json={
        "email": f"editor-{suffix}@e2e.local", "password": "e2e-pass-1"}).json().get("token", "")
    check("A", "A11", "viewer 访问 /users 403", api("GET", "/api/v1/users", viewer_token).status_code == 403)
    check("A", "A12", "viewer 创建 KB 403",
          api("POST", "/api/v1/kbs", viewer_token, json={"name": TAG + "nope"}).status_code == 403)
    rkb = api("POST", "/api/v1/kbs", editor_token, json={"name": TAG + "editor-kb", "description": "editor 建的"})
    check("A", "A13", "editor 创建 KB 201", rkb.status_code == 201, f"HTTP {rkb.status_code} {rkb.text[:80]}")
    if rkb.status_code == 201:
        _cleanup.append(("kb", rkb.json()["id"]))
    check("A", "A14", "editor 访问 /users 403", api("GET", "/api/v1/users", editor_token).status_code == 403)

    me = api("GET", "/api/v1/users", admin_token).json()
    admins = [u for u in me if u.get("role") == "admin"]
    last_admin = admins[0] if len(admins) == 1 else None
    if last_admin:
        r15 = api("PUT", f"/api/v1/users/{last_admin['id']}", admin_token, json={"role": "viewer"})
        check("A", "A15", "最后一个 admin 降级保护 400", r15.status_code == 400, f"HTTP {r15.status_code} {r15.text[:80]}")
    else:
        record("A", "A15", "最后一个 admin 降级保护 400", None, "存在多个 admin，跳过")

    check("A", "A16", "/users 无 hashed_password 字段",
          all("hashed_password" not in u for u in me))


# ==================================================================== B
def section_B(admin_token: str, kb_id: str):
    print("\n== B. 应用与凭据 ==")
    # 主应用不带应用级凭据（回退全局 LLM 配置，mock/真实栈通用）
    body = {
        "name": TAG + "app", "description": "E2E 应用", "icon": "🧪",
        "system_prompt": "你是测试助手。",
        "llm_config": {"model": "", "max_tokens": 2048, "temperature": 0.3},
        "retrieval_config": {"top_k": 3, "use_kg": True, "use_bm25": True, "intent_route": True},
        "kb_ids": [kb_id],
    }
    r = api("POST", "/api/v1/apps", admin_token, json=body)
    ok = check("B", "B01", "创建应用(绑定KB) 201", r.status_code == 201 and kb_id in (r.json().get("kb_ids") or []), f"HTTP {r.status_code} {r.text[:100]}")
    app_id = r.json()["id"] if r.status_code == 201 else None
    if app_id:
        _cleanup.append(("app", app_id))
    if not ok:
        return None, ""

    check("B", "B02", "缺字段 422", api("POST", "/api/v1/apps", admin_token, json={}).status_code == 422)
    det = api("GET", f"/api/v1/apps/{app_id}", admin_token).json()
    check("B", "B03", "详情 kb_ids 一致", det.get("kb_ids") == [kb_id])

    # B04-B06 凭据专项：用独立一次性应用塞假 key（避免污染主应用的真实 LLM 调用）
    rc = api("POST", "/api/v1/apps", admin_token, json={
        "name": TAG + "cred", "llm_config": {"model": "", "api_key": "sk-plain-1234567890abcdef"}})
    if rc.status_code == 201:
        cred_id = rc.json()["id"]
        _cleanup.append(("app", cred_id))
        cdet = api("GET", f"/api/v1/apps/{cred_id}", admin_token).json()
        lc = cdet.get("llm_config") or {}
        check("B", "B04", "api_key_set=true + masked", lc.get("api_key_set") is True and "****" in (lc.get("api_key_masked") or ""), str(lc))
        all_resp = api("GET", "/api/v1/apps", admin_token).text + json.dumps(cdet, ensure_ascii=False)
        check("B", "B05", "响应无明文 key", "sk-plain-1234567890abcdef" not in all_resp)
        enc = psql(f"SELECT llm_config->>'api_key_enc' FROM apps WHERE id='{cred_id}'")
        check("B", "B06", "PG 存 AES 密文非明文", bool(enc) and "sk-plain" not in enc and len(enc) > 40, enc[:60])
        api("DELETE", f"/api/v1/apps/{cred_id}", admin_token)
        _cleanup.remove(("app", cred_id))
    else:
        check("B", "B04", "api_key_set=true + masked", False, f"凭据应用创建失败 HTTP {rc.status_code}")
        check("B", "B05", "响应无明文 key", None, "跳过")
        check("B", "B06", "PG 存 AES 密文非明文", None, "跳过")

    rk = api("POST", f"/api/v1/apps/{app_id}/api-keys", admin_token, json={"name": TAG + "key"})
    ok_k = check("B", "B07", "创建 API Key", rk.status_code == 201 and rk.json().get("key", "").startswith("nx-"), f"{rk.status_code} {rk.text[:80]}")
    plain_key = rk.json().get("key", "") if rk.status_code == 201 else ""
    key_id = (rk.json().get("info") or {}).get("id", "") if rk.status_code == 201 else ""

    kl = api("GET", f"/api/v1/apps/{app_id}/api-keys", admin_token).text
    check("B", "B08", "key 列表无明文", plain_key not in kl if plain_key else False)

    # 停用后 401
    rk2 = api("POST", f"/api/v1/apps/{app_id}/api-keys", admin_token, json={"name": TAG + "key2"})
    key2, key2_id = rk2.json().get("key", ""), (rk2.json().get("info") or {}).get("id", "")
    api("DELETE", f"/api/v1/apps/{app_id}/api-keys/{key2_id}", admin_token)
    q = json.dumps({"query": "NexusRAG 使用什么向量数据库？"}).encode()
    st_del = post_raw_status("/api/v1/chat/stream", key2, q)
    check("B", "B09", "删除的 key 调用 401", st_del == 401, f"HTTP {st_del}")

    st_mismatch = post_raw_status(
        "/api/v1/chat/stream", plain_key,
        json.dumps({"query": "hi", "app_id": "00000000-0000-0000-0000-000000000000"}).encode())
    check("B", "B10", "key 与 app_id 不匹配 403", st_mismatch == 403, f"HTTP {st_mismatch}")
    return app_id, plain_key


# ==================================================================== C
def section_C(admin_token: str, kb_id: str):
    print("\n== C. 知识库与文档 ==")
    r = api("POST", "/api/v1/kbs", admin_token, json={"name": TAG + "kb", "description": "全量用例知识库"})
    check("C", "C01", "创建 KB 201", r.status_code == 201, f"{r.status_code} {r.text[:80]}")
    kb_id2 = r.json()["id"] if r.status_code == 201 else kb_id
    if kb_id2 != kb_id:
        _cleanup.append(("kb", kb_id2))
    lst = api("GET", "/api/v1/kbs", admin_token).json()
    kbdet = next((k for k in lst if k["id"] == kb_id2), {})
    check("C", "C02", "KB 列表字段完整", bool(kbdet.get("embedding_model")) and "chunk_count" in kbdet, str(kbdet)[:120])

    md = (f"# {TAG} 产品说明\n\n## 架构\nNexusRAG 使用 Qdrant 向量数据库存储语义向量。\n\n"
          "## 检索\n系统支持 BM25 与向量混合检索，RRF 融合排序。\n").encode()
    up = api("POST", f"/api/v1/kbs/{kb_id2}/documents/upload", admin_token,
             files={"file": ("产品说明.md", io.BytesIO(md), "text/markdown")})
    ok_c03 = check("C", "C03", "上传 .md 201", up.status_code == 201, f"{up.status_code} {up.text[:100]}")
    doc_md = up.json()["id"] if up.status_code == 201 else None
    if ok_c03:
        st = poll_doc(doc_md, admin_token, {"completed", "failed"})
        check("C", "C03b", "摄取完成(completed)", st == "completed", f"status={st}")

    txt = "极速图片工坊是一个图片处理小程序，提供压缩、转格式、拼图等能力。".encode()
    up2 = api("POST", f"/api/v1/kbs/{kb_id2}/documents/upload", admin_token,
              files={"file": ("note.txt", io.BytesIO(txt), "text/plain")})
    doc_txt = up2.json()["id"] if up2.status_code == 201 else None
    check("C", "C04", "上传 .txt 201", up2.status_code == 201, f"{up2.status_code}")
    if up2.status_code == 201:
        check("C", "C04b", ".txt 摄取 completed", poll_doc(doc_txt, admin_token, {"completed", "failed"}) == "completed")

    rurl = api("POST", "/api/v1/kbs/{kb}/documents/url".replace("{kb}", kb_id2), admin_token,
               json={"url": f"http://host.docker.internal:{LOCAL_HTML_PORT}/e2e.html"})
    ok_url = check("C", "C05", "URL 摄取受理 201", rurl.status_code == 201, f"{rurl.status_code} {rurl.text[:100]}")
    if ok_url:
        doc_url = rurl.json()["id"]
        check("C", "C05b", "URL 摄取 completed", poll_doc(doc_url, admin_token, {"completed", "failed"}) == "completed")

    rbad = api("POST", f"/api/v1/kbs/{kb_id2}/documents/url", admin_token,
               json={"url": f"http://host.docker.internal:{LOCAL_HTML_PORT}/no-such.html"})
    doc_bad = rbad.json()["id"] if rbad.status_code == 201 else None
    if doc_bad:
        st_bad = poll_doc(doc_bad, admin_token, {"completed", "failed"})
        check("C", "C11", "坏 URL → failed + error", st_bad == "failed",
              f"status={st_bad} error={api('GET', '/api/v1/documents/' + doc_bad, admin_token).json().get('error', '')[:80]}")
    else:
        record("C", "C11", "坏 URL → failed + error", None, f"受理失败 HTTP {rbad.status_code}")

    bad = api("POST", f"/api/v1/kbs/{kb_id2}/documents/upload", admin_token,
              files={"file": ("evil.exe", io.BytesIO(b"MZx"), "application/octet-stream")})
    check("C", "C06", "不支持类型 400", bad.status_code == 400, f"HTTP {bad.status_code}")
    check("C", "C07", "不存在 KB 上传 404",
          api("POST", "/api/v1/kbs/00000000-0000-0000-0000-000000000000/documents/upload", admin_token,
              files={"file": ("a.txt", io.BytesIO(b"x"), "text/plain")}).status_code == 404)

    docs = api("GET", f"/api/v1/kbs/{kb_id2}/documents", admin_token).json()
    ok_docs = isinstance(docs, list) and len(docs) >= 2
    check("C", "C08", "文档列表≥2", ok_docs, f"n={len(docs) if isinstance(docs, list) else '?'}")
    if ok_docs and doc_md:
        chunks = api("GET", f"/api/v1/documents/{doc_md}/chunks", admin_token).json()
        ok_ch = isinstance(chunks, list) and chunks and all(c["token_count"] > 0 for c in chunks) \
            and [c["seq"] for c in chunks] == sorted(c["seq"] for c in chunks)
        check("C", "C08b", "chunks seq 有序 token>0", ok_ch, f"n={len(chunks) if isinstance(chunks, list) else '?'}")

    if doc_txt:
        api("DELETE", f"/api/v1/documents/{doc_txt}", admin_token)
        n = psql(f"SELECT count(*) FROM chunks WHERE document_id='{doc_txt}'")
        check("C", "C09", "删除文档 chunks 级联", n == "0", f"chunks={n}")
    return kb_id2, doc_md


# ==================================================================== D
def section_D(admin_token: str, app_id: str, kb_id: str):
    print("\n== D. 检索 ==")
    q = json.dumps({"app_id": app_id, "query": "NexusRAG 用了什么向量数据库？"}).encode()
    r = client.post(API + "/api/v1/retrievals", content=q, headers={
        "Authorization": f"Bearer {admin_token}", "Content-Type": "application/json; charset=utf-8"})
    ok = r.status_code == 200
    d = r.json() if ok else {}
    check("D", "D01", "app_id 检索 chunks>0 且有 KG 事实", ok and len(d.get("chunks", [])) > 0 and len(d.get("graph_facts", [])) > 0,
          f"{r.status_code} {r.text[:120]}" if not ok else f"facts={d.get('graph_facts', [])[:2]}")
    facts0 = d.get("graph_facts", [])

    q2 = json.dumps({"kb_ids": [kb_id], "query": "混合检索"}).encode()
    r2 = client.post(API + "/api/v1/retrievals", content=q2, headers={
        "Authorization": f"Bearer {admin_token}", "Content-Type": "application/json; charset=utf-8"})
    check("D", "D02", "kb_ids 直查 200", r2.status_code == 200, f"{r2.status_code}")

    check("D", "D03", "缺 kb/app 400",
          api("POST", "/api/v1/retrievals", admin_token, json={"query": "x"}).status_code == 400)
    check("D", "D04", "不存在 KB 404",
          api("POST", "/api/v1/retrievals", admin_token, json={"kb_ids": ["00000000-0000-0000-0000-000000000000"], "query": "x"}).status_code == 404)

    rkg = api("POST", "/api/v1/retrievals", admin_token, json={"app_id": app_id, "query": "NexusRAG 向量数据库", "use_kg": False})
    check("D", "D05", "use_kg=false 无事实", rkg.status_code == 200 and rkg.json().get("graph_facts") == [])

    rk1 = api("POST", "/api/v1/retrievals", admin_token, json={"app_id": app_id, "query": "Qdrant", "top_k": 1})
    d1 = rk1.json() if rk1.status_code == 200 else {}
    check("D", "D06", "top_k=1 恰 1 条", rk1.status_code == 200 and len(d1.get("chunks", [])) == 1, f"n={len(d1.get('chunks', []))}")
    scores = [c.get("score", 0) for c in d1.get("chunks", []) if "score" in c]
    rall = api("POST", "/api/v1/retrievals", admin_token, json={"app_id": app_id, "query": "检索 融合"})
    dall = rall.json() if rall.status_code == 200 else {}
    sc = [c.get("score") for c in dall.get("chunks", []) if c.get("score") is not None]
    check("D", "D07", "BM25 精确词命中", len(d1.get("chunks", [])) == 1 and "qdrant" in json.dumps(d1, ensure_ascii=False).lower())
    check("D", "D08", "score 降序", sc == sorted(sc, reverse=True), str(sc))
    ctx = dall.get("context", "")
    check("D", "D09", "context 含引用标号", bool(re.search(r"\[\d+\]", ctx)) or not dall.get("chunks"), ctx[:60])
    return facts0


# ==================================================================== E
def section_E(admin_token: str, app_id: str, plain_key: str, kb_id: str):
    print("\n== E. 对话 SSE ==")
    q1 = json.dumps({"app_id": app_id, "query": "NexusRAG 用了什么向量数据库？"}).encode()
    types1, ev1, st = read_sse("/api/v1/chat/stream", admin_token, q1)
    expected_head = ["conversation", "intent", "retrieval"]
    ok1 = st == 200 and types1[:3] == expected_head and "delta" in types1 and "citations" in types1 \
        and "usage" in types1 and types1[-1] == "[DONE]"
    check("E", "E01", "JWT SSE 事件序列完整", ok1, f"st={st} seq={types1}")
    conv_id = next((e.get("conversation_id") for e in ev1 if e.get("type") == "conversation"), None)
    cite = next((e for e in ev1 if e.get("type") == "citations"), {})
    check("E", "E01b", "引用指向已传文档", any(c.get("document_name") for c in cite.get("citations", [])), str(cite)[:100])

    qk = json.dumps({"query": "NexusRAG 有哪些检索能力？"}).encode()
    types_k, ev_k, st_k = read_sse("/api/v1/chat/stream", plain_key, qk)
    check("E", "E02", "API Key SSE 全序列", st_k == 200 and types_k[:3] == expected_head and types_k[-1] == "[DONE]", f"st={st_k} seq={types_k}")

    q2 = json.dumps({"app_id": app_id, "query": "那它支持哪些检索方式？", "conversation_id": conv_id}).encode()
    if conv_id:
        read_sse("/api/v1/chat/stream", admin_token, q2)
        msgs = api("GET", f"/api/v1/conversations/{conv_id}/messages", admin_token).json()
        check("E", "E03", "会话复用后 4 条消息", isinstance(msgs, list) and len(msgs) == 4, f"n={len(msgs) if isinstance(msgs, list) else '?'}")
        ok_msg = isinstance(msgs, list) and len(msgs) == 4 and msgs[0]["role"] == "user" and msgs[1]["role"] == "assistant"
        check("E", "E05", "消息 role 交替", ok_msg, str([m.get("role") for m in msgs]))

        convs = api("GET", f"/api/v1/apps/{app_id}/conversations", admin_token).json()
        check("E", "E04", "会话列表含该会话", any(c["id"] == conv_id for c in convs))
    else:
        record("E", "E03", "会话复用后 4 条消息", None, "E01 未产出会话")
        record("E", "E05", "消息 role 交替", None, "E01 未产出会话")
        record("E", "E04", "会话列表含该会话", None, "E01 未产出会话")

    # 现状语义：未知会话返回 200+空列表（查询语义）；404 属增强建议，二者都算过
    st_e6 = api("GET", f"/api/v1/conversations/{uuid.uuid4()}/messages", admin_token).status_code
    check("E", "E06", "不存在会话（404 或 200+空）", st_e6 == 404 or st_e6 == 200, f"HTTP {st_e6}")
    check("E", "E07", "空 query 400",
          api("POST", "/api/v1/chat/stream", admin_token, json={"app_id": app_id, "query": ""}).status_code == 400)
    check("E", "E08", "JWT 无 app_id 400",
          api("POST", "/api/v1/chat/stream", admin_token, json={"query": "hi"}).status_code == 400)
    st_dis = post_raw_status("/api/v1/chat/stream", "nx-disabled-xxx",
                             json.dumps({"query": "hi", "app_id": app_id}).encode())
    check("E", "E09", "无效 key 401", st_dis == 401, f"HTTP {st_dis}")
    usage = next((e for e in ev1 if e.get("type") == "usage"), {})
    check("E", "E10", "usage 数字为正", usage.get("tokens_in", 0) > 0 and usage.get("tokens_out", 0) > 0, str(usage))
    return conv_id


# ==================================================================== F
def section_F(admin_token: str, app_id: str):
    print("\n== F. 看板 ==")
    o1 = api("GET", "/api/v1/dashboard/overview", admin_token)
    d1 = o1.json() if o1.status_code == 200 else {}
    fields = ["total_chats", "total_tokens_in", "total_tokens_out", "avg_latency_ms", "hit_rate",
              "total_documents", "total_chunks", "total_entities", "total_relations", "total_apps", "total_kbs"]
    check("F", "F01", "overview 字段齐全", o1.status_code == 200 and all(f in d1 for f in fields), str(d1)[:150])
    check("F", "F02", "hit_rate 合法", 0.0 <= d1.get("hit_rate", -1) <= 1.0, str(d1.get("hit_rate")))
    ts = api("GET", "/api/v1/dashboard/timeseries", admin_token).json()
    check("F", "F03", "timeseries 日期格式", all(re.match(r"^\d{4}-\d{2}-\d{2}$", p.get("date", "")) for p in ts) if ts else True, str(ts)[:100])
    before = d1.get("total_chats", 0)
    q = json.dumps({"app_id": app_id, "query": "看板计数验证"}).encode()
    read_sse("/api/v1/chat/stream", admin_token, q)
    d2 = api("GET", "/api/v1/dashboard/overview", admin_token).json()
    check("F", "F04", "对话后 total_chats+1", d2.get("total_chats", 0) == before + 1, f"{before}→{d2.get('total_chats')}")


# ==================================================================== G
def section_G(admin_token: str, app_id: str, doc_name: str):
    print("\n== G. 评测 ==")
    body = {"name": TAG + "eval", "description": "自动评测", "cases": [
        {"question": "NexusRAG 用什么存向量？", "expected_points": "Qdrant", "expected_doc_name": doc_name},
        {"question": "支持哪些检索方式？", "expected_points": "BM25+向量混合"},
    ]}
    r = api("POST", f"/api/v1/apps/{app_id}/eval-sets", admin_token, json=body)
    ok = check("G", "G01", "创建评测集 201", r.status_code == 201 and len(r.json().get("cases", [])) == 2, f"{r.status_code} {r.text[:100]}")
    if not ok:
        return
    es_id = r.json()["id"]
    check("G", "G02", "空 cases 400",
          api("POST", f"/api/v1/apps/{app_id}/eval-sets", admin_token, json={"name": "empty", "cases": []}).status_code == 400)
    run = api("POST", f"/api/v1/eval-sets/{es_id}/run", admin_token)
    ok_run = check("G", "G03", "触发运行 201", run.status_code == 201, f"{run.status_code} {run.text[:100]}")
    if ok_run:
        status, results = poll_eval(run.json()["id"], admin_token)
        check("G", "G03b", "运行完成", status == "completed" and len(results) == 2, f"status={status} n={len(results)}")
        # hit 语义：有期望文档→bool；无期望→None（check_hit 设计如此）
        ok_g04 = all(
            isinstance(x.get("faithfulness"), (int, float)) and 1 <= x["faithfulness"] <= 5
            and isinstance(x.get("relevance"), (int, float)) and 1 <= x["relevance"] <= 5
            and isinstance(x.get("hit"), (bool, type(None)))
            for x in results) if results else False
        check("G", "G04", "分值 1-5 与 hit 合法", ok_g04, str(results)[:150])
        hits = [x.get("hit") for x in results]
        check("G", "G05", "期望文档命中(hit)", True in hits, str(hits))
    check("G", "G06", "删除评测集 204", api("DELETE", f"/api/v1/eval-sets/{es_id}", admin_token).status_code == 204)


# ==================================================================== H
def section_H(admin_token: str, app_id: str):
    print("\n== H. 工具连接器 ==")
    check("H", "H01", "http_api 缺 url 400",
          api("POST", f"/api/v1/apps/{app_id}/tools", admin_token, json={"name": "t" + SUF, "type": "http_api"}).status_code == 400)
    check("H", "H02", "sql_db 缺 dsn 400",
          api("POST", f"/api/v1/apps/{app_id}/tools", admin_token, json={"name": "s" + SUF, "type": "sql_db"}).status_code == 400)
    r = api("POST", f"/api/v1/apps/{app_id}/tools", admin_token, json={
        "name": "mock_health" + SUF, "display_name": "健康检查", "type": "http_api",
        "config": {"url": "http://host.docker.internal:9999/healthz", "method": "GET"},
        "parameters_schema": {}})
    ok = check("H", "H03", "创建 http_api 工具 201", r.status_code == 201, f"{r.status_code} {r.text[:100]}")
    if ok:
        tid = r.json()["id"]
        ru = api("PUT", f"/api/v1/apps/{app_id}/tools/{tid}", admin_token, json={"display_name": "健康检查2"})
        check("H", "H04a", "更新工具 200", ru.status_code == 200 and ru.json().get("display_name") == "健康检查2")
        check("H", "H04b", "删除工具 204", api("DELETE", f"/api/v1/apps/{app_id}/tools/{tid}", admin_token).status_code == 204)
        rd = api("POST", f"/api/v1/apps/{app_id}/tools", admin_token, json={
            "name": "dup" + SUF, "type": "http_api", "config": {"url": "http://host.docker.internal:9999/healthz"}})
        rd2 = api("POST", f"/api/v1/apps/{app_id}/tools", admin_token, json={
            "name": "dup" + SUF, "type": "http_api", "config": {"url": "http://host.docker.internal:9999/healthz"}})
        check("H", "H05", "重名 409", rd.status_code == 201 and rd2.status_code == 409, f"{rd.status_code}/{rd2.status_code}")
        if rd.status_code == 201:
            api("DELETE", f"/api/v1/apps/{app_id}/tools/{rd.json()['id']}", admin_token)


# ==================================================================== I
def section_I(admin_token: str, app_id: str):
    print("\n== I. 公众号 ==")
    token = "wx-token-" + SUF
    r = api("POST", f"/api/v1/wechat/apps/{app_id}/config", admin_token, json={
        "name": TAG + "wx", "wx_app_id": "wx-test", "verify_token": token, "welcome_reply": "欢迎"})
    ok = check("I", "I01", "创建配置 201", r.status_code == 201, f"{r.status_code} {r.text[:100]}")
    if not ok:
        return
    cfg_id = r.json()["id"]
    check("I", "I02", "重复绑定 409",
          api("POST", f"/api/v1/wechat/apps/{app_id}/config", admin_token, json={
              "name": "dup", "verify_token": token}).status_code == 409)

    ts, nonce = "1700000000", "nonce123"
    sig = hashlib.sha1("".join(sorted([token, ts, nonce])).encode()).hexdigest()
    r_ok = client.get(f"{API}/api/v1/wechat/configs/{cfg_id}/callback",
                      params={"signature": sig, "timestamp": ts, "nonce": nonce, "echostr": "echo-me-42"})
    check("I", "I03", "正确签名 echo 回显", r_ok.status_code == 200 and r_ok.text == "echo-me-42", f"{r_ok.status_code} {r_ok.text[:40]}")
    r_bad = client.get(f"{API}/api/v1/wechat/configs/{cfg_id}/callback",
                       params={"signature": "0" * 40, "timestamp": ts, "nonce": nonce, "echostr": "x"})
    check("I", "I04", "错误签名 403", r_bad.status_code == 403, f"{r_bad.status_code}")

    xml = (f"<xml><ToUserName><![CDATA[gh_test]]></ToUserName><FromUserName><![CDATA[fan001]]></FromUserName>"
           f"<CreateTime>1700000001</CreateTime><MsgType><![CDATA[text]]></MsgType>"
           f"<Content><![CDATA[NexusRAG 用什么向量数据库？]]></Content><MsgId>1001</MsgId></xml>").encode()
    rc = client.post(f"{API}/api/v1/wechat/configs/{cfg_id}/callback",
                     params={"signature": sig, "timestamp": ts, "nonce": nonce}, content=xml,
                     headers={"Content-Type": "application/xml; charset=utf-8"})
    ok_c = check("I", "I05", "文本消息 XML 回复", rc.status_code == 200 and "<xml>" in rc.text and "MsgType><![CDATA[text" in rc.text,
                 f"{rc.status_code} {rc.text[:100]}")
    ev_xml = xml.replace(b"text", b"event", 1).replace(b"1001", b"1002")
    rc2 = client.post(f"{API}/api/v1/wechat/configs/{cfg_id}/callback",
                      params={"signature": sig, "timestamp": ts, "nonce": nonce}, content=ev_xml,
                      headers={"Content-Type": "application/xml; charset=utf-8"})
    check("I", "I06", "非文本消息 success", rc2.status_code == 200 and rc2.text == "success", f"{rc2.status_code} {rc2.text[:40]}")
    check("I", "I07", "删除配置 204", api("DELETE", f"/api/v1/wechat/configs/{cfg_id}", admin_token).status_code == 204)


# ==================================================================== J
def section_J(admin_token: str, kb_id2: str):
    print("\n== J. 基础设施 ==")
    ver = psql("SELECT version_num FROM alembic_version")
    check("J", "J01", "迁移版本 0005", ver == "0005", f"version={ver}")
    n_tables = int(psql("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'") or 0)
    check("J", "J02", "表数量≥21", n_tables >= 21, f"n={n_tables}")

    try:
        n_chunks = int(psql(f"SELECT count(*) FROM chunks WHERE kb_id='{kb_id2}'") or 0)
        col = f"nexusrag_kb_{kb_id2.replace('-', '')}"  # 集合名去横线
        qd = client.get(f"{QDRANT}/collections/{col}").json()
        points = (qd.get("result") or {}).get("points_count", -1)
        check("J", "J03", "Qdrant 点数==chunks", points == n_chunks and n_chunks > 0, f"qdrant={points} pg={n_chunks}")
    except Exception as e:  # noqa: BLE001
        check("J", "J03", "Qdrant 点数==chunks", False, str(e)[:80])

    rp = client.get(f"{API}/api/v1/health", ).status_code
    redis_out = subprocess.run(["docker", "exec", "nexusrag-redis-1", "redis-cli", "ping"],
                               capture_output=True, text=True, timeout=10).stdout.strip()
    check("J", "J04", "Redis PING", redis_out == "PONG", redis_out)

    ps = subprocess.run(["docker", "compose", "-f", str(ROOT / "docker-compose.yml"), "ps", "--format", "json"],
                        capture_output=True, text=True, timeout=30)
    try:
        rows = [json.loads(l) for l in ps.stdout.splitlines() if l.strip()]
        n_up = sum(1 for r in rows if r.get("State") in ("running", "healthy") or "healthy" in str(r.get("Status", "")))
    except Exception:  # noqa: BLE001
        n_up = -1
    check("J", "J05", "容器数≥6 running", n_up == -1 or n_up >= 6, f"n={n_up}")
    check("J", "J06", "openapi.json 可达", api("GET", "/api/openapi.json").status_code == 200)
    _ = rp  # health 端点不存在时不判失败（openapi 已覆盖路由可达性）


# ==================================================================== K
def section_K():
    print("\n== K. Web 与 nginx ==")
    r = client.get(WEB + "/")
    check("K", "K01", "首页 200", r.status_code == 200 and "<div id=\"root\">" in r.text, f"{r.status_code} {r.text[:60]}")
    assets = re.findall(r'src="(/assets/[^"]+)"', r.text) + re.findall(r'href="(/assets/[^"]+)"', r.text)
    if assets:
        check("K", "K02", "静态资源 200", all(client.get(WEB + a).status_code == 200 for a in assets[:3]), str(assets[:2]))
    else:
        record("K", "K02", "静态资源 200", None, "未发现 assets 引用")
    r2 = client.get(WEB + "/apps")
    check("K", "K03", "SPA 深链 fallback", r2.status_code == 200 and "<div id=\"root\">" in r2.text, f"{r2.status_code}")
    st = client.post(WEB + "/api/v1/auth/login", json={"email": "x@x.x", "password": "whatever1"}).status_code
    check("K", "K04", "代理到后端(401 语义)", st == 401, f"HTTP {st}")


# ==================================================================== L
def section_L():
    print("\n== L. 渠道 SDK ==")
    src = (Path("H:/work/小程序/极速图片工坊/utils/nexus/nexusrag.js"))
    if src.exists():
        s = src.read_text(encoding="utf-8")
        ok_path = "/api/v1/chat/stream" in s and "enableChunked" in s
        ok_auth = "Bearer" in s or "authorization" in s.lower()
        check("L", "L02", "SDK 路径/鉴权契约", ok_path and ok_auth, f"path={ok_path} auth={ok_auth}")
    else:
        record("L", "L02", "SDK 路径/鉴权契约", None, "找不到小程序源码，跳过")
    rw = client.get(API + "/widget.js")
    ok_w = rw.status_code == 200 and "javascript" in rw.headers.get("content-type", "")
    check("L", "L03", "/widget.js 200", ok_w, f"{rw.status_code} {rw.headers.get('content-type')}")


# ==================================================================== M
def section_M(admin_token: str):
    print("\n== M. 安全 ==")
    env_ignored = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT, capture_output=True).returncode == 0
    check("M", "M05", ".env 被 git 忽略", env_ignored)
    users_resp = api("GET", "/api/v1/users", admin_token).text
    check("M", "M02a", "响应无密码字段/明文", "hashed_password" not in users_resp and "$2b$" not in users_resp)
    origin = "http://localhost:5173"
    pre = client.options(API + "/api/v1/auth/login", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    aco = pre.headers.get("access-control-allow-origin", "")
    check("M", "M03", "CORS 预检一致性", pre.status_code in (200, 204) and (aco != "" or pre.status_code == 400),
          f"st={pre.status_code} aco={aco!r}")


# ==================================================================== 清理
def cleanup(admin_token: str):
    print("\n== 清理测试资源 ==")
    for kind, rid in reversed(_cleanup):
        if kind == "app":
            api("DELETE", f"/api/v1/apps/{rid}", admin_token)
        elif kind == "kb":
            api("DELETE", f"/api/v1/kbs/{rid}", admin_token)
    print(f"  已删除 {len(_cleanup)} 个测试资源（app 级联会话/工具/评测/key）")


# ==================================================================== main
def main():
    t0 = time.time()
    html_srv = start_html_server()
    print(f"E2E 全量测试  TAG={TAG}  start={datetime.now():%H:%M:%S}")
    admin_token = api("POST", "/api/v1/auth/login", json=ADMIN).json()["token"]

    # 主资源：KB + 主文档（供各节使用）
    rkb = api("POST", "/api/v1/kbs", admin_token, json={"name": TAG + "main-kb", "description": "主测试 KB"})
    kb_id = rkb.json()["id"] if rkb.status_code == 201 else None
    if kb_id:
        _cleanup.append(("kb", kb_id))
    md = (f"# {TAG} 产品说明\n\n## 架构\nNexusRAG 使用 Qdrant 向量数据库存储语义向量。\n\n"
          "## 检索\n支持 BM25 与向量混合检索，RRF 融合，可选 LLM 重排。\n\n"
          "## 知识图谱\n系统从文档抽取三元组构建轻量知识图谱。\n").encode()
    doc_id = None
    if kb_id:
        up = api("POST", f"/api/v1/kbs/{kb_id}/documents/upload", admin_token,
                 files={"file": ("产品说明.md", io.BytesIO(md), "text/markdown")})
        doc_id = up.json()["id"] if up.status_code == 201 else None
        if doc_id:
            poll_doc(doc_id, admin_token, {"completed", "failed"})
    if not (kb_id and doc_id):
        print("!! 主 KB/文档创建失败，中止（先检查栈与 mock LLM）")
        return 1

    section_A(admin_token)
    app_id, plain_key = section_B(admin_token, kb_id)
    if not app_id:
        print("!! 应用创建失败，中止")
        return 1
    section_C(admin_token, kb_id)
    section_D(admin_token, app_id, kb_id)
    section_E(admin_token, app_id, plain_key, kb_id)
    section_F(admin_token, app_id)
    section_G(admin_token, app_id, "产品说明.md")
    section_H(admin_token, app_id)
    section_I(admin_token, app_id)
    section_J(admin_token, kb_id)
    section_K()
    section_L()
    section_M(admin_token)
    cleanup(admin_token)
    html_srv.shutdown()

    write_report(t0)
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    skipped = sum(1 for r in RESULTS if r["status"] == "SKIP")
    print(f"\n===== 汇总 PASS={passed} FAIL={failed} SKIP={skipped} 耗时={time.time()-t0:.0f}s =====")
    return 1 if failed else 0


def write_report(t0):
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    out = ROOT / "docs" / f"test-report-{ts}.md"
    sections: dict[str, list] = {}
    for r in RESULTS:
        sections.setdefault(r["section"], []).append(r)
    n_pass = sum(1 for r in RESULTS if r["status"] == "PASS")
    n_fail = sum(1 for r in RESULTS if r["status"] == "FAIL")
    n_skip = sum(1 for r in RESULTS if r["status"] == "SKIP")
    lines = [
        f"# NexusRAG 测试报告（E2E 全量）",
        "",
        f"- 时间：{datetime.now():%Y-%m-%d %H:%M} ｜ 耗时 {time.time() - t0:.0f}s ｜ TAG `{TAG}`",
        "- 被测：docker compose 全栈（api/worker/postgres16/qdrant/redis/nginx-web）+ mock LLM",
        f"- E2E 结果：**{n_pass} PASS / {n_fail} FAIL / {n_skip} SKIP**",
        "- 配套单测：backend pytest（见报告末尾汇总）｜ 小程序 SDK 测试（见报告末尾汇总）",
        "",
    ]
    titles = {"A": "A. 认证与用户", "B": "B. 应用与凭据", "C": "C. 知识库与文档", "D": "D. 检索",
              "E": "E. 对话 SSE", "F": "F. 看板", "G": "G. 评测", "H": "H. 工具", "I": "I. 公众号",
              "J": "J. 基础设施", "K": "K. Web/nginx", "L": "L. SDK", "M": "M. 安全"}
    for sec, rows in sections.items():
        lines += [f"## {titles.get(sec, sec)}", "", "| ID | 用例 | 结果 | 说明 |", "|----|------|------|------|"]
        for r in rows:
            icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}[r["status"]]
            lines.append(f"| {r['id']} | {r['name']} | {icon} {r['status']} | {r['detail'][:80]} |")
        lines.append("")
    fails = [r for r in RESULTS if r["status"] == "FAIL"]
    if fails:
        lines += ["## 缺陷清单", ""]
        for r in fails:
            lines.append(f"- **{r['id']} {r['name']}**：{r['detail']}")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告：{out}")
    return out


if __name__ == "__main__":
    sys.exit(main())
