# NexusRAG

**通用 RAG + 知识图谱开源平台** — 快速搭建属于你的智能客服 / 智能助理。

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](backend/pyproject.toml)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)](frontend/package.json)

## NexusRAG 是什么

NexusRAG 帮你把一堆文档，变成一个**可被检索、可溯源、可量化**的智能问答系统：

- **向上**：开放 API（SSE 流式对话 / 检索），网页、App、小程序随时接入
- **中间**：应用级灵活配置——提示词、模型、检索策略、知识库绑定，全部可编排
- **向下**：连接业务系统（规划中）——数据库与业务 API 作为工具被大模型调用

```
┌──────────────────────────────────────────────────────┐
│  渠道层   Web / App / 小程序 / 微信（二期 SDK，先开放 API） │
├──────────────────────────────────────────────────────┤
│  应用层   应用配置 · 提示词 · 模型 · 检索策略 · 对话记录     │
├──────────────────────────────────────────────────────┤
│  引擎层   RAG：解析→分块→嵌入→向量检索→重排→生成+引用溯源   │
│          KG ：LLM 实体关系抽取→图谱存储→子图召回→融合检索   │
├──────────────────────────────────────────────────────┤
│  存储层   PostgreSQL（业务+图谱） · Qdrant（向量） · Redis │
├──────────────────────────────────────────────────────┤
│  平台层   用户 · API Key · 操作日志 · 数据看板             │
└──────────────────────────────────────────────────────┘
```

## 核心特性

- 🚀 **开箱即用**：docker compose 一键拉起全栈（API / Worker / PostgreSQL / Qdrant / Redis）
- 🧠 **双引擎检索**：向量 RAG + 轻量知识图谱（GraphRAG-lite），实体类问题显著增强
- 🔗 **引用溯源**：每条回答标注来源文档与原文片段，拒绝黑盒
- 🛠 **模型无关**：OpenAI 兼容协议一套配置适配 DeepSeek / 智谱 GLM / 通义 / OpenAI / Ollama 本地模型
- 📊 **数据看板**：调用量、Token 消耗、延迟分位、命中率、无答案率一目了然
- 🔐 **多应用隔离**：每个应用独立的知识库绑定与参数配置，API Key 认证
- 📖 **Apache 2.0**：可自由二次开发与商用

## 快速开始

### Docker Compose（推荐）

```bash
cp .env.example .env      # 编辑 .env：填入 LLM_API_KEY / EMBEDDING_API_KEY
docker compose up -d      # 首次启动自动建表 + 创建管理员
open http://localhost:8000 # 控制台（默认账号见 .env 中 ADMIN_EMAIL/ADMIN_PASSWORD）
```

### 本机开发

```bash
# 后端（Python 3.10+）
cd backend
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 前端（Node 18+）
cd frontend
pnpm install
pnpm dev       # http://localhost:5173，代理到后端 8000
```

### 5 分钟跑通第一个应用

1. 控制台创建**知识库** → 上传文档（PDF / Word / Excel / Markdown / 网页 URL）
2. 等待摄取完成（自动解析、分块、向量化、知识图谱抽取）
3. 创建**应用**，绑定知识库，配置提示词与模型
4. 在 **Playground** 中提问，验证回答与引用溯源
5. 生成 **API Key**，用开放接口接入你自己的网页 / App：

```bash
curl -N http://localhost:8000/api/v1/chat/stream \
  -H "Authorization: Bearer nx-xxxx" -H "Content-Type: application/json" \
  -d '{"app_id": "xxx", "messages": [{"role": "user", "content": "你们的退款政策是什么？"}]}'
```

## 项目结构

```
├── backend/   FastAPI · SQLAlchemy 2 · ARQ · Qdrant client
├── frontend/  React 18 · TypeScript · Ant Design 5 · ECharts
├── docs/      架构文档与路线图
└── docker-compose.yml
```

详见 [docs/architecture.md](docs/architecture.md) 与 [docs/roadmap.md](docs/roadmap.md)。

## 路线图

- [x] 一期：核心 RAG + 轻量 KG + 控制台 + 数据看板 + 开放 API
- [ ] 二期：网页聊天挂件 / 小程序 SDK、业务系统连接器（DB & API 工具）、混合检索(BM25)、重排模型
- [ ] 三期：可视化工作流编排、多租户与团队协作、Neo4j 图引擎、GraphRAG 深度模式

## 参与贡献

欢迎 Issue / PR。开发环境见上方「本机开发」，提交前请跑 `ruff check` 与 `pytest`。

## License

[Apache License 2.0](LICENSE)
