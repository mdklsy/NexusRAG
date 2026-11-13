"""多 agent 协作模式：planner_workers（规划 → 分发 → 汇总）。

启用方式（应用 retrieval_config.agent_config，默认 mode=single 不走这里）：
    {
      "mode": "planner_workers",
      "max_subtasks": 4,
      "parallel": true,          # 互不依赖的子任务按波次并发（默认 true；受限环境可关）
      "max_concurrency": 4,      # 单波最大并发代理数（1~8）
      "workers": [
        {"name": "检索员", "system_prompt": "你是资料检索专家…", "tool_names": null, "max_rounds": 2},
        {"name": "查数员", "system_prompt": "你是业务数据专家…", "tool_names": ["query_order"], "max_rounds": 3}
      ]
    }

流程：规划（LLM 拆解子任务、指派 worker、标注依赖）→ 按依赖拓扑分波，
波内并发（asyncio.gather + 信号量限流）、波间串行等待 → 汇总 agent 结合
原问题与全部产出生成最终回答（流式）。parallel=false 退化为纯串行。
"""

import asyncio
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
3. depends_on 写前置子任务的 title 数组（该任务必须等它们完成才有意义，如依赖查数结果的分析）；无依赖用空数组 []
4. 只输出 JSON：{{"subtasks": [{{"title": "子任务标题", "worker": "代理名", "instruction": "执行指令", "depends_on": []}}]}}

用户问题：{question}"""

SYNTH_SYSTEM_SUFFIX = """

# 多代理协作结果
你将看到多个代理代理执行产出的中间结论（可能重叠或冲突），请结合它们与【参考资料】
回答用户的原始问题：交叉验证、去重合并；结论冲突时说明差异及你采用的依据。
最终回答遵守系统提示词的全部规则（引用、格式、语言）。"""


def _build_specs(config: dict, tools: list) -> dict[str, AgentSpec]:
    """构建 worker spec；工具白名单与实际注册工具做交集校验，
    配置写错（如工具改名/删除）时记入 missing_tools，避免静默变成无工具代理。"""
    valid = {slugify(t.name) for t in tools}
    specs: dict[str, AgentSpec] = {}
    for w in config.get("workers") or []:
        name = str(w.get("name") or "").strip()
        if not name:
            continue
        names = w.get("tool_names") if isinstance(w.get("tool_names"), list) else None
        missing: list[str] = []
        if names is not None:
            wanted = [n for n in names if slugify(n)]
            missing = [n for n in wanted if slugify(n) not in valid]
            names = [n for n in wanted if slugify(n) in valid]
        specs[name] = AgentSpec(
            name=name,
            system_prompt=str(w.get("system_prompt") or ""),
            tool_names=names,
            max_rounds=max(1, min(int(w.get("max_rounds") or 2), 6)),
            missing_tools=missing,
        )
    return specs


def _normalize_plan(plan_raw, workers: dict[str, AgentSpec], max_subtasks: int):
    """解析规划 JSON → 校验后的子任务列表（含合法化后的 depends_on 索引）。"""
    try:
        data = json.loads(plan_raw) if isinstance(plan_raw, str) else plan_raw
        raw = data.get("subtasks") or []
    except (ValueError, AttributeError):
        raw = []
    subtasks = [
        st for st in raw
        if isinstance(st, dict) and st.get("worker") in workers
    ][:max_subtasks]
    # title → 索引（重复 title 取首个）
    idx_by_title: dict[str, int] = {}
    for i, st in enumerate(subtasks):
        idx_by_title.setdefault(str(st.get("title") or ""), i)
    deps: list[set[int]] = []
    for i, st in enumerate(subtasks):
        ds: set[int] = set()
        for d in st.get("depends_on") or []:
            j = idx_by_title.get(str(d))
            if j is not None and j != i:
                ds.add(j)
        deps.append(ds)
    return subtasks, deps


def _compute_waves(subtasks: list[dict], deps: list[set[int]]) -> list[list[int]]:
    """Kahn 分层：波内互不依赖可并发，波间串行等待；成环的剩余节点
    视为互不依赖塞进最后一波（保证必然终止）。"""
    remaining = set(range(len(subtasks)))
    done: set[int] = set()
    waves: list[list[int]] = []
    while remaining:
        wave = [i for i in sorted(remaining) if deps[i] <= done]
        if not wave:  # 依赖成环，打破：剩余的一起跑
            wave = sorted(remaining)
        waves.append(wave)
        done |= set(wave)
        remaining -= set(wave)
    return waves


async def _run_subtask(
    i: int, st: dict, spec: AgentSpec, llm, tools, ctx,
    temperature: float, max_tokens: int, queue: asyncio.Queue, wave: int,
    sem: asyncio.Semaphore, outputs: list, usages: list,
) -> None:
    """并行路径执行单个子任务：事件入队，产出写回 outputs[i]/usages[i]。

    信号量限并发；结束必发哨兵 None（主循环靠它计数收波），单代理失败
    不拖垮整体：异常转为失败结论文本进汇总，事件流照常闭合。"""
    await sem.acquire()
    try:
        instruction = str(st.get("instruction") or st.get("title") or "")
        await queue.put({"type": "agent_start", "agent": spec.name, "task": st.get("title") or instruction, "wave": wave})
        out = ""
        usage = {"tokens_in": 0, "tokens_out": 0}
        try:
            wmsgs = [
                {"role": "system", "content": spec.system_prompt},
                {"role": "user", "content": instruction},
            ]
            async for ev in run_agent(
                llm, spec, wmsgs, tools, ctx=ctx,
                temperature=temperature, max_tokens=max_tokens,
            ):
                if ev["type"] == "delta":
                    out += ev["content"]
                elif ev["type"] == "usage":
                    usage = {
                        "tokens_in": usage["tokens_in"] + ev.get("tokens_in", 0),
                        "tokens_out": usage["tokens_out"] + ev.get("tokens_out", 0),
                    }
                else:
                    await queue.put(ev)
            outputs[i] = out
            usages[i] = usage
            done_ev = {"type": "agent_done", "agent": spec.name, "summary": out[:200]}
        except Exception as e:  # noqa: BLE001 单代理失败不拖垮整体，结论留痕进汇总
            outputs[i] = f"（执行失败：{type(e).__name__}: {e}）"
            done_ev = {"type": "agent_done", "agent": spec.name, "summary": outputs[i][:200]}
        await queue.put({**done_ev, "wave": wave})
    finally:
        sem.release()
        await queue.put(None)  # 哨兵：主循环按 None 计数判波结束


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
    """规划 → （按依赖波次并行）分发 → 汇总。事件协议见 runner 模块注释。"""
    workers = _build_specs(config, tools)
    if not workers:
        yield {"type": "delta", "content": "⚠️ agent_config.workers 未配置，无法启用多代理模式。"}
        yield {"type": "usage", "tokens_in": 0, "tokens_out": 0}
        return

    max_subtasks = max(1, min(int(config.get("max_subtasks") or 4), 8))
    parallel = config.get("parallel", True) is not False
    max_concurrency = max(1, min(int(config.get("max_concurrency") or 4), 8))

    # 1. 规划
    roster = "\n".join(
        f"- {s.name}：{s.system_prompt.splitlines()[0] if s.system_prompt else '（无描述）'}"
        f"（可用工具：{'全部' if s.tool_names is None else ('、'.join(s.tool_names) if s.tool_names else '无')}"
        + (f"；⚠️ 配置的工具未找到：{'、'.join(s.missing_tools)}，该代理无法查数据，不要给它派需要调接口的任务" if s.missing_tools else "")
        + "）"
        for s in workers.values()
    )
    # chat_json 收消息列表（内部取 messages[-1] 追加 JSON 约束），不能传裸字符串
    plan_raw = await llm.chat_json(
        [{"role": "user", "content": PLAN_PROMPT.format(agents=roster, max_subtasks=max_subtasks, question=question)}],
        temperature=0.0,
    )
    subtasks, deps = _normalize_plan(plan_raw, workers, max_subtasks)
    yield {"type": "plan", "subtasks": [
        {
            "title": st.get("title"),
            "worker": st.get("worker"),
            "depends_on": [
                subtasks[j].get("title") for j in sorted(deps[i])
            ],
        }
        for i, st in enumerate(subtasks)
    ]}

    outputs: list[str | None] = [None] * len(subtasks)
    usages = [{"tokens_in": 0, "tokens_out": 0} for _ in subtasks]
    total = {"tokens_in": 0, "tokens_out": 0}

    # 2. 分发
    if parallel and len(subtasks) > 1:
        # 并行：按波次 gather，波内信号量限流；事件经队列回主循环保序下发
        waves = _compute_waves(subtasks, deps)
        queue: asyncio.Queue = asyncio.Queue()
        sem = asyncio.Semaphore(max_concurrency)
        for wave_no, wave in enumerate(waves):
            tasks = [
                asyncio.create_task(
                    _run_subtask(i, subtasks[i], workers[subtasks[i]["worker"]],
                                 llm, tools, ctx, temperature, max_tokens,
                                 queue, wave_no, sem, outputs, usages)
                )
                for i in wave
            ]
            pending = len(tasks)
            while pending:
                item = await queue.get()
                if item is None:
                    pending -= 1
                else:
                    yield item
            await asyncio.gather(*tasks)
    else:
        # 串行：逐个子任务（parallel=false 或只有单个子任务），保持事件时序紧凑
        for i, st in enumerate(subtasks):
            spec = workers[st["worker"]]
            yield {"type": "agent_start", "agent": spec.name, "task": st.get("title") or ""}
            out = ""
            async for ev in run_agent(
                llm, spec,
                [
                    {"role": "system", "content": spec.system_prompt},
                    {"role": "user", "content": str(st.get("instruction") or st.get("title") or "")},
                ],
                tools, ctx=ctx, temperature=temperature, max_tokens=max_tokens,
            ):
                if ev["type"] == "delta":
                    out += ev["content"]
                elif ev["type"] == "usage":
                    total["tokens_in"] += ev.get("tokens_in", 0)
                    total["tokens_out"] += ev.get("tokens_out", 0)
                else:
                    yield ev
            outputs[i] = out
            yield {"type": "agent_done", "agent": spec.name, "summary": out[:200]}

    for u in usages:
        total["tokens_in"] += u["tokens_in"]
        total["tokens_out"] += u["tokens_out"]

    if not any(o is not None for o in outputs):
        # 规划失败兜底：直接走主消息（检索上下文已在 messages 里）生成
        async for delta, u in llm.chat_stream(messages, temperature=temperature, max_tokens=max_tokens):
            if delta:
                yield {"type": "delta", "content": delta}
            if u:
                total = {"tokens_in": u.get("tokens_in", 0), "tokens_out": u.get("tokens_out", 0)}
        yield {"type": "usage", **total}
        return

    # 3. 汇总：原始对话上下文 + 各代理产出（按规划顺序）→ 流式最终答案
    synth_msgs = list(messages)
    synth_msgs[-1] = {
        "role": "user",
        "content": synth_msgs[-1]["content"]
        + "\n\n[多代理协作产出]\n"
        + "\n\n".join(
            f"### {subtasks[i]['worker']}（{subtasks[i].get('title') or ''}）\n{(outputs[i] or '')[:2000]}"
            for i in range(len(subtasks)) if outputs[i] is not None
        )
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
