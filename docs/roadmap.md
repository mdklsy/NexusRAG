# NexusRAG 路线图

## 一期（当前）：核心 RAG + 轻量 KG + 控制台

- [x] 多应用模型：提示词 / 模型 / 检索参数 / 知识库绑定
- [x] 知识库与文档管理：PDF / Word / Excel / Markdown / TXT / 网页 URL
- [x] 摄取管线：解析 → 分块（可配置）→ 嵌入 → Qdrant
- [x] 轻量知识图谱：LLM 三元组抽取 → PG 图存储 → 子图召回 → 融合检索
- [x] 对话 API：SSE 流式 + 引用溯源 + 意图路由
- [x] 控制台：登录 / 应用 / 知识库 / Playground / 实体图谱浏览 / 数据看板
- [x] 平台基础：JWT 认证、API Key、用量事件、docker compose 一键部署

## 二期：接入生态

- [x] 网页聊天挂件（一行 script 嵌入，Shadow DOM 隔离，`/widget.js`）
- [x] 业务系统连接器：HTTP API 工具 + 只读 SQL 连接器（function calling 循环）
- [x] 挂件专用 API Key（scope=chat）与挂件外观配置（标题/欢迎语/主题色）
- [x] 微信小程序 SDK（`miniprogram/`，chunked SSE + 低版本降级，5 用例测试）
- [x] 混合检索：jieba 分词 + chunk_tokens 倒排 + BM25 + 向量 RRF 融合
- [x] 重排：LLM 重排（零依赖）+ Cross-Encoder（可选依赖 `[rerank]`）
- [ ] 微信公众号接入
- [ ] 意图识别可配置化（多轮澄清、转人工兜底）
- [ ] 问答评测（ Ragas 风格：忠实度 / 相关性 / 命中率）

## 三期：规模化

- [x] 应用级 LLM 凭证：api_base/api_key 应用专属（AES 加密存储、接口打码返回），全局配置作默认
- [x] 用户角色权限：admin（含用户管理）/ editor（读写）/ viewer（只读+对话），最后一个管理员保护
- [x] Ragas 风格评测：评测集 → 命中率/忠实度/相关性（LLM 打分）→ 运行轮询与汇总
- [x] 微信公众号接入：签名校验回调 + 每粉丝会话 + markdown 清理的被动回复（明文模式）
- [ ] 公众号安全模式（EncodingAESKey 加解密）
- [ ] 可视化工作流编排器
- [ ] Neo4j 图引擎选项（GraphStore 接口已预留）
- [ ] GraphRAG 深度模式：社区检测 + 全局摘要 + 局部/全局双检索
- [ ] 高可用部署（K8s Helm Chart）

## 明确不做

- 多租户（单组织内用角色权限管理，见「简单用户权限」）

## 原则

- 每期交付物都可独立使用、可增量升级
- 数据模型向后兼容，不做破坏性迁移
- 重依赖（Neo4j、重排模型 GPU）永远是可选项，最小部署保持 5 容器
