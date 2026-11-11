# NexusRAG 真实 LLM 端到端报告

- 时间：2026-11-11 10:40
- 结果：**12 PASS / 0 FAIL**

| 检查项 | 结果 | 说明 |
|--------|------|------|
| LLM+embedding 均为真实配置 | ✅ | llm=deepseek-chat emb=BAAI/bge-m3 |
| 真实向量摄取 completed | ✅ | status=completed err= |
| SSE 流式 200 | ✅ | HTTP 200 |
| 回答非空且非 mock 话术 | ✅ | NexusRAG 的向量存储使用 **Qdrant**，业务数据（以及知识图谱）存储在 **PostgreSQL**。[1]

- 向量存储：Qdrant [1 |
| 回答命中事实(Qdrant/PostgreSQL) | ✅ | NexusRAG 的向量存储使用 **Qdrant**，业务数据（以及知识图谱）存储在 **PostgreSQL**。[1]

- 向量存储：Qdrant [1]
- 业务数据与知 |
| 引用溯源 | ✅ | [{'index': 1, 'chunk_id': '66e09702-d186-4bd5-a9d3-eb2f88e8ce2c', 'document_id': |
| usage 真实 token 数 | ✅ | {'type': 'usage', 'tokens_in': 479, 'tokens_out': 55} |
| 闲聊意图识别 + 直答 | ✅ | intent=chat answer=你好！我这边没有天气相关的资料，无法告诉你今天天气怎么样。建议你查看天气App或当地气象台的最新预报。 |
| 检索 API 200 + chunks 非空 | ✅ | HTTP 200 n=1 |
| KG 事实注入 | ✅ | ['NexusRAG --是--> 开源平台', 'NexusRAG --包含--> 检索增强生成（RAG）'] |
| 评测运行完成 | ✅ | status=completed f=5.0 rel=5.0 |
| judge 分数合理(≥3) | ✅ | {'question': 'NexusRAG 用什么存向量？', 'answer': 'NexusRAG 使用 **Qdrant** 存储向量。', 'retrieved_doc_ |