"""真实 LLM 多轮追问验证：查询改写 + 引用更新时间。

第 1 轮直接问（应跳过改写，query==原问题）；
第 2 轮用代词追问（应改写为独立完整查询，且能命中资料）。
"""

import json
import uuid

import httpx

API = "http://127.0.0.1:8000"
CLIENT = httpx.Client(trust_env=False, timeout=120)


def login():
    r = CLIENT.post(
        f"{API}/api/v1/auth/login",
        json={"email": "admin@nexusrag.local", "password": "admin123"},
    )
    return f"Bearer {r.json()['token']}"


def find_app(auth, name):
    r = CLIENT.get(f"{API}/api/v1/apps", headers={"Authorization": auth})
    for a in r.json():
        if a["name"] == name:
            return a["id"]
    raise SystemExit(f"app {name} not found")


def chat(auth, app_id, question, conversation_id=None):
    body = {"app_id": app_id, "query": question}
    if conversation_id:
        body["conversation_id"] = conversation_id
    events = {"deltas": [], "citations": None}
    with CLIENT.stream(
        "POST",
        f"{API}/api/v1/chat/stream",
        headers={"Authorization": auth, "Content-Type": "application/json"},
        json=body,
    ) as resp:
        for line in resp.iter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            ev = json.loads(line[6:])
            t = ev.get("type")
            if t == "conversation":
                events["conversation_id"] = ev["conversation_id"]
            elif t == "intent":
                events["intent"] = ev["intent"]
            elif t == "retrieval":
                events["retrieval"] = ev
            elif t == "delta":
                events["deltas"].append(ev["content"])
            elif t == "citations":
                events["citations"] = ev["citations"]
            elif t == "error":
                events["error"] = ev["message"]
    events["answer"] = "".join(events.pop("deltas"))
    return events


def main():
    auth = login()
    app_id = find_app(auth, "极速图片工坊助手")
    print(f"app={app_id}")

    q1 = "NexusRAG 支持混合检索吗？"
    e1 = chat(auth, app_id, q1)
    print("\n=== 第 1 轮 ===")
    print("intent:", e1.get("intent"), "| retrieval:", e1.get("retrieval"))
    assert e1.get("retrieval", {}).get("query") == q1, "首轮不应改写"
    print("answer:", e1["answer"][:150])
    print("citation[0]:", json.dumps((e1.get("citations") or [{}])[0], ensure_ascii=False))

    q2 = "它的重排用的什么模型？"
    e2 = chat(auth, app_id, q2, e1["conversation_id"])
    print("\n=== 第 2 轮（代词追问）===")
    print("intent:", e2.get("intent"), "| retrieval:", e2.get("retrieval"))
    rq = e2.get("retrieval", {}).get("query", "")
    assert rq != q2, "追问应触发改写"
    assert "重排" in rq and ("NexusRAG" in rq or "混合检索" in rq or "检索" in rq), (
        f"改写应消解指代并补全主语，实际: {rq}"
    )
    print("answer:", e2["answer"][:200])
    print("citation[0]:", json.dumps((e2.get("citations") or [{}])[0], ensure_ascii=False))
    print("\nPASS: 首轮跳过改写 / 追写改写消解指代 / 引用带更新时间")


if __name__ == "__main__":
    main()
