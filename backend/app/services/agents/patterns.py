"""多 agent 协作模式：planner_workers（规划 → 分发 → 汇总）。

启用方式（应用 retrieval_config.agent_config，默认 mode=single 不走这里）：
    {
      "mode": "planner_workers",
      "workers": [
        {"name": "检索员", "system_prompt": "你是资料检索专家…", "tool_names": null, "max_rounds": 2},
        {"name": "查数员", "system_prompt": "你是业务数据专家…", "tool_names": ["query_order"], "max_rounds": 3}
      ],
      "max_subtasks": 4
    }

流程：规划（LLM 拆解子任务并指派 worker）→ 各 worker 带工具独立执行
（顺序执行，结果累积）→ 汇总 agent 结合原问题与全部产出生成最终回答（流式）。
"""

import json
from collections.abc import AsyncGenerator

from app.services.agents.runner import AgentSpec, run_agent
from app.services.tools import slugify

PLAN_PROMPT = """你是任务规划器。把用户问题拆解为可由下列专家代理执行的子任务。

可用代理：
{agents}

要求：
1. 每个子任务指派一个最合适的代理，instruction 写成自包含的执行指令（含必要的背景信息）
2. 子任务不超过 {max_subtasks} 个；问题简单到不需要拆解时，拆成 1 个交给最合适的代理
3. 只输出 JSON：{{"subtasks": [{{"title": "子任务标题", "worker": "代理名", "instruction": "执行指令"}}]}}

用户问题：{question}"""

SYNTH_SYSTEM_SUFFIX = """

# 多代理协作结果
你将看到多个代理代理执行产出的中间结论（可能重叠或冲突），请结合它们与【参考资料】
回答用户的原始问题：交叉验证、去重合并；结论冲突时说明差异及你采用的依据。
最终回答遵守系统提示词的全部规则（引用、格式、语言）。"""


def _build_specs(config: dict) -> dict[str, AgentSpec]:
    specs: dict[str, AgentSpec] = {}
    for w in config.get("workers") or []:
        name = str(w.get("name") or "").strip()
        if not name:
            continue
        specs[name] = AgentSpec(
            name=name,
            system_prompt=str(w.get("system_prompt") or ""),
            tool_names=w.get("tool_names") if isinstance(w.get("tool_names"), list) else None,
            max_rounds=max(1, min(int(w.get("max_rounds") or 2), 6)),
        )
    return specs


async def planner_workers(
    llm,
    messages: list[dict],
    tools: list,
    question: str,
    config: dict,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    ctx: dict | None = None,
) -> AsyncGenerator[dict]:
    """规划 → 顺序分发 → 汇总。事件协议见 runner 模块注释。"""
    workers = _build_specs(config)
    if not workers:
        yield {"type": "delta", "content": "⚠️ agent_config.workers 未配置，无法启用多代理模式。"}
        yield {"type": "usage", "tokens_in": 0, "tokens_out": 0}
        return

    max_subtasks = max(1, min(int(config.get("max_subtasks") or 4), 8))

    # 1. 规划
    roster = "\n".join(
        f"- {s.name}：{s.system_prompt.splitlines()[0] if s.system_prompt else '（无描述）'}"
        f"（可用工具：{'全部' if s.tool_names is None else '、'.join(s.tool_names)}）"
        for s in workers.values()
    )
    plan_raw = await llm.chat_json(
        PLAN_PROMPT.format(agents=roster, max_subtasks=max_subtasks, question=question),
        temperature=0.0,
    )
    try:
        subtasks = (json.loads(plan_raw) if isinstance(plan_raw, str) else plan_raw).get("subtasks") or []
    except (ValueError, AttributeError):
        subtasks = []
    subtasks = [
        st for st in subtasks
        if isinstance(st, dict) and st.get("worker") in workers
    ][:max_subtasks]
    yield {"type": "plan", "subtasks": [
        {"title": st.get("title"), "worker": st.get("worker")} for st in subtasks
    ]}

    # 2. 顺序执行各子任务
    outputs: list[dict] = []
    total = {"tokens_in": 0, "tokens_out": 0}
    for st in subtasks:
        spec = workers[st["worker"]]
        instruction = str(st.get("instruction") or st.get("title") or "")
        yield {"type": "agent_start", "agent": spec.name, "task": st.get("title") or instruction}
        wmsgs = [
            {"role": "system", "content": spec.system_prompt},
            {"role": "user", "content": instruction},
        ]
        out = ""
        async for ev in run_agent(
            llm, spec, wmsgs, tools, ctx=ctx,
            temperature=temperature, max_tokens=max_tokens,
        ):
            if ev["type"] == "delta":
                out += ev["content"]
            elif ev["type"] == "usage":
                total["tokens_in"] += ev.get("tokens_in", 0)
                total["tokens_out"] += ev.get("tokens_out", 0)
            else:
                yield ev
        yield {"type": "agent_done", "agent": spec.name, "summary": out[:200]}
        outputs.append({"worker": spec.name, "title": st.get("title") or "", "result": out})

    if not outputs:
        # 规划失败兜底：直接走主消息（检索上下文已在 messages 里）生成
        async for delta, u in llm.chat_stream(messages, temperature=temperature, max_tokens=max_tokens):
            if delta:
                yield {"type": "delta", "content": delta}
            if u:
                total = {"tokens_in": u.get("tokens_in", 0), "tokens_out": u.get("tokens_out", 0)}
        yield {"type": "usage", **total}
        return

    # 3. 汇总：原始对话上下文 + 各代理产出 → 流式最终答案
    synth_msgs = list(messages)
    synth_msgs[-1] = {
        "role": "user",
        "content": synth_msgs[-1]["content"]
        + "\n\n[多代理协作产出]\n"
        + "\n\n".join(f"### {o['worker']}（{o['title']}）\n{o['result'][:2000]}" for o in outputs)
        + "\n\n请综合以上产出回答我的原始问题。",
    }
    if synth_msgs and synth_msgs[0].get("role") == "system":
        synth_msgs[0] = {**synth_msgs[0], "content": synth_msgs[0]["content"] + SYNTH_SYSTEM_SUFFIX}
    async for delta, u in llm.chat_stream(synth_msgs, temperature=temperature, max_tokens=max_tokens):
        if delta:
            yield {"type": "delta", "content": delta}
        if u:
            total = {"tokens_in": total.get("tokens_in", 0) + u.get("tokens_in", 0),
                     "tokens_out": total.get("tokens_out", 0) + u.get("tokens_out", 0)}
    yield {"type": "usage", **total}
