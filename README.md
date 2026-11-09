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
│  渠道层   网页挂件(一行script) / 小程序SDK / 开放API    │
├──────────────────────────────────────────────────────┤
│  应用层   应用配置 · 提示词 · 模型 · 检索策略 · 对话记录 │
├──────────────────────────────────────────────────────┤
│  引擎层   RAG：解析→分块→嵌入→向量+BM25混合→重排→生成   │
│          KG ：LLM 实体关系抽取→图谱存储→子图召回→融合   │
│          工具：HTTP API / 只读SQL ← function calling   │
├──────────────────────────────────────────────────────┤
│  存储层   PostgreSQL（业务+图谱+倒排） · Qdrant · Redis │
├──────────────────────────────────────────────────────┤
│  平台层   用户 · API Key · 操作日志 · 数据看板          │
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
open http://localhost:3001 # 控制台（默认账号见 .env 中 ADMIN_EMAIL/ADMIN_PASSWORD）
```

> 还没有 LLM API Key？`cd backend && python scripts/mock_llm.py` 会启动一个
> OpenAI 协议兼容的本地 mock 服务（127.0.0.1:9999，确定性向量 + 固定回答），
> `.env` 里把 `LLM_API_BASE` / `EMBEDDING_API_BASE` 指向
> `http://host.docker.internal:9999/v1` 即可先跑通全链路再接真模型。

<details>
<summary>🇨🇳 国内网络部署指引（镜像拉取 / 依赖安装慢看这里）</summary>

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

### 一行代码把客服挂到任意网页

应用配置里生成「挂件 Key（仅对话）」，把下面这行加到你的网站 `</body>` 前：

```html
<script src="http://your-host/widget.js" data-key="nx-挂件Key" defer></script>
```

右下角出现 💬 气泡，点击即聊——流式回答、引用溯源、工具调用状态全都有，Shadow DOM 隔离样式，不依赖任何框架。

### 让助手能查你的业务系统

应用「配置 → 业务工具」里添加连接器，LLM 会在需要时自动调用（function calling）：

- **HTTP API**：填 Method + URL（支持 `{order_id}` 路径占位）+ 请求头，即可对接现有业务接口
- **SQL 只读查询**：填数据库连接串（建议只读账号），内置安全校验——仅允许单条 SELECT/WITH，禁止写操作与多语句，最多返回 20 行

## 项目结构

```
├── backend/   FastAPI · SQLAlchemy 2 · ARQ · Qdrant client
├── frontend/  React 18 · TypeScript · Ant Design 5 · ECharts
├── miniprogram/ 微信小程序 SDK（零依赖单文件）
├── docs/      架构文档与路线图
└── docker-compose.yml
```

详见 [docs/architecture.md](docs/architecture.md) 与 [docs/roadmap.md](docs/roadmap.md)。

## 真实集成案例

- [极速图片工坊（微信小程序）](docs/integration-miniprogram.md) — 小程序 SDK 接入全流程
- [（Web 管理台）](docs/integration-web.md) — 业务 API 注册为工具，LLM 自动查询业务数据（function calling）

## 路线图

- [x] 一期：核心 RAG + 轻量 KG + 控制台 + 数据看板 + 开放 API
- [x] 二期：网页聊天挂件（一行 script）、业务系统连接器（HTTP API + 只读 SQL + function calling）、挂件专用 Key（scope=chat）
- [x] 二期续：混合检索（BM25 倒排 + 向量 RRF 融合，jieba 分词）、重排（LLM 零依赖 / Cross-Encoder 可选依赖）、微信小程序 SDK
- [x] 三期已落地：应用级 LLM 凭证（AES 加密，每应用可独立厂商/账号）、用户角色权限（admin/editor/viewer）、Ragas 风格评测（忠实度/相关性/命中率）、微信公众号接入
- [ ] 后续：公众号安全模式加密、可视化工作流编排、Neo4j 图引擎、GraphRAG 深度模式（明确不做多租户）

## 参与贡献

欢迎 Issue / PR。开发环境见上方「本机开发」，提交前请跑 `ruff check` 与 `pytest`。

## License

[Apache License 2.0](LICENSE)
