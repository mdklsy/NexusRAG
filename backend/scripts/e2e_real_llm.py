"""真实 LLM 端到端验证（填好 key 后一键运行）。

前置：
  1. .env 中填入真实 key：
       LLM_API_BASE=https://open.bigmodel.cn/api/paas/v4   （或任意 OpenAI 兼容地址）
       LLM_API_KEY=sk-xxxx
       LLM_MODEL=glm-4-flash                              （按你的服务商选）
       EMBEDDING_API_BASE / EMBEDDING_API_KEY / EMBEDDING_MODEL 同理（可与 LLM 同家）
  2. 重启让容器读到新配置：docker compose up -d api worker
  3. 运行：cd backend && .venv/Scripts/python scripts/e2e_real_llm.py

产出：docs/real-llm-report-<时间戳>.md，并清理本次创建的临时应用/知识库。
"""

import io
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
API = "http://127.0.0.1:8000"
SUF = uuid.uuid4().hex[:8]

DOC_TEXT = """# NexusRAG 产品说明

## 简介
NexusRAG 是一个开源的检索增强生成（RAG）与知识图谱平台，让使用者快速搭建智能客服与智能助理。

## 架构
- 向量存储使用 Qdrant
- 业务数据与知识图谱存储在 PostgreSQL
- 混合检索：BM25 关键词检索 + 语义向量检索，RRF 融合排序
- 知识图谱：从文档抽取三元组，检索时注入图事实

## 对话能力
- SSE 流式输出，支持引用溯源
- 应用级 LLM 凭据，支持 OpenAI 兼容协议
"""


def env() -> dict:
    out = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def main() -> int:
    e = env()
    llm_base, llm_key = e.get("LLM_API_BASE", ""), e.get("LLM_API_KEY", "")
    emb_base = e.get("EMBEDDING_API_BASE", "") or llm_base
    emb_key = e.get("EMBEDDING_API_KEY", "") or llm_key
    model = e.get("LLM_MODEL", "")
    emb_model = e.get("EMBEDDING_MODEL", "")

    results: list[tuple[str, bool, str]] = []

    def step(name: str, ok: bool, detail: str = ""):
        results.append((name, ok, detail))
        print(f"  {'✓' if ok else '✗'} {name}" + ("" if ok else f"  -- {detail[:120]}"))

    print("== 0. 配置检查 ==")
    mock_like = ("9999" in llm_base or "mock" in llm_key.lower()
                 or "9999" in emb_base or "mock" in emb_key.lower())
    if mock_like or not (llm_key and emb_key):
        print("✗ .env 仍是 mock 配置或缺少 key。请先填：")
        print("    LLM_API_BASE / LLM_API_KEY / LLM_MODEL")
        print("    EMBEDDING_API_BASE / EMBEDDING_API_KEY / EMBEDDING_MODEL")
        print("  然后：docker compose up -d api worker  （让容器读到新配置）")
        return 1
    step("配置非 mock", True, f"base={llm_base} model={model}")

    c = httpx.Client(trust_env=False, timeout=90)
    token = c.post(API + "/api/v1/auth/login",
                   json={"email": "admin@nexusrag.local", "password": "admin123"}).json()["token"]

    def api(method, path, **kw):
        return c.request(method, API + path, headers={"Authorization": f"Bearer {token}"}, **kw)

    print("== 1. 真实 embedding 摄取 ==")
    rkb = api("POST", "/api/v1/kbs", json={"name": f"[real-llm-{SUF}] kb"})
    kb_id = rkb.json()["id"]
    up = api("POST", f"/api/v1/kbs/{kb_id}/documents/upload",
             files={"file": ("产品说明.md", io.BytesIO(DOC_TEXT.encode()), "text/markdown")})
    if up.status_code != 201:
        step("上传", False, f"HTTP {up.status_code} {up.text[:100]}")
        return finish(results, None)
    doc_id = up.json()["id"]
    st = "pending"
    for _ in range(120):
        time.sleep(2)
        st = api("GET", f"/api/v1/documents/{doc_id}").json()["status"]
        if st in ("completed", "failed"):
            break
    step("真实向量摄取 completed", st == "completed",
         f"status={st} err={api('GET', f'/api/v1/documents/{doc_id}').json().get('error', '')[:80]}")

    print("== 2. 真实 LLM 对话（SSE + 引用） ==")
    rap = api("POST", "/api/v1/apps", json={
        "name": f"[real-llm-{SUF}] app", "system_prompt": "你是 NexusRAG 产品助手，仅依据资料回答。",
        "kb_ids": [kb_id],
        "retrieval_config": {"top_k": 3, "use_kg": True, "use_bm25": True, "intent_route": True}})
    app_id = rap.json()["id"]

    def sse(question: str) -> tuple[list[dict], int]:
        req = c.build_request("POST", API + "/api/v1/chat/stream",
                              content=json.dumps({"app_id": app_id, "query": question}).encode(),
                              headers={"Authorization": f"Bearer {token}",
                                       "Content-Type": "application/json; charset=utf-8"})
        resp = c.send(req)
        if resp.status_code != 200:
            return [], resp.status_code
        events = []
        for line in resp.text.splitlines():
            if line.startswith("data: ") and line != "data: [DONE]":
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
        return events, resp.status_code

    events, st = sse("NexusRAG 的向量存储和业务数据分别用什么？")
    deltas = "".join(x.get("content", "") for x in events if x.get("type") == "delta")
    cite = next((x for x in events if x.get("type") == "citations"), {})
    usage = next((x for x in events if x.get("type") == "usage"), {})
    step("SSE 流式 200", st == 200, f"HTTP {st}")
    step("回答非空且非 mock 话术", bool(deltas.strip()) and "mock" not in deltas.lower(), deltas[:80])
    step("回答命中事实(Qdrant/PostgreSQL)", ("qdrant" in deltas.lower()) and ("postgresql" in deltas.lower() or "pg" in deltas.lower()), deltas[:120])
    step("引用溯源", bool(cite.get("citations")), str(cite.get("citations", []))[:80])
    step("usage 真实 token 数", usage.get("tokens_in", 0) > 20 and usage.get("tokens_out", 0) > 10, str(usage))

    print("== 3. 真实 LLM 意图路由 ==")
    events2, _ = sse("你好呀，今天天气怎么样？")
    intent2 = next((x.get("intent") for x in events2 if x.get("type") == "intent"), "?")
    deltas2 = "".join(x.get("content", "") for x in events2 if x.get("type") == "delta")
    step("闲聊意图识别 + 直答", intent2 in ("chitchat", "chat", "smalltalk", "small_talk"), f"intent={intent2} answer={deltas2[:60]}")

    print("== 4. 评测链路（真实 LLM judge） ==")
    res = api("POST", f"/api/v1/apps/{app_id}/eval-sets", json={
        "name": f"real-{SUF}", "cases": [
            {"question": "NexusRAG 用什么存向量？", "expected_points": "Qdrant", "expected_doc_name": "产品说明.md"}]})
    es_id = res.json()["id"]
    run = api("POST", f"/api/v1/eval-sets/{es_id}/run")
    status, data = "pending", {}
    for _ in range(90):
        time.sleep(2)
        data = api("GET", f"/api/v1/eval-runs/{run.json()['id']}").json()
        status = data.get("status")
        if status in ("completed", "failed"):
            break
    r0 = (data.get("results") or [{}])[0]
    step("评测运行完成", status == "completed" and r0.get("faithfulness") is not None,
         f"status={status} f={r0.get('faithfulness')} rel={r0.get('relevance')}")
    step("judge 分数合理(≥3)", (r0.get("faithfulness") or 0) >= 3 and (r0.get("relevance") or 0) >= 3, str(r0)[:100])

    print("== 5. 清理 ==")
    api("DELETE", f"/api/v1/apps/{app_id}")
    api("DELETE", f"/api/v1/kbs/{kb_id}")
    print("  临时 app/kb 已删除")

    return finish(results, None)


def finish(results, _) -> int:
    n_pass = sum(1 for _, ok, _ in results if ok)
    n_fail = len(results) - n_pass
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    out = ROOT / "docs" / f"real-llm-report-{ts}.md"
    lines = [
        "# NexusRAG 真实 LLM 端到端报告", "",
        f"- 时间：{datetime.now():%Y-%m-%d %H:%M}",
        f"- 结果：**{n_pass} PASS / {n_fail} FAIL**", "",
        "| 检查项 | 结果 | 说明 |", "|--------|------|------|",
    ]
    for name, ok, detail in results:
        lines.append(f"| {name} | {'✅' if ok else '❌'} | {detail[:90]} |")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n===== 真实 LLM 验证 PASS={n_pass} FAIL={n_fail} =====\n报告：{out}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
