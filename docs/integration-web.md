# 集成案例：把 NexusRAG 接入你的 Web 管理台

> 示例场景：一个 Node.js 订单管理系统接入 NexusRAG：
> ① Web 端挂 AI 助手聊天页；② 把业务 API 注册为 NexusRAG 工具，
> 让大模型在对话中**自动调用**（function calling），实现「向下打通业务系统」。
> 下文以「订单/工单」这类通用业务为例，替换成你自己的领域即可。

## 架构

```
public/assistant.html（AI 助手聊天页，fetch SSE 流式）
        │
        ▼
NexusRAG /api/v1/chat/stream
   │ 意图路由 → 检索 → 生成
   │ LLM 决定调用哪个工具（function calling 循环，最多 N 轮）
        │
        ▼ execute_tool (HTTP)
routes/business-api.mjs（业务测试接口，只读）
   │ 查数据库（orders / tasks / receipts 等你的业务表）
   ▼
结果回喂 LLM → 组织成自然语言回答
```

## 第一步：暴露业务接口（`routes/business-api.mjs`）

先给 AI 一组**只读**接口，模拟「业务系统 API」：

| 接口 | 用途 | 演示的工具形态 |
|---|---|---|
| `GET /api/assistant/ping?msg=` | 回声探测 | 查询参数 |
| `GET /api/assistant/time` | 服务器时间 | 零参数 |
| `GET /api/assistant/stats` | 业务全局统计 | 零参数（LLM 主动调用） |
| `GET /api/assistant/orders/{order_id}` | 单订单详情 | 路径参数 |
| `GET /api/assistant/orders?order_no=` | 按单号查询 | 查询参数 |

在你的 Node 服务里注册这组路由（Express 示例）：

```js
// ESM：import crypto from 'node:crypto' 等按需引入
app.get("/api/assistant/stats", (req, res) => {
  // 查你的业务库，返回 JSON
  res.json({ orders_total: 42, by_status: { paid: 30, shipped: 10, refunded: 2 } });
});
```

## 第二步：在 NexusRAG 注册为工具

控制台 → 应用配置 → 业务工具 → 添加（或调 API）：

| 函数名 | 类型 | URL | 给 LLM 的描述（关键！） |
|---|---|---|---|
| `order_stats` | http_api | `http://your-host/api/assistant/stats` | 统计订单整体情况：总数/各状态分布。用户问整体情况时调用 |
| `get_order` | http_api | `http://your-host/api/assistant/orders/{order_id}` | 按订单ID查详情：状态/金额/物流。参数 order_id=数字ID |
| `query_order` | http_api | `http://your-host/api/assistant/orders?order_no={order_no}` | 按订单号查发货状态。参数 order_no=订单号 |

> **描述写法决定调用准确率**：写清「什么时候调用 + 每个参数的含义」，
> LLM 靠这段文字决定是否调用、怎么填参数。

## 第三步：Web 聊天页（`public/assistant.html`）

独立页面 `/assistant`，右上角 ⚙ 配置 NexusRAG 地址与 API Key（存 localStorage）。
对话走 `fetch` + `ReadableStream` 解析 SSE，支持：

- 流式打字机输出
- `⚙ 工具名` 调用徽标（成功 ✓ / 失败 ✗ 着色）
- 引用溯源标签

不想自己写页面？用官方挂件最快——在任意页面加一行（挂件 Key）：

```html
<script src="http://nexusrag-host/widget.js" data-key="nx-挂件Key" defer></script>
```

## 预期效果

```
用户：现在订单情况怎么样？
LLM：→ 自动调用 order_stats →
回答：当前共 42 个订单：已支付 30、已发货 10、已退款 2。

用户：订单 A1001 发货了吗？
LLM：→ 自动调用 query_order(order_no="A1001") →
回答：订单 A1001 状态已发货，物流单号 SF1234。
```

*（工具执行链路开箱即用；「LLM 何时决定调用」需要配置真实 LLM API Key 后生效）*

## 结构化卡片（生成式 UI，可选）

业务工具的 HTTP 响应如果是**纯 JSON** 且顶层含 `nexus_card` 对象，挂件会把
回答下面的内容渲染成结构化卡片（而不是等 LLM 把数字复述成文字）。LLM 仍会
收到完整响应文本用于组织话术，卡片只是附加展示。

```json
{
  "nexus_card": {
    "card_type": "stats",
    "title": "今日订单",
    "items": [
      {"label": "总数", "value": 42},
      {"label": "已支付", "value": 30}
    ]
  }
}
```

支持四种卡型（白名单，超出忽略）：

| card_type | 字段 | 渲染 |
|---|---|---|
| `stats` | `items:[{label, value}]`（≤8） | 指标格网 |
| `table` | `headers:[]`、`rows:[][]`（≤6 列 ×10 行） | 表格 |
| `list` | `items:[]`（≤10） | 列表 |
| `actions` | `buttons:[{label, url}]`（≤5） | 链接按钮（新窗口打开） |

约束：卡片整体 ≤4KB；字段值按字符串截断渲染；按钮仅支持打开链接（不做任意
回调），确保挂件侧无脚本注入面。卡片随消息持久化，历史记录中同样渲染。

## 踩坑记录（对其他集成者有价值）

1. **系统代理劫持内网请求**：工具执行器默认 `trust_env=False` 直连
   （业务 API 多为内网地址，Windows 系统代理会把 `127.0.0.1:PORT` 这类地址也代理掉返回 502）。
   需要代理的工具在 config 里显式加 `"proxy": "http://..."`。
2. **JSON 中文描述**：用 curl 调 NexusRAG API 传中文会被 Git Bash 编码搞坏，
   改用 Python/HTTP 客户端注册工具。
3. **给 AI 的接口要只读 + 幂等**：LLM 会重复试探调用，写接口必须自己做防护
   （本案例全部只读；生产写接口建议加鉴权 + 幂等键；确需写操作的敏感接口，
   可在 NexusRAG 里给工具勾选「调用前需人工确认」走审批门）。
