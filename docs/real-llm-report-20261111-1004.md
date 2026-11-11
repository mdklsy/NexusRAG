# NexusRAG 真实 LLM 端到端报告

- 时间：2026-11-11 10:04
- 结果：**11 PASS / 0 FAIL**

| 检查项 | 结果 | 说明 |
|--------|------|------|
| LLM 配置为真实模型 | ✅ | base=https://api.deepseek.com/v1 model=deepseek-chat |
| embedding=本地 mock（DeepSeek 无向量接口，检索确定性向量） | ✅ | 允许：向量环节不依赖真模型 |
| 真实向量摄取 completed | ✅ | status=completed err= |
| SSE 流式 200 | ✅ | HTTP 200 |
| 回答非空且非 mock 话术 | ✅ | 根据资料，NexusRAG 的向量存储使用 **Qdrant**，业务数据（以及知识图谱）存储在 **PostgreSQL** [1]。 |
| 回答命中事实(Qdrant/PostgreSQL) | ✅ | 根据资料，NexusRAG 的向量存储使用 **Qdrant**，业务数据（以及知识图谱）存储在 **PostgreSQL** [1]。 |
| 引用溯源 | ✅ | [{'index': 1, 'chunk_id': 'd2d843eb-9695-487e-858f-a1423458c10d', 'document_id': |
| usage 真实 token 数 | ✅ | {'type': 'usage', 'tokens_in': 449, 'tokens_out': 34} |
| 闲聊意图识别 + 直答 | ✅ | intent=chat answer=你好！关于天气，我这边没有相关的资料可以查询，建议你查看天气App或当地气象台的最新信息。有其他问题随时问我～ |
| 评测运行完成 | ✅ | status=completed f=5.0 rel=5.0 |
| judge 分数合理(≥3) | ✅ | {'question': 'NexusRAG 用什么存向量？', 'answer': 'NexusRAG 使用 **Qdrant** 存储向量。', 'retrieved_doc_ |