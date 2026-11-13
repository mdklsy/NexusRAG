# 多 Agent 协作架构

> 状态：**架构先行，默认关闭**。对话主链路（单 agent + 工具循环）行为零变化；
> 有合适场景时在应用配置里启用即可，不需要改代码。

## 分层

```
orchestrator.run_chat（对话主链路：意图路由→记忆压缩→改写→检索→生成）
    └─ 生成段按 retrieval_config.agent_config.mode 分流：
        ├─ "single"（默认）→ _run_with_tools：单 agent function calling 循环
        └─ "planner_workers" → services/agents/patterns.planner_workers

services/agents/
    ├─ runner.AgentSpec   # agent 角色：名字 / 系统提示词 / 工具白名单 / 轮数 / 子代理
    ├─ runner.run_agent   # 执行器：工具循环 + handoff 委派（子代理独立上下文）
    └─ patterns.planner_workers  # 规划 → 分发 → 汇总
```

## 事件协议（SSE，向后兼容）

单 agent 事件（`tool_call` / `tool_result` / `delta` / `usage`）基础上：

| 事件 | 字段 | 说明 |
|---|---|---|
| `plan` | `subtasks:[{title,worker}]` | 规划器产出（旧消费端忽略未知 type，安全） |
| `agent_start` | `agent, label, task` | 进入某代理；`label` 是执行链（如 `队长→查数员`） |
| `agent_done` | `agent, label, summary` | 代理完成（摘要截 200 字） |
| `tool_call`/`tool_result` | …+`agent` | 归属到执行的代理 |

## 两种协作形态

**planner_workers（规划-分发-汇总）**：规划器把问题拆成子任务、指派给注册的
worker（各自系统提示词 + 工具白名单）并标注 `depends_on` 依赖，按依赖拓扑
**分波执行（波内并发、波间等待）**，最后由汇总 agent 结合原始上下文与全部
产出流式生成最终回答。

### 并行编排（依赖波次）

- 规划器为每个子任务输出 `depends_on`（前置子任务 title 数组）；无效/自引用依赖被忽略
- 波次按 Kahn 分层：第 1 波 = 无依赖任务，第 n 波 = 依赖全落在前 n-1 波的任务
- 依赖成环自动打破：剩余节点视为互不依赖塞进最后一波（保证必然终止）
- `parallel`（默认 true）：false 退化为严格串行（LLM 供应商并发配额受限的场景）
- `max_concurrency`（默认 4，钳 1~8）：同一波同时执行的代理数上限
- 汇总产出按**规划顺序**拼接（不随完成顺序乱）；单个代理失败转为失败结论进汇总，不拖垮整体
- 事件新增 `wave` 字段（agent_start/agent_done），消费端可忽略

**handoff 委派**（runner 内建）：agent 配置 `delegates` 后自动获得
`handoff_to_<子代理>` 工具，把自包含任务文本转交子代理独立执行，结论作为工具
结果回喂继续决策。深度限 2 层防委派环。

## 启用方式

```bash
# 编辑应用检索配置（控制台/API 均可）
PUT /api/v1/apps/{id}
{
  "retrieval_config": {
    "agent_config": {
      "mode": "planner_workers",
      "max_subtasks": 4,
      "parallel": true,
      "max_concurrency": 4,
      "workers": [
        {"name": "检索员", "system_prompt": "你是资料检索专家…", "max_rounds": 2},
        {"name": "查数员", "system_prompt": "你是业务数据专家…",
         "tool_names": ["query_order"], "max_rounds": 3}
      ]
    }
  }
}
```

- `tool_names` 缺省 = 全部工具；指定则只暴露白名单内的工具（按 slugify 后匹配）
- `max_subtasks` 钳 1..8；worker 的 `max_rounds` 钳 1..6
- 规划器会把未注册的 worker 指派过滤掉；规划失败兜底走主消息直接生成

## 设计取舍

- **依赖波次并行**：LLM 调用是墙钟大头，无依赖子任务并发收益真实；波内信号量限流兜住供应商并发配额；要严格时序可 `parallel: false`
- **委派 = 合成工具**而非独立消息通道：完全复用 function calling 协议，所有 LLM 提供商兼容
- **多 agent 不改变记忆/落库**：usage 累计入同一条 assistant 消息；中间代理产出不落 messages 表（避免污染上下文窗口）
