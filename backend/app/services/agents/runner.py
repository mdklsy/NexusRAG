"""Agent 抽象与执行器：单 agent 循环 + 子 agent 委派（handoff）。

这是多 agent 协作的架构层。当前业务默认走单 agent（orchestrator._run_with_tools），
本模块保持同构的事件协议（tool_call/tool_result/delta/usage + agent 标注），
场景成熟后在应用配置里启用即可，不改动对话主链路。

事件协议（在单 agent 事件基础上追加字段，消费端向后兼容）：
- {"type": "agent_start", "agent", "task"}    进入某个 agent
- {"type": "agent_done", "agent", "summary"}  某个 agent 完成
- {"type": "tool_call"/"tool_result", ..., "agent"}  归属到执行的 agent
"""

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

from app.services.tools import ToolError, execute_tool, slugify, to_openai_tools


@dataclass
class AgentSpec:
    """一个可派发的 agent 角色。tool_names=None 表示可用全部工具。"""

    name: str
    system_prompt: str = ""
    tool_names: list[str] | None = None
    max_rounds: int = 2
    delegates: "dict[str, AgentSpec]" = field(default_factory=dict)


def _filter_tools(spec: AgentSpec, tools: list) -> list:
    if spec.tool_names is None:
        return list(tools)
    wanted = {slugify(n) for n in spec.tool_names}
    return [t for t in tools if slugify(t.name) in wanted]


async def run_agent(
    llm,
    spec: AgentSpec,
    messages: list[dict],
    tools: list,
    ctx: dict | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    agent_label: str | None = None,
    depth: int = 0,
) -> AsyncGenerator[dict]:
    """执行一个 agent：function calling 循环 + 可选子 agent 委派。

    委派以合成工具 handoff_to_<子agent> 暴露：主 agent 把任务文本交给子 agent，
    子 agent 独立上下文跑完后，结果作为工具结果回喂主 agent 继续决策。
    depth 防止委派环（>2 层拒绝）。label 用于事件归属；未显式给则用 spec.name。
    """
    label = agent_label or spec.name
    my_tools = _filter_tools(spec, tools)
    openai_tools = to_openai_tools(my_tools)
    tool_map = {slugify(t.name): t for t in my_tools}

    # 子 agent 委派工具（handoff 模式）。中文等名字 slugify 后可能撞名，
    # 生成名与派发用同一张映射表，不靠名字反推。
    delegate_specs = {} if depth >= 2 else (spec.delegates or {})
    handoff_map: dict[str, AgentSpec] = {}
    for idx, child in enumerate(delegate_specs.values(), 1):
        gen_name = "handoff_to_" + (slugify(child.name) or f"agent{idx}")
        if gen_name in handoff_map or gen_name in tool_map:
            gen_name = f"handoff_to_{idx}"
        handoff_map[gen_name] = child
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": gen_name,
                    "description": (
                        f"把任务转交给子代理「{child.name}」独立处理，返回其结论。"
                        "参数 task 用一段完整、自包含的任务描述（背景+要做什么）。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task": {"type": "string", "description": "自包含的任务描述"}
                        },
                        "required": ["task"],
                    },
                },
            }
        )

    msgs = list(messages)
    total = {"tokens_in": 0, "tokens_out": 0}
    max_rounds = max(1, int(spec.max_rounds))

    for round_no in range(max_rounds + 1):
        last_round = round_no == max_rounds
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
                yield {"type": "delta", "content": content, "agent": label}
            yield {"type": "usage", "tokens_in": total["tokens_in"], "tokens_out": total["tokens_out"], "agent": label}
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
            yield {"type": "tool_call", "name": tc["name"], "args": args, "agent": label}

            child = handoff_map.get(tc["name"])
            if child is not None:
                # 子 agent：独立上下文（其 system + 任务文本），完成后结果回喂
                child_label = f"{label}→{child.name}"
                yield {"type": "agent_start", "agent": child.name, "label": child_label, "task": args.get("task", "")}
                child_msgs = [
                    {"role": "system", "content": child.system_prompt},
                    {"role": "user", "content": str(args.get("task") or "完成分配的任务")},
                ]
                child_out, child_usage = "", {"tokens_in": 0, "tokens_out": 0}
                async for ev in run_agent(
                    llm, child, child_msgs, tools, ctx=ctx,
                    temperature=temperature, max_tokens=max_tokens,
                    agent_label=child_label, depth=depth + 1,
                ):
                    if ev["type"] == "delta":
                        child_out += ev["content"]
                    elif ev["type"] == "usage":
                        child_usage = ev
                    else:
                        yield ev
                total["tokens_in"] += child_usage.get("tokens_in", 0)
                total["tokens_out"] += child_usage.get("tokens_out", 0)
                yield {"type": "agent_done", "agent": child.name, "label": child_label, "summary": child_out[:200]}
                result, ok = child_out or "（子代理无输出）", True
            else:
                tool = tool_map.get(tc["name"])
                try:
                    if tool is None:
                        raise ToolError(f"未知工具 {tc['name']}")
                    result = execute_tool(tool, args, ctx)
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
                "agent": label,
            }
            msgs.append(
                {"role": "tool", "tool_call_id": tc["id"], "content": result[:4000]}
            )
