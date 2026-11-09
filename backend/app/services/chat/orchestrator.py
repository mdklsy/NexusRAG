"""对话编排：意图路由 → 检索 → 流式生成/工具调用 → 引用溯源 → 落库计量。"""

import json
import time
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app import App, Conversation, Message, UsageEvent
from app.services.llm import get_llm_client
from app.services.retrieval import get_app_knowledge_bases, retrieve
from app.services.tools import (
    ToolError,
    execute_tool,
    get_app_tools,
    slugify,
    to_openai_tools,
)

TOOL_MAX_ROUNDS = 2

QA_SYSTEM_TEMPLATE = """{app_prompt}

你是通过检索增强（RAG）回答问题的助手。回答规则：
1. 优先依据下方【参考资料】回答；引用时标注来源编号，如 [1][2]
2. 可以结合【知识图谱事实】中列出的实体关系
3. 若参考资料与图谱都不足以回答，如实告知用户你没有相关资料，禁止编造
4. 用与用户提问相同的语言作答，简洁准确

【参考资料】
{context}"""

INTENT_PROMPT = """判断用户消息的意图类别：
- qa：需要查询知识库/资料，或需要查询业务系统数据（订单、库存、账号、余额等）才能回答的问题
- chat：闲聊、问候、或不需要任何资料即可回答的通用问题

输出 JSON：{{"intent": "qa"}} 或 {{"intent": "chat"}}

用户消息：{message}"""

NO_CONTEXT_NOTE = "\n\n（注意：本次检索未找到相关资料，若问题超出你的常识范围请如实告知。）"


def _build_messages(
    app: App,
    question: str,
    history: list[dict],
    context: str,
) -> list[dict]:
    base_prompt = app.system_prompt or f"你是「{app.name}」，一个专业的智能助手。"
    system = QA_SYSTEM_TEMPLATE.format(app_prompt=base_prompt, context=context or "（无）")
    if not context:
        system += NO_CONTEXT_NOTE
    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})
    return messages


async def _classify_intent(llm, question: str) -> str:
    try:
        raw = await llm.chat_json(
            [{"role": "user", "content": INTENT_PROMPT.format(message=question)}],
            max_tokens=50,
        )
        if '"chat"' in raw:
            return "chat"
        return "qa"
    except Exception:  # noqa: BLE001 意图判断失败按 qa 处理，宁可多检索
        return "qa"


async def _run_with_tools(
    llm, messages: list[dict], tools, temperature: float, max_tokens: int
) -> AsyncGenerator[dict]:
    """function calling 循环（非流式多轮）。

    产出事件：tool_call / tool_result / delta（最终答案整段）/ usage。
    工具执行失败不中断，错误文本回喂 LLM 令其向用户说明。
    """
    openai_tools = to_openai_tools(tools)
    tool_map = {slugify(t.name): t for t in tools}
    msgs = list(messages)
    total = {"tokens_in": 0, "tokens_out": 0}

    for round_no in range(TOOL_MAX_ROUNDS + 1):
        last_round = round_no == TOOL_MAX_ROUNDS  # 最后一轮强制直接作答
        content, tool_calls, u = await llm.chat_with_tools(
            msgs,
            [] if last_round else openai_tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        total["tokens_in"] += u.get("tokens_in", 0)
        total["tokens_out"] += u.get("tokens_out", 0)

        if not tool_calls or last_round:
            if content:
                yield {"type": "delta", "content": content}
            yield {"type": "usage", **total}
            return

        msgs.append(
            {
                "role": "assistant",
                "content": content or "",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in tool_calls
                ],
            }
        )
        for tc in tool_calls:
            try:
                args = json.loads(tc["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            yield {"type": "tool_call", "name": tc["name"], "args": args}
            tool = tool_map.get(tc["name"])
            try:
                if tool is None:
                    raise ToolError(f"未知工具 {tc['name']}")
                result = execute_tool(tool, args)
                ok = True
            except ToolError as e:
                result, ok = f"工具执行失败: {e}", False
            except Exception as e:  # noqa: BLE001
                result, ok = f"工具执行异常: {type(e).__name__}: {e}", False
            yield {
                "type": "tool_result",
                "name": tc["name"],
                "ok": ok,
                "preview": result[:200],
            }
            msgs.append(
                {"role": "tool", "tool_call_id": tc["id"], "content": result[:4000]}
            )


async def run_chat(
    session: AsyncSession,
    app: App,
    conversation_id: uuid.UUID,
    question: str,
    history: list[dict],
) -> AsyncGenerator[dict]:
    """产出 SSE 事件流。事件 type：intent / retrieval / delta / citations / usage / done。"""
    start = time.monotonic()
    config = app.retrieval_config or {}
    llm = get_llm_client(app.llm_config)

    # 1. 意图路由
    intent = "qa"
    if config.get("intent_route", True):
        intent = await _classify_intent(llm, question)
    yield {"type": "intent", "intent": intent}

    # 2. 检索
    context, citations, hit = "", [], False
    graph_fact_count = 0
    if intent == "qa":
        kbs = await get_app_knowledge_bases(session, app.id)
        if kbs:
            result = await retrieve(session, kbs, question, config)
            context, citations = result.build_context()
            hit = result.hit
            graph_fact_count = len(result.graph_facts)
            yield {
                "type": "retrieval",
                "chunks": len(result.chunks),
                "graph_facts": graph_fact_count,
                "hit": hit,
            }

    # 3. 生成：配置了业务工具 → function calling 循环；否则直接流式
    messages = _build_messages(app, question, history, context)
    temperature = float((app.llm_config or {}).get("temperature", 0.3))
    max_tokens = int((app.llm_config or {}).get("max_tokens", 2048))

    answer_parts: list[str] = []
    usage: dict = {}
    tools = await get_app_tools(session, app.id)

    if tools:
        async for event in _run_with_tools(
            llm, messages, tools, temperature, max_tokens
        ):
            if event["type"] == "delta":
                answer_parts.append(event["content"])
                yield {"type": "delta", "content": event["content"]}
            elif event["type"] == "usage":
                usage = event  # 事件本身即 {type, tokens_in, tokens_out}
            else:
                yield event
    else:
        async for delta, u in llm.chat_stream(
            messages, temperature=temperature, max_tokens=max_tokens
        ):
            if delta:
                answer_parts.append(delta)
                yield {"type": "delta", "content": delta}
            if u:
                usage = u
    answer = "".join(answer_parts)

    if citations:
        yield {"type": "citations", "citations": citations}
    if usage:
        yield {"type": "usage", **usage}

    # 4. 落库：消息 + 用量事件
    latency_ms = int((time.monotonic() - start) * 1000)
    conversation = await session.get(Conversation, conversation_id)
    session.add(
        Message(conversation_id=conversation_id, role="user", content=question)
    )
    session.add(
        Message(
            conversation_id=conversation_id,
            role="assistant",
            content=answer,
            citations=citations,
            tokens_in=usage.get("tokens_in", 0),
            tokens_out=usage.get("tokens_out", 0),
            latency_ms=latency_ms,
        )
    )
    session.add(
        UsageEvent(
            app_id=app.id,
            type="chat",
            tokens_in=usage.get("tokens_in", 0),
            tokens_out=usage.get("tokens_out", 0),
            latency_ms=latency_ms,
            hit=hit,
        )
    )
    if conversation and conversation.title == "新对话":
        conversation.title = question[:100]
    await session.commit()

    yield {
        "type": "done",
        "latency_ms": latency_ms,
        "message_id": "",
    }
