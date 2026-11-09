# 集成案例：（Web 管理台 + 业务系统打通）

> 真实案例：Node.js 任务管理系统（自动化）接入 NexusRAG：
> ① Web 端挂 AI 助手聊天页；② 把业务 API 注册为 NexusRAG 工具，
> 让大模型在对话中**自动调用**（function calling），实现「向下打通业务系统」。

## 架构

```
server/public/（AI 助手聊天页，fetch SSE 流式）
        │
        ▼
NexusRAG /api/v1/chat/stream
   │ 意图路由 → 检索 → 生成
   │ LLM 决定调用哪个工具（function calling 循环，最多 2 轮）
        │
        ▼ execute_tool (HTTP)
server/routes/（业务测试接口，只读）
   │ 查 sqlite（tasks / receipts / invite_orders）
   ▼
结果回喂 LLM → 组织成自然语言回答
```

## 第一步：暴露业务接口（`server/routes/`）

5 个只读测试接口，模拟「业务系统 API」：

| 接口 | 用途 | 演示的工具形态 |
|---|---|---|
| `GET /api/nexus/ping?msg=` | 回声探测 | 查询参数 |
| `GET /api/nexus/time` | 服务器时间 | 零参数 |
| `GET /api/nexus/stats` | 任务全局统计 | 零参数（LLM 主动调用） |
| `GET /api/nexus/tasks/{task_id}` | 单任务详情 | 路径参数 |
| `GET /api/nexus/orders?order_no=` | 订单发货状态 | 查询参数 |

注册进 `server.mjs` 的 `ROUTE_GROUPS`（`staticRoutes` 之前）即可。

## 第二步：在 NexusRAG 注册为工具

控制台 → 应用配置 → 业务工具 → 添加（或调 API）：

| 函数名 | 类型 | URL | 给 LLM 的描述（关键！） |
|---|---|---|---|
| `` | http_api | `http:///api/nexus/stats` | 统计邀请任务整体进度：总数/各状态分布/成功回执数。用户问任务整体情况时调用 |
| `get_invite_task` | http_api | `.../api/nexus/tasks/{task_id}` | 按任务ID查详情：状态/目标数/完成数/当前步骤。参数 task_id=数字ID |
| `query_order` | http_api | `.../api/nexus/orders` | 按订单号查发货状态。参数 order_no=订单号 |

> **描述写法决定调用准确率**：写清「什么时候调用 + 每个参数的含义」，
> LLM 靠这段文字决定是否调用、怎么填参数。

## 第三步：Web 聊天页（`server/public/`）

独立页面 `/nexus`，右上角 ⚙ 配置 NexusRAG 地址与 API Key（存 localStorage）。
对话走 `fetch` + `ReadableStream` 解析 SSE，支持：

- 流式打字机输出
- `⚙ 工具名` 调用徽标（成功 ✓ / 失败 ✗ 着色）
- 引用溯源标签

想全站挂角标？在任意页面加一行（挂件 Key）：

```html
<script src="http://nexusrag-host/widget.js" data-key="nx-挂件Key" defer></script>
```

## 实测效果

```
用户：现在任务跑得怎么样？
LLM：→ 自动调用  →
回答：当前共 1 个任务，全部完成（completed: 1）；累计成功回执 1 条，今日新增 1 条。

用户：查一下任务 1 的状态
LLM：→ 自动调用 get_invite_task(task_id="1") →
回答：任务 1 已完成，目标 3 件，成功回执 1 件。

用户：订单 TEST-001 发货了吗？
LLM：→ 自动调用 query_order(order_no="TEST-001") →
回答：订单 TEST-001 关联任务 1，状态已完成，2 件中已完成 1 件。
```

*（以上为工具执行链路实测；「LLM 何时决定调用」需要配置真实 LLM API Key 后生效）*

## 踩坑记录（对其他集成者有价值）

1. **系统代理劫持内网请求**：工具执行器默认 `trust_env=False` 直连
   （业务 API 多为内网地址，Windows 系统代理会把 `` 也代理掉返回 502）。
   需要代理的工具在 config 里显式加 `"proxy": "http://..."`。
2. **JSON 中文描述**：用 curl 调 NexusRAG API 传中文会被 Git Bash 编码搞坏，
   改用 Python/HTTP 客户端注册工具。
3. **给 AI 的接口要只读 + 幂等**：LLM 会重复试探调用，写接口必须自己做防护
   （本案例全部只读；生产写接口建议加鉴权 + 幂等键）。
