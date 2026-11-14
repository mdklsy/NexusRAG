# NexusRAG 全量测试用例矩阵

> 版本：2026-11-10 ｜ 被测：compose 全栈（api/worker/postgres/qdrant/redis/web，mock LLM）
> 分层：**单测**（backend/pytest，SQLite+FakeLLM，42 条）｜**SDK 测**（miniprogram，node，5 条）｜**E2E**（backend/scripts/e2e_full.py，对运行中真实栈）
> 结果落盘：`docs/test-report-<日期>.md`

## A. 认证与用户（auth / users / RBAC）

| ID | 用例 | 期望 | 层 |
|----|------|------|----|
| A01 | admin 正确密码登录 | 200，返回 token+user | E2E |
| A02 | 密码错误登录 | 401 | E2E |
| A03 | 不存在的邮箱登录 | 401 | E2E |
| A04 | 无 Authorization 头访问受保护接口 | 401 | E2E |
| A05 | 篡改签名的 JWT | 401 | E2E |
| A06 | 过期 JWT（本地按 SECRET_KEY 签发 exp-1h） | 401 | E2E |
| A07 | `alg:none` 伪 JWT | 401 | E2E |
| A08 | admin 创建 viewer / editor 用户 | 201 | E2E |
| A09 | 重复邮箱创建 | 409 | E2E |
| A10 | 非法 role（hacker） | 400 | E2E |
| A11 | viewer 访问 /users（admin-only） | 403 | E2E |
| A12 | viewer 创建知识库（editor 门槛） | 403 | E2E |
| A13 | editor 创建知识库 | 201 | E2E |
| A14 | editor 访问 /users | 403 | E2E |
| A15 | 把最后一个 admin 降级为 viewer | 400 保护 | E2E |
| A16 | /users 响应不泄露 hashed_password | 无该字段 | E2E+单测 |

## B. 应用管理与凭据（apps / llm_config / api-keys）

| ID | 用例 | 期望 | 层 |
|----|------|------|----|
| B01 | 创建应用（绑定 KB） | 201，kb_ids 回显 | E2E |
| B02 | 缺必填字段创建 | 422 | E2E |
| B03 | 应用详情/列表/更新 | 一致性 | E2E |
| B04 | 设置应用级 api_key | api_key_set=true，masked 形如 `sk-****XXXX` | E2E |
| B05 | 任何响应不回明文 key | grep 无明文 | E2E |
| B06 | PG 中 llm_config.api_key_enc 为 AES 密文 ≠ 明文 | docker exec psql 验证 | E2E |
| B07 | 创建 API Key | 201，明文一次性返回 | E2E |
| B08 | key 列表只出 masked/前缀 | 无完整明文 | E2E |
| B09 | 停用 key 后调 /chat/stream | 401 | E2E |
| B10 | nx- key 带 mismatch app_id 调 chat | 403 | E2E |
| B11 | 删除 key 后调用 | 401 | E2E |
| B12 | 删除应用 → 会话/消息/事件级联消失 | psql 计数 0 | E2E |

## C. 知识库与文档（kbs / documents / chunks / 摄取）

| ID | 用例 | 期望 | 层 |
|----|------|------|----|
| C01 | 创建 KB（模型/维度/分块参数） | 201 | E2E |
| C02 | KB 列表/详情字段完整 | doc_count/chunk_count | E2E |
| C03 | 上传 .md → ARQ 摄取 → 轮询至 completed | chunk_count≥1 | E2E |
| C04 | 上传 .txt | completed | E2E |
| C05 | URL 摄取（本地 HTML 服务） | completed，来源标记 url | E2E |
| C06 | 不支持的扩展名 | 400 | E2E |
| C07 | 上传到不存在的 KB | 404 | E2E |
| C08 | chunks 列表：seq 有序、token_count>0、meta 含标题 | 校验 | E2E |
| C09 | 删除文档 → chunks 级联 | 204+计数 0 | E2E |
| C10 | 删除 KB → 文档/chunks/Qdrant collection 级联 | psql+6333 验证 | E2E |
| C11 | 摄取失败可见 status=failed+error | 注入坏 URL | E2E |
| C12 | 解析器单测（pdf/docx/xlsx/md） | 全绿 | 单测 |

## D. 检索服务（retrievals：向量+BM25+RRF+KG）

| ID | 用例 | 期望 | 层 |
|----|------|------|----|
| D01 | 按 app_id 检索 | chunks>0，graph_facts 非空 | E2E |
| D02 | 按 kb_ids 直查 | 同上 | E2E |
| D03 | kb_ids 与 app_id 均缺省 | 400 | E2E |
| D04 | 不存在的 KB | 404 | E2E |
| D05 | use_kg=false | graph_facts 空 | E2E |
| D06 | top_k=1 | 恰 1 条 | E2E |
| D07 | BM25 精确词命中（倒排索引生效） | 命中文档排前 | E2E |
| D08 | score 降序 | 有序 | E2E |
| D09 | context 含引用标号 [1] | 格式正确 | E2E |
| D10 | 混合检索/RRF/重排单测 | 全绿 | 单测 |

## E. 对话链路（chat SSE + 会话）

| ID | 用例 | 期望 | 层 |
|----|------|------|----|
| E01 | JWT+app_id 流式对话 | conversation→intent→retrieval→delta…→citations→usage→done→[DONE] | E2E |
| E02 | API Key 流式对话（免 app_id） | 同上 | E2E |
| E03 | conversation_id 复用，历史窗口生效 | 第二轮 messages=4 | E2E |
| E04 | 会话列表 /apps/{id}/conversations | 含标题 | E2E |
| E05 | 消息列表 role/citations/tokens 字段 | 完整 | E2E |
| E06 | 不存在的 conversation_id | 404 | E2E |
| E07 | 空 query | 400 | E2E |
| E08 | JWT 无 app_id | 400 | E2E |
| E09 | 已停用应用的 key 调用 | 403 | E2E |
| E10 | usage 数字为正 | tokens_in/out>0 | E2E |
| E11 | 编排器/引用溯源单测 | 全绿 | 单测 |

## F. 数据看板（dashboard）

| ID | 用例 | 期望 | 层 |
|----|------|------|----|
| F01 | overview 字段齐全 | total_chats/hit_rate/… | E2E |
| F02 | hit_rate ∈ [0,1] | 数值合法 | E2E |
| F03 | timeseries 日期格式 YYYY-MM-DD | 合法 | E2E |
| F04 | 发起 1 次对话后 total_chats+1 | 因果一致 | E2E |

## G. 评测（evals）

| ID | 用例 | 期望 | 层 |
|----|------|------|----|
| G01 | 创建评测集（2 用例） | 201 | E2E |
| G02 | 空 cases | 400 | E2E |
| G03 | 运行评测（ARQ/内联回退）→ 轮询 completed | status 完成 | E2E |
| G04 | faithfulness/relevance ∈ 1..5，hit bool | 合法 | E2E |
| G05 | expected_doc_name 命中 → hit=true | 语义命中 | E2E |
| G06 | 删除评测集 | 204 | E2E |

## H. 业务工具连接器（tools）

| ID | 用例 | 期望 | 层 |
|----|------|------|----|
| H01 | http_api 缺 config.url | 400 | E2E |
| H02 | sql_db 缺 config.dsn | 400 | E2E |
| H03 | 创建 http_api 工具（指向 mock healthz） | 201 | E2E |
| H04 | 更新/删除工具 | 200/204 | E2E |
| H05 | 同名工具重复 | 409 | E2E |
| H06 | SQL 只读守卫（UPDATE/DELETE/;注入 拒绝） | ToolError | 单测 |
| H07 | HTTP 执行器 trust_env=False 直连 | 单测断言 | 单测 |

## I. 公众号渠道（wechat）

| ID | 用例 | 期望 | 层 |
|----|------|------|----|
| I01 | 创建绑定配置 | 201 | E2E |
| I02 | 同应用重复绑定 | 409 | E2E |
| I03 | GET 回调正确 sha1 签名 → 原样 echostr | 200 回显 | E2E |
| I04 | 错误签名 | 403 | E2E |
| I05 | POST 文本消息（正确签名） | XML Text → 包含回答 | E2E |
| I06 | 非文本消息（event） | success | E2E |
| I07 | 已停用配置回调 | 404 | E2E |
| I08 | 删除配置 | 204 | E2E |

## J. 基础设施与迁移

| ID | 用例 | 期望 | 层 |
|----|------|------|----|
| J01 | alembic version | 0005 | E2E |
| J02 | 核心表齐全（13 初始表+迁移新增） | psql 清点 | E2E |
| J03 | Qdrant 向量数 == chunks 计数 | 一致 | E2E |
| J04 | Redis PING | PONG | E2E |
| J05 | 六容器 Up/healthy | docker ps | E2E |
| J06 | /openapi.json 可达、路由数>0 | 200 | E2E |

## K. Web 前端与 nginx 代理

| ID | 用例 | 期望 | 层 |
|----|------|------|----|
| K01 | :3001 首页 200 | 200 | E2E |
| K02 | 静态 assets/*.js | 200 | E2E |
| K03 | SPA fallback（深链 /apps）→ index.html | 200 | E2E |
| K04 | /api/v1 代理到 FastAPI（401 语义证明） | 401 非 404/502 | E2E |

## L. 渠道 SDK

| ID | 用例 | 期望 | 层 |
|----|------|------|----|
| L01 | 小程序 SDK 单测（流式/解码/降级） | 5/5 | SDK测 |
| L02 | SDK 请求路径/鉴权头与后端契约一致 | 源码断言 | E2E |
| L03 | api 服务 /widget.js 挂件脚本 | 200 + Content-Type | E2E |

## M. 安全专项

| ID | 用例 | 期望 | 层 |
|----|------|------|----|
| M01 | 篡改 JWT / alg:none / 过期（同 A05-A07） | 401 | E2E |
| M02 | 响应中无明文 API Key / 密码 / 密文 key | grep 断言 | E2E |
| M03 | CORS 预检行为与配置一致 | 按配置断言 | E2E |
| M04 | 工具 SQL 注入/写操作拒绝 | 拒绝 | 单测 |
| M05 | .env / servers.json 不入库 | git check-ignore | E2E |

## 明确不在本轮范围

- 真实 LLM 端到端（mock 只覆盖协议形态；语义质量待真 key）→ 已备 `backend/scripts/e2e_real_llm.py`
- 小程序真机流程（需开发者工具+真机，人工配合）
- 压测/长稳、并发竞争、容器宕机演练（roadmap）
