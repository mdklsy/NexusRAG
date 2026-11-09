"""本地 mock LLM/Embedding 服务（OpenAI 协议兼容）。

用途：没有真实 API Key 时，让 compose 全栈的摄取/对话链路可以端到端联调。
确定性向量（同文本同向量）、固定三元组抽取、固定流式回答。

启动：.venv/Scripts/python scripts/mock_llm.py   （监听 127.0.0.1:9999）
"""

import hashlib
import json
import math

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()

DIM = 1024  # 与 .env EMBEDDING_DIM 一致


def _vec(text: str) -> list[float]:
    raw = hashlib.md5(text.encode()).digest()
    out = []
    seed = raw[0] / 255.0
    for i in range(DIM):
        b = raw[i % len(raw)] / 255.0
        out.append(math.sin(seed * 3.14159 + b * 6.28 + i * 0.01))
    norm = math.sqrt(sum(x * x for x in out)) or 1.0
    return [x / norm for x in out]


def _answer_for(messages: list[dict]) -> str:
    last = messages[-1]["content"] if messages else ""
    if "意图" in last:
        return '{"intent": "qa"}'
    if "知识图谱信息抽取" in last:
        return json.dumps(
            {
                "triples": [
                    {
                        "source": {"name": "NexusRAG", "type": "产品"},
                        "predicate": "使用",
                        "target": {"name": "Qdrant", "type": "技术"},
                    },
                    {
                        "source": {"name": "Qdrant", "type": "技术"},
                        "predicate": "属于",
                        "target": {"name": "向量数据库", "type": "概念"},
                    },
                ]
            },
            ensure_ascii=False,
        )
    if "质量评审员" in last:
        return '{"faithfulness": 5, "relevance": 4}'
    return "根据资料，这是 mock 模型的回答。[1]"


@app.post("/v1/embeddings")
async def embeddings(req: Request):
    body = await req.json()
    texts = body.get("input", [])
    if isinstance(texts, str):
        texts = [texts]
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": i, "embedding": _vec(t)}
            for i, t in enumerate(texts)
        ],
        "model": body.get("model", "mock"),
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    messages = body.get("messages", [])
    content = _answer_for(messages)

    if body.get("stream"):
        async def gen():
            # 分三段流式吐出，最后带 usage
            for piece in [content[:10], content[10:20], content[20:]]:
                data = {
                    "id": "mock", "object": "chat.completion.chunk", "model": "mock",
                    "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            data = {
                "id": "mock", "object": "chat.completion.chunk", "model": "mock",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            }
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    return {
        "id": "mock", "object": "chat.completion", "model": body.get("model", "mock"),
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
    }


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "mock-llm"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9999, log_level="warning")
