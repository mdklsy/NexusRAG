"""多 agent 协作架构层（默认关闭，见 patterns 模块注释的启用方式）。

- runner.run_agent：单 agent 执行器（工具循环 + handoff 委派），事件协议与
  orchestrator 单 agent 路径同构并追加 agent 归属字段，消费端向后兼容。
- patterns.planner_workers：规划 → 分发 → 汇总模式，由应用配置
  retrieval_config.agent_config.mode 启用；未启用时对话主链路零变化。
"""

from app.services.agents.patterns import planner_workers
from app.services.agents.runner import AgentSpec, run_agent

__all__ = ["AgentSpec", "planner_workers", "run_agent"]
