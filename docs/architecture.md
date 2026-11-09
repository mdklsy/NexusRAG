# NexusRAG 架构文档

## 总体分层

```
┌────────────────────────────────────────────────────────────┐
│ 渠道层（二期 SDK）    Web 挂件 · App · 小程序 · 微信           │
│                      本期先以开放 API + API Key 提供接入能力     │
├────────────────────────────────────────────────────────────┤
│ 应用层               App = 提示词 + 模型配置 + 检索策略 + KB 绑定 │
│                      对话记录 · 引用溯源 · usage_events         │
├────────────────────────────────────────────────────────────┤
│ 引擎层                                                          │
│   摄取管线: 解析 → 分块 → 嵌入 → Qdrant → KG 三元组抽取 → PG 图  │
│   检索管线: query → 向量召回 → (可选重排) → 实体链接 → 子图召回    │
│             → 上下文融合 → LLM 流式生成 → 引用                   │
├────────────────────────────────────────────────────────────┤
│ 存储层   PostgreSQL(业务数据+图谱) · Qdrant(向量) · Redis(队列)   │
├────────────────────────────────────────────────────────────┤
│ 平台层   用户认证(JWT) · API Key · 操作日志 · 数据看板            │
└────────────────────────────────────────────────────────────┘
```

## 关键设计决策

### 1. 模型接入：OpenAI 兼容协议薄层

不自研 provider 体系。国内外主流厂商（DeepSeek / 智谱 / 通义 / OpenAI / Ollama）全部兼容
OpenAI Chat Completions + Embeddings 协议，`LLM_API_BASE` 一项配置即可切换。
`app/services/llm/` 中 `LLMClient` / `EmbeddingClient` 是唯一出口，业务层不感知厂商。

### 2. 双写存储：chunk 主存 PostgreSQL，向量只存 Qdrant

- `chunks` 表保存原文、序号、元数据（标题层级等），是引用溯源的事实来源
- Qdrant point id = chunk uuid，payload 仅存 kb_id / document_id 冗余字段用于过滤
- 好处：换向量库时零损失迁移；PG 里的知识资产永远完整

### 3. 轻量知识图谱：LLM 抽取 + PostgreSQL 邻接表

- 摄取时按 chunk 调 LLM 抽取 `(实体, 关系, 实体)` 三元组，实体按名称+类型归一合并
- 图存 PG：`entities` / `relations` 两张表，多跳查询用递归 CTE，百万实体内性能足够
- `GraphStore` 是抽象接口（`app/services/kg/graph_store.py`），二期可无缝换 Neo4j
- 检索增强：query 实体链接 → 1~2 跳子图 → 实体/关系事实文本拼入上下文（GraphRAG-lite）

### 4. 异步摄取：ARQ + Redis

解析/分块/嵌入/KG 抽取均为异步任务（`app/workers/tasks/`），文档状态机：
`pending → parsing → chunking → embedding → extracting_kg → completed / failed`。
摄取管线核心逻辑写成纯函数，ARQ 只是薄封装，可独立单测。

### 5. 对话接口：SSE 流式 + 结构化事件

`POST /api/v1/chat/stream` 返回 `text/event-stream`：
`delta`（增量文本）→ `citations`（引用数组）→ `usage`（token 统计）→ `done`。
天然适配浏览器 EventSource 与各端 SDK 封装。

### 6. 多租户预留

所有业务表带 `tenant_id`（默认 1），一期不做租户隔离逻辑，三期开多租户时无需迁移数据。

## 数据模型（ER 概览）

```
users ── api_keys
  │
  ├── apps ──┬── app_knowledge_bases ── knowledge_bases
  │          └── conversations ── messages
knowledge_bases ── documents ── chunks ── chunk_entities ── entities
                                     └── relations (evidence_chunk_id → chunks)
usage_events (app_id, type, tokens, latency_ms, hit, created_at)
```

## API 一览（/api/v1）

| 模块 | 端点 | 认证 |
|---|---|---|
| 认证 | POST /auth/login、GET /auth/me | JWT |
| 应用 | CRUD /apps、POST /apps/{id}/api-keys | JWT |
| 知识库 | CRUD /kbs | JWT |
| 文档 | POST /kbs/{id}/documents（上传/URL）、GET 列表、DELETE、GET /documents/{id}/chunks | JWT |
| 检索 | POST /retrievals（向量+图融合，调试用） | JWT |
| 对话 | POST /chat/stream（SSE）、GET /conversations | JWT 或 API Key |
| 看板 | GET /dashboard/overview、/dashboard/timeseries | JWT |
