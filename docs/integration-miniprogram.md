# 集成案例：极速图片工坊（微信小程序）

> 真实案例：原生小程序「图快快工具箱」（图片压缩/格式转换/证件照等纯本地处理工具）
> 接入 NexusRAG，新增「AI 助手」能力。本文记录完整接入步骤，供其他小程序参考。

## 架构

```
小程序 pages/ai（对话页）
   │  utils/nexus/nexusrag.js —— NexusRAG 小程序 SDK（chunked SSE 流式）
   ▼
NexusRAG 后端 /api/v1/chat/stream（SSE）
   │  意图路由 → 混合检索（向量+BM25）→ KG 增强 → LLM 生成
   ▼
回答 + 引用溯源 + 工具调用状态
```

## 接入步骤（4 步）

### 1. 拷贝 SDK（2 个文件，零依赖）

```
utils/nexus/nexusrag.js          # 主 SDK：init/chat/abort/on 事件总线
utils/nexus/nexusrag-decoder.js  # UTF-8 解码器（处理中文多字节被 chunk 拆分）
```

要求基础库 ≥ 2.20.1（`wx.request` 的 `enableChunked`）；低版本 SDK 自动降级为非流式。

### 2. 配置（`utils/config.js`）

```js
nexus: {
  enabled: true,
  baseUrl: 'https://你的NexusRAG域名',   // 须加入微信后台 request 合法域名
  apiKey: 'nx-xxxxxxxx'                  // 控制台生成「挂件 Key」（scope=chat）
}
```

> 开发阶段：开发者工具「详情 → 本地设置 → 不校验合法域名」可直接连本机
> `http://127.0.0.1:8000` 联调；上线前换成 HTTPS 域名。

### 3. 对话页（`pages/ai/`）

核心就是调 SDK 的 `chat()`，流式事件驱动 UI：

```js
const nexus = require('../../utils/nexus/nexusrag');
const client = nexus.init({ apiKey: config.nexus.apiKey, baseUrl: config.nexus.baseUrl });

client.chat('证件照怎么拍才合格？', (ev) => {
  if (ev.type === 'delta')      /* 追加流式文本 */;
  if (ev.type === 'tool_call')  /* 显示 ⚙ 工具徽标 */;
  if (ev.type === 'citations')  /* 渲染引用来源标签 */;
  if (ev.type === 'done')       /* 显示耗时，解除 busy */;
});
```

完整实现见本仓库 `pages/ai/index.js`（多轮会话自动续接、失败降级提示、思考中动效）。

### 4. 首页入口

- `app.json` 的 `pages` 注册 `pages/ai/index`
- `utils/features.js` 加卡片元数据，首页九宫格自动出现「AI 助手」入口

## 业务要点

- **隐私不冲突**：图片业务全部本地处理不上传（本项目卖点），AI 助手只收发文本，
  用户提问内容走 NexusRAG 后端，与图片数据完全隔离。
- **Key 权限最小化**：小程序用 `scope=chat` 的挂件 Key，即使泄漏也只能对话，
  不能操作知识库/应用配置。
- **多轮会话**：SDK 实例内自动持久化 `conversationId`，页面卸载时调 `client.abort()` 断流。

## 已知约束

- `enableChunked` 在真机部分安卓机型偶发丢帧，SDK 对坏帧静默跳过（不影响完整性，
  缺失内容以下一轮 delta 补齐；极端情况降级非流式重试）。
- 合法域名必须 HTTPS 且备案；本地 HTTP 仅限开发者工具联调。
