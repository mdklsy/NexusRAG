# NexusRAG 微信小程序 SDK

零依赖（单文件）小程序端接入 SDK，支持流式对话（SSE over `wx.request` chunked），低版本基础库自动降级为非流式。

## 接入步骤

1. 把 [nexusrag.js](nexusrag.js) 和 [nexusrag-decoder.js](nexusrag-decoder.js) 拷到你的小程序项目（如 `libs/` 目录），两个文件放同一目录
2. 小程序后台「开发管理 → 服务器域名」把 NexusRAG 部署域名加入 **request 合法域名**（必须 HTTPS）
3. 在 NexusRAG 控制台给应用生成 API Key（建议「仅对话」scope 的挂件 Key）

## 使用示例

```js
// pages/chat/chat.js
const nexus = require("../../libs/nexusrag.js");

Page({
  onLoad() {
    this.client = nexus.init({
      apiKey: "nx-你的Key",
      baseUrl: "https://your-nexusrag-host",
      // conversationId: "uuid",  // 可选：跨页面续接会话
    });
    this.client.on("delta", (ev) => {
      this.setData({ answer: this.data.answer + ev.content });
    });
    this.client.on("citations", (ev) => this.setData({ cites: ev.citations }));
    this.client.on("tool_call", (ev) => wx.showToast({ title: "查询中…", icon: "none" }));
    this.client.on("error", () => wx.hideLoading());
    this.client.on("done", () => wx.hideLoading());
  },

  onAsk(e) {
    const q = e.detail.value.question;
    this.setData({ answer: "" });
    wx.showLoading({ title: "思考中" });
    this.client.chat(q);
  },

  onUnload() {
    this.client && this.client.abort();
  },
});
```

## 事件一览

| type | payload | 说明 |
|---|---|---|
| start | `{}` | 请求已发出 |
| conversation | `{conversation_id}` | 首轮返回，续接会话用 |
| intent | `{intent}` | 意图路由结果（qa/chat） |
| retrieval | `{chunks, graph_facts, hit}` | 检索命中概况 |
| tool_call / tool_result | `{name, ...}` | 业务工具调用状态 |
| delta | `{content}` | 流式增量文本 |
| citations | `{citations:[...]}` | 引用溯源 |
| usage | `{tokens_in, tokens_out}` | token 消耗 |
| done | `{latency_ms}` | 本轮结束 |
| error | `errMsg` | 失败 |

## 运行测试

```bash
node miniprogram/test.js   # 5 个用例：分帧、UTF-8 跨 chunk 拆分、降级路径等
```
