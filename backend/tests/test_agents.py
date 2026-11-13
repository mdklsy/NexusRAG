"""多 agent 架构回归：run_agent 工具循环、handoff 委派、planner_workers 全流程。

agents 模块默认关闭（对话主链路走单 agent），这里的测试保证架构层可用：
脚本化 LLM 驱动事件序列断言，不连任何外部服务。
"""

import pytest

from app.models.app import Tool

pytestmark = pytest.mark.asyncio


class ScriptedLLM:
    """chat_with_tools 按脚本逐轮返回；chat_json/chat_stream 供 planner_workers 用。"""

    def __init__(self, script, plan_json=None, stream_pieces=None):
        self.script = list(script)  # [(content, tool_calls), ...]
        self.plan_json = plan_json or "{}"
        self.stream_pieces = stream_pieces or ["汇总答案：", "检索与数据均就绪。"]
        self.streamed_msgs = None

    async def chat_json(self, messages, temperature=0.0, max_tokens=4096):
        return self.plan_json

    async def chat_with_tools(self, messages, tools, temperature=0.3, max_tokens=2048):
        if not self.script:
            return "（脚本耗尽）", None, {"tokens_in": 1, "tokens_out": 1}
        content, calls = self.script.pop(0)
        return content, calls, {"tokens_in": 10, "tokens_out": 5}

    async def chat_stream(self, messages, temperature=0.3, max_tokens=2048):
        self.streamed_msgs = messages
        for piece in self.stream_pieces:
            yield piece, None
        yield "", {"tokens_in": 30, "tokens_out": 12}


def _tool(name="search_kb", desc="搜索知识库"):
    return Tool(
        app_id=None, name=name, description=desc, type="http_api",
        config={"method": "GET", "url": "http://internal/search"},
        parameters_schema={},
    )


async def _collect(gen):
    return [ev async for ev in gen]


async def test_run_agent_tool_loop(monkeypatch):
    """第一轮调工具，第二轮作答；事件带 agent 归属。"""
    from app.services.agents import AgentSpec, run_agent
    import app.services.agents.runner as runner_mod

    seen = {}

    def fake_execute(tool, args, ctx=None):
        seen["tool"] = tool.name
        seen["args"] = args
        seen["ctx"] = ctx
        return "检索到 3 条结果"

    monkeypatch.setattr(runner_mod, "execute_tool", fake_execute)
    llm = ScriptedLLM([
        ("", [{"id": "c1", "name": "search_kb", "arguments": '{"query": "退款政策"}'}]),
        ("答案是七天无理由退款。", None),
    ])
    spec = AgentSpec(name="检索员", system_prompt="你是检索专家", max_rounds=2)
    events = await _collect(run_agent(llm, spec, [{"role": "user", "content": "退款政策?"}], [_tool()], ctx={"metadata": {"k": 1}}))

    types = [e["type"] for e in events]
    assert types == ["tool_call", "tool_result", "delta", "usage"]
    assert seen["tool"] == "search_kb" and seen["ctx"] == {"metadata": {"k": 1}}
    tr = events[1]
    assert tr["ok"] is True and "3 条" in tr["preview"]
    assert events[2]["content"] == "答案是七天无理由退款。"
    assert all(e.get("agent") == "检索员" for e in events)


async def test_run_agent_handoff_delegation(monkeypatch):
    """主 agent 委派子 agent：子代理独立执行并回喂结论。"""
    from app.services.agents import AgentSpec, run_agent
    import app.services.agents.runner as runner_mod

    monkeypatch.setattr(runner_mod, "execute_tool", lambda tool, args, ctx=None: "数据")
    # 脚本：第1轮(主)handoff → 子代理第1轮调工具 → 子代理第2轮结论 → 主第2轮最终答案
    # handoff 工具名用系统实际下发的生成名（中文 slugify 后为 tool，LLM 按下发名调用）
    from app.services.tools import slugify

    handoff_name = "handoff_to_" + slugify("查数员")
    llm = ScriptedLLM([
        ("", [{"id": "h1", "name": handoff_name, "arguments": '{"task": "查Q3销售额"}'}]),
        ("", [{"id": "c2", "name": "search_kb", "arguments": "{}"}]),
        ("Q3 销售额为 120 万。", None),
        ("综合：Q3 销售额 120 万。", None),
    ])
    child = AgentSpec(name="查数员", system_prompt="你是数据专家", max_rounds=2)
    parent = AgentSpec(name="队长", system_prompt="你是队长", delegates={"查数员": child})
    events = await _collect(run_agent(llm, parent, [{"role": "user", "content": "复盘Q3"}], [_tool()]))

    assert any(e["type"] == "agent_start" and e["agent"] == "查数员" for e in events)
    assert any(e["type"] == "agent_done" and "120 万" in e["summary"] for e in events)
    # 子代理的工具事件归属带链路标签
    child_tool = next(e for e in events if e["type"] == "tool_call" and e.get("agent", "").startswith("队长→"))
    assert child_tool["name"] == "search_kb"
    # 最终答案由主 agent 产出
    final = [e for e in events if e["type"] == "delta" and e["agent"] == "队长"]
    assert any("综合" in e["content"] for e in final)


async def test_planner_workers_end_to_end(monkeypatch):
    """规划 → worker 带工具执行 → 汇总流式输出；未知 worker 被过滤。"""
    from app.services.agents import planner_workers
    import app.services.agents.runner as runner_mod

    monkeypatch.setattr(runner_mod, "execute_tool", lambda tool, args, ctx=None: "命中资料")
    llm = ScriptedLLM(
        script=[
            ("", [{"id": "c1", "name": "search_kb", "arguments": "{}"}]),
            ("资料结论：支持七天无理由。", None),
        ],
        plan_json=(
            '{"subtasks": ['
            '{"title": "查政策", "worker": "检索员", "instruction": "检索退款政策"},'
            '{"title": "不存在", "worker": "幽灵代理", "instruction": "x"}'
            ']}'
        ),
    )
    config = {
        "mode": "planner_workers",
        "workers": [
            {"name": "检索员", "system_prompt": "你是检索专家", "tool_names": ["search_kb"], "max_rounds": 2},
        ],
    }
    messages = [
        {"role": "system", "content": "主系统提示词"},
        {"role": "user", "content": "退款政策是什么"},
    ]
    events = await _collect(planner_workers(
        llm, messages, [_tool()], "退款政策是什么", config,
        temperature=0.2, max_tokens=1024, ctx={"metadata": {}},
    ))

    types = [e["type"] for e in events]
    assert types[0] == "plan"
    # 幽灵代理被过滤，只剩 1 个子任务（plan 事件另带 depends_on 字段）
    assert [(x["title"], x["worker"]) for x in events[0]["subtasks"]] == [("查政策", "检索员")]
    assert "agent_start" in types and "agent_done" in types
    # 汇总是流式 delta 且系统提示词注入了协作规则
    deltas = "".join(e["content"] for e in events if e["type"] == "delta")
    assert "汇总答案" in deltas
    assert "多代理协作产出" in llm.streamed_msgs[-1]["content"]
    assert "多代理协作结果" in llm.streamed_msgs[0]["content"]
    usage = next(e for e in events if e["type"] == "usage")
    assert usage["tokens_in"] > 0


async def test_planner_workers_requires_workers():
    from app.services.agents import planner_workers

    events = await _collect(planner_workers(None, [], [], "q", {"mode": "planner_workers"}))
    assert "workers 未配置" in events[0]["content"]


async def test_planner_workers_parallel_waves():
    """波次并行：无依赖的并发先跑，依赖者等前置完成；汇总按规划顺序排列产出。"""
    from app.services.agents import planner_workers
    import app.services.agents.runner as runner_mod

    monkeypatch_mod = None
    import pytest as _pytest
    _mp = _pytest.MonkeyPatch()
    _mp.setattr(runner_mod, "execute_tool", lambda tool, args, ctx=None: "数据")
    try:
        # 三个 worker 各跑一轮直接作答；脚本弹出资序在波内不确定，靠结论文本区分
        llm = ScriptedLLM(
            script=[("结论甲", None), ("结论乙", None), ("结论丙", None)],
            plan_json=(
                '{"subtasks": ['
                '{"title": "查A", "worker": "w1", "instruction": "查A", "depends_on": []},'
                '{"title": "查B", "worker": "w2", "instruction": "查B", "depends_on": []},'
                '{"title": "析C", "worker": "w3", "instruction": "基于A和B分析", "depends_on": ["查A", "查B"]}'
                ']}'
            ),
        )
        config = {
            "mode": "planner_workers", "max_subtasks": 4,
            "parallel": True, "max_concurrency": 2,
            "workers": [
                {"name": "w1", "system_prompt": "查A的", "max_rounds": 1},
                {"name": "w2", "system_prompt": "查B的", "max_rounds": 1},
                {"name": "w3", "system_prompt": "分析C的", "max_rounds": 1},
            ],
        }
        messages = [{"role": "system", "content": "主提示词"}, {"role": "user", "content": "问题"}]
        events = await _collect(planner_workers(
            llm, messages, [_tool()], "问题", config, ctx={"metadata": {}},
        ))

        starts = [e["agent"] for e in events if e["type"] == "agent_start"]
        assert set(starts) == {"w1", "w2", "w3"}
        # 依赖者 w3 必须在 w1/w2 都开始之后才开跑
        i1, i2, i3 = starts.index("w1"), starts.index("w2"), starts.index("w3")
        assert i3 > i1 and i3 > i2
        # 汇总产出按规划顺序（甲、乙、丙），不随完成顺序乱
        assert "结论甲" in llm.streamed_msgs[-1]["content"]
        assert llm.streamed_msgs[-1]["content"].index("结论甲") < llm.streamed_msgs[-1]["content"].index("结论丙")
        # plan 事件带依赖信息
        plan = events[0]
        assert plan["subtasks"][2]["depends_on"] == ["查A", "查B"]
        usage = next(e for e in events if e["type"] == "usage")
        assert usage["tokens_in"] > 0
    finally:
        _mp.undo()


async def test_planner_workers_parallel_cycle_breaks():
    """依赖成环自动打破：两个互为依赖的子任务仍然全部执行（不挂死）。"""
    from app.services.agents import planner_workers
    import app.services.agents.runner as runner_mod
    import pytest as _pytest
    _mp = _pytest.MonkeyPatch()
    _mp.setattr(runner_mod, "execute_tool", lambda tool, args, ctx=None: "x")
    try:
        llm = ScriptedLLM(
            script=[("甲done", None), ("乙done", None)],
            plan_json=(
                '{"subtasks": ['
                '{"title": "T1", "worker": "w1", "instruction": "a", "depends_on": ["T2"]},'
                '{"title": "T2", "worker": "w2", "instruction": "b", "depends_on": ["T1"]}'
                ']}'
            ),
        )
        config = {
            "mode": "planner_workers", "parallel": True,
            "workers": [
                {"name": "w1", "system_prompt": "s1", "max_rounds": 1},
                {"name": "w2", "system_prompt": "s2", "max_rounds": 1},
            ],
        }
        messages = [{"role": "system", "content": "m"}, {"role": "user", "content": "q"}]
        events = await _collect(planner_workers(llm, messages, [_tool()], "q", config))
        dones = [e["agent"] for e in events if e["type"] == "agent_done"]
        assert sorted(dones) == ["w1", "w2"]
    finally:
        _mp.undo()


async def test_planner_workers_serial_mode_order():
    """parallel=false：严格串行，事件时序紧凑（start→done→下一个 start）。"""
    from app.services.agents import planner_workers
    import app.services.agents.runner as runner_mod
    import pytest as _pytest
    _mp = _pytest.MonkeyPatch()
    _mp.setattr(runner_mod, "execute_tool", lambda tool, args, ctx=None: "x")
    try:
        llm = ScriptedLLM(
            script=[("甲done", None), ("乙done", None)],
            plan_json=(
                '{"subtasks": ['
                '{"title": "T1", "worker": "w1", "instruction": "a"},'
                '{"title": "T2", "worker": "w2", "instruction": "b"}'
                ']}'
            ),
        )
        config = {
            "mode": "planner_workers", "parallel": False,
            "workers": [
                {"name": "w1", "system_prompt": "s1", "max_rounds": 1},
                {"name": "w2", "system_prompt": "s2", "max_rounds": 1},
            ],
        }
        messages = [{"role": "system", "content": "m"}, {"role": "user", "content": "q"}]
        events = await _collect(planner_workers(llm, messages, [_tool()], "q", config))
        seq = [(e["type"], e.get("agent")) for e in events if e["type"] in ("agent_start", "agent_done")]
        # 串行：w1 整段完成后 w2 才开始
        assert seq == [("agent_start", "w1"), ("agent_done", "w1"), ("agent_start", "w2"), ("agent_done", "w2")]
    finally:
        _mp.undo()
