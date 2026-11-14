# NexusRAG

**通用 RAG + 知识图谱开源平台** — 快速搭建属于你的智能客服 / 智能助理。

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python_3.10+-3776AB?logo=python&logoColor=white)](backend/pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](backend/app/main.py)
[![React](https://img.shields.io/badge/React_18-61DAFB?logo=react&logoColor=white)](frontend/package.json)
[![CI](https://github.com/mdklsy/NexusRAG/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)

## NexusRAG 是什么

NexusRAG 帮你把一堆文档变成一个**可检索、可溯源、可量化**的智能问答系统，再让它长出手脚去连你的业务系统：

```
┌────────────────────────────────────────────────────────────┐
│  渠道层    网页挂件（一行 script） · 小程序 SDK · 开放 API     │
├────────────────────────────────────────────────────────────┤
│  应用层    应用配置 · 提示词 · 模型 · 检索策略 · 对话记录       │
├────────────────────────────────────────────────────────────┤
│  编排层    意图路由 → 记忆压缩 → 多轮改写 → 检索 → 生成        │
│           多 Agent 编排（规划-分发-汇总 / 依赖波次并行）       │
│           人机协作（工具审批门 · 回答人工审核）                │
├────────────────────────────────────────────────────────────┤
│  引擎层    RAG：解析→分块→嵌入→向量+BM25混合→重排→生成        │
│           KG ：LLM 实体关系抽取→图谱存储→子图召回→融合        │
│           工具：HTTP API / 只读SQL(NL2SQL) ← function call  │
├────────────────────────────────────────────────────────────┤
│  存储层    PostgreSQL（业务+图谱+倒排） · Qdrant · Redis     │
├────────────────────────────────────────────────────────────┤
│  平台层    用户 · API Key · 操作日志 · 数据看板 · 评测集       │
└────────────────────────────────────────────────────────────┘
```

- **向上**：开放 API（SSE 流式对话 / 检索），网页、App、小程序随时接入
- **中间**：应用级灵活配置——提示词、模型、检索策略、多 Agent 编排、人机协作，全部可视化配置
- **向下**：业务连接器——HTTP API 与只读 SQL 作为工具被大模型自动调用（function calling）

## 核心特性

| 特性 | 说明 |
|---|---|
| **开箱即用** | `docker compose up -d` 拉起全栈（API / Worker / PostgreSQL / Qdrant / Redis），首次启动自动建表 + 建管理员 |
| **双引擎检索** | 向量 RAG + 轻量知识图谱（GraphRAG-lite），实体关系类问题显著增强 |
| **混合检索 + 重排** | BM25 关键词 + 向量语义 RRF 融合，可插接 rerank 模型，回答附带引用溯源 |
| **业务工具** | HTTP API（路径占位、模板参数）与只读 SQL（仅 SELECT 白名单校验）两条连接器 |
| **NL2SQL** | 自省表结构自动内联/伴随工具路由、安全 SQL 白名单，模型自主查库答数 |
| **多 Agent 编排** | 规划器拆解子任务 → 依赖波次并行执行 → 汇总；代理支持工具白名单/轮数/委派 |
| **人机协作** | 敏感工具调用先审批后执行；回答先审后发（可改写）；缺参时模型先问不编造 |
| **洞察飞轮** | 审核改写挖成提示词规则、驳回问题一键转评测用例；无答案问题聚类成知识缺口主题并可起草候选答案 |
| **文档级 ACL** | 同一知识库按文档设置终端用户白名单，检索层过滤（向量+BM25），敏感知识按人可见 |
| **评测自诊断** | 评测失败自动归因（召回空/期望文档未召回/排序靠后/资料不足/生成不忠实）并给出修复建议 |
| **生成式 UI** | 业务工具返回 nexus_card 结构时挂件渲染指标/表格/列表/按钮卡片，答案即工作台 |
| **语义缓存 + 预算** | 相似问题直接复用回答（零检索零生成）；按应用设每日/每月 token 预算熔断 |
| **数据看板 + 评测** | 调用量 / Token / 延迟分位 / 命中率；评测集回归对比检索与回答质量 |
| **模型无关** | OpenAI 兼容协议一套配置适配 DeepSeek / 智谱 GLM / 通义 / OpenAI / Ollama |
| **多应用隔离** | 每个应用独立知识库绑定与参数配置，API Key 认证，挂件样式按应用配置 |

## 快速开始

### Docker Compose（推荐）

```bash
cp .env.example .env      # 编辑 .env：填入 LLM_API_KEY / EMBEDDING_API_KEY
docker compose up -d      # 首次启动自动建表 + 创建管理员
open http://localhost:3001 # 控制台（账号见 .env 中 ADMIN_EMAIL / ADMIN_PASSWORD）
```

> 还没有 LLM API Key？`cd backend && python scripts/mock_llm.py` 会启动一个
> OpenAI 协议兼容的本地 mock 服务（127.0.0.1:9999，确定性向量 + 固定回答），
> `.env` 里把 `LLM_API_BASE` / `EMBEDDING_API_BASE` 指向
> `http://host.docker.internal:9999/v1` 即可先跑通全链路再接真模型。

<details>
<summary>国内网络部署指引（镜像拉取 / 依赖安装慢看这里）</summary>

1. **基础镜像预拉**：BuildKit 构建时拉基础镜像常走 `auth.docker.io`（易受 DNS 污染影响）。
   推荐先用 daemon 直接预拉（daemon 走 `registry-mirrors`，成功率高），构建即命中本地缓存：

   ```bash
   docker pull postgres:16-alpine
   docker pull qdrant/qdrant:latest
   docker pull redis:7-alpine
   docker pull python:3.11-slim
   docker pull node:20-alpine
   docker pull nginx:1.25-alpine
   ```

   daemon 镜像源可在 Docker Desktop → Settings → Docker Engine 中配置（如
   `https://docker.1ms.run`、`https://docker.m.daocloud.io`）。

2. **Python 依赖**：backend 镜像已内置清华 PyPI 源（`PIP_INDEX_URL`），无需额外配置。

3. **前端依赖**：镜像内 `pnpm install` 走 npm 官方源；如遇 pnpm 10+ 的
   `ERR_PNPM_TARBALL_URL_MISMATCH`（lockfile 内镜像站 URL 与官方元数据校验冲突），
   为已知供应链校验限制，仓库构建流程已通过忽略 lockfile 规避。

4. **端口**：web 控制台固定映射 `3001`（3000 端口常与本机其他 dev server 冲突）。
   若 3001 也被占用，改 `docker-compose.yml` 中 web 的 `ports` 后 `docker compose up -d web`。

</details>

### 本机开发

```bash
# 后端（Python 3.10+）
cd backend
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head       # 需要 PostgreSQL（见 .env.example DATABASE_URL）
python -m app.bootstrap    # 创建初始管理员
uvicorn app.main:app --reload --port 8000

# 前端（Node 18+）
cd frontend
pnpm install
pnpm dev       # http://localhost:5173，代理到后端 8000
```

> **Windows 本机开发提示**：若公司/系统代理拦截了对 LLM API 的出站请求（症状：摄取文档
> failed 且错误含 `502`），给终端设置 `set no_proxy=*`（Git Bash: `export no_proxy='*'`）后重启服务。
> 测试：`cd backend && pytest`（无需任何外部服务，内置 sqlite + 内存向量库 + Fake LLM）。

## 5 分钟跑通第一个应用

1. 控制台创建**知识库** → 上传文档（PDF / Word / Excel / Markdown / 网页 URL）
2. 等待摄取完成（自动解析、分块、向量化、知识图谱抽取）
3. 创建**应用**，绑定知识库，配置提示词与模型
4. 在 **Playground** 中提问，验证回答与引用溯源
5. 生成 **API Key**，用开放接口接入你自己的网页 / App：

```bash
curl -N http://localhost:8000/api/v1/chat/stream \
  -H "Authorization: Bearer nx-xxxx" -H "Content-Type: application/json" \
  -d '{"app_id": "xxx", "query": "你们的退款政策是什么？"}'
```

回答以 SSE 流式返回，事件包括 `conversation` / `intent` / `delta` / `citations` / `usage` / `done`。

### 一行代码把客服挂到任意网页

应用配置里生成「挂件 Key（仅对话）」，把下面这行加到你的网站 `</body>` 前：

```html
<script src="http://your-host/widget.js" data-key="nx-挂件Key" defer></script>
```

右下角出现对话气泡，点击即聊——流式回答、引用溯源、历史会话懒加载、工具调用状态全都有，Shadow DOM 隔离样式，不依赖任何框架。详见 [docs/integration-web.md](docs/integration-web.md)；微信小程序 SDK 见 [docs/integration-miniprogram.md](docs/integration-miniprogram.md)。

### 让助手能查你的业务系统

应用「配置 → 业务工具」里添加连接器，LLM 会在需要时自动调用（function calling）：

- **HTTP API**：填 Method + URL（支持 `{order_id}` 路径占位）+ 请求头，即可对接现有业务接口
- **SQL 只读查询**：填数据库连接串（建议只读账号）。内置 NL2SQL 工程：
  - 启用即自省库表结构：小库结构内联进提示词，大库自动生成 `<工具名>_tables` 伴随工具按需查表
  - 安全白名单：仅允许单条 SELECT/WITH，禁止写操作与多语句，最多返回 20 行

### 多 Agent 协作（可选，默认关闭）

应用「配置 → 多代理协作」选「规划-执行模式」：规划器把问题拆成子任务，按 `depends_on` 依赖关系
分波并行执行（无依赖的同波并发，有依赖的按序等待），最后汇总结论。每个代理可配：

- **系统提示词**（职责）、**工具白名单**（不勾 = 全部可用）、**轮数**（查几次工具才作答）

对话页签默认不显示过程线，控制台可按应用开启过程展示。架构详见 [docs/agents.md](docs/agents.md)。

### 人机协作（审批 + 审核）

「人机协作」控制台一级页面（侧边栏入口，带全局待办角标）承载所有人工介入：

- **工具审批门**：给敏感工具（退款、发货、发短信……）勾选「调用前需人工确认」→ 代理调用
  不真执行，落审批单；值班人「通过执行 / 拒绝」后，系统真执行并把结果自动回复到原对话
- **回答人工审核**：应用配置开启后，每轮回答先进待审核队列，全文卡片展示，
  支持**改写后通过 / 通过原文 / 驳回**，放行后用户才可见（挂件历史只回已发布消息）
- **缺参先问**：内置提示词规则——用户问题缺必要参数（订单号、手机号）时先询问，
  不编造参数、不调用注定失败的工具

## 应用配置速查

应用编辑抽屉各页签的可配置项（均为运行时可改，保存即生效）：

| 页签 | 关键配置 |
|---|---|
| 基本信息 | 名称 / 描述 / 图标 / 绑定知识库 |
| 模型 | LLM 供应商与模型、temperature、max_tokens |
| 检索策略 | top_k、相似度阈值、BM25 开关、rerank 模型、KG 开关与跳数、历史窗口、工具轮数、意图路由 |
| 多代理协作 | 关闭 / 规划-执行模式；最多子任务数、并行开关、单波并发；代理名单（提示词/工具白名单/轮数） |
| 人机协作 | 回答人工审核开关（工具级审批在「业务工具」页签按工具勾选） |
| 网页挂件 | 标题 / 主题色 / 欢迎语 / 悬浮球图标或自定义图片 |
| 业务工具 | HTTP API / SQL 连接器；路径占位、请求头、参数模板、「调用前需人工确认」 |

## 项目结构

```
├── backend/    FastAPI · SQLAlchemy 2(async) · ARQ · Qdrant client
│   └── app/
│       ├── api/v1/        # REST：apps / kbs / documents / chat / hitl / evals / dashboard …
│       ├── services/
│       │   ├── chat/      # 编排：意图路由→改写→检索→生成（SSE 事件流）
│       │   ├── agents/    # 多 Agent：runner（工具循环/委派）+ patterns（规划-并行-汇总）
│       │   ├── retrieval/ # 向量 / BM25 / KG 子图 / RRF 融合 / rerank
│       │   ├── kg/        # LLM 三元组抽取 + PostgreSQL 图存储
│       │   ├── ingestion/ # 解析（PDF/Word/Excel/MD/URL）→ 分块 → 嵌入
│       │   ├── tools/     # 业务连接器执行器（HTTP / 安全SQL / schema自省）
│       │   └── approvals.py  # 人机协作：审批门 + 审核决策
│       └── workers/       # ARQ 异步摄取任务
├── frontend/   React 18 · TypeScript · Ant Design 5 · ECharts · TanStack Query
│   └── src/pages/  Apps / KnowledgeBases / Playground / HumanLoop(人机协作) / Dashboard / Evals …
├── miniprogram/  微信小程序 SDK（零依赖单文件）
├── backend/app/static/widget.js  网页挂件（Shadow DOM 单文件）
├── docs/       架构文档 / 多Agent / 集成指南 / 路线图
└── docker-compose.yml
```

## 文档

| 文档 | 内容 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 总体架构、关键设计决策、数据模型 ER、API 一览 |
| [docs/agents.md](docs/agents.md) | 多 Agent 架构：AgentSpec、规划-并行编排、SSE 事件协议 |
| [docs/integration-web.md](docs/integration-web.md) | 网页集成实战：暴露业务接口 → 注册工具 → 聊天页 → 踩坑记录 |
| [docs/integration-miniprogram.md](docs/integration-miniprogram.md) | 微信小程序接入 SDK |
| [docs/roadmap.md](docs/roadmap.md) | 路线图 |

## License

[Apache License 2.0](LICENSE)
