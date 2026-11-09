/**
 * NexusRAG 微信小程序 SDK
 *
 * 用法（页面 JS）：
 *   const nexus = require("../../libs/nexusrag.js");
 *   const client = nexus.init({ apiKey: "nx-xxx", baseUrl: "https://your-host" });
 *   client.on("delta", t => this.setData({ answer: t }));
 *   client.on("citations", list => this.setData({ cites: list }));
 *   client.on("done", () => wx.hideLoading());
 *   client.chat("退款政策是什么？");
 *
 * 依赖：基础库 >= 2.20.1（wx.request enableChunked）。
 * 低版本自动降级为非流式（一次性收到完整回复）。
 * 记得把 baseUrl 域名加入小程序后台 request 合法域名。
 */

function NexusClient(opts) {
  this.apiKey = opts.apiKey;
  this.baseUrl = (opts.baseUrl || "").replace(/\/$/, "");
  this.conversationId = opts.conversationId || null;
  this.listeners = {};
  this._task = null;
}

NexusClient.prototype.on = function (type, fn) {
  (this.listeners[type] = this.listeners[type] || []).push(fn);
  return this;
};

NexusClient.prototype.emit = function (type, payload) {
  (this.listeners[type] || []).forEach(function (fn) {
    try {
      fn(payload);
    } catch (e) {
      console.error("[nexusrag] listener error", e);
    }
  });
};

NexusClient.prototype.abort = function () {
  if (this._task && this._task.abort) this._task.abort();
  this._task = null;
};

/** 流式对话。onEvent 可选（缺省走 on() 注册的监听器） */
NexusClient.prototype.chat = function (query, onEvent) {
  const self = this;
  // onEvent 便捷回调与事件总线同时触发
  const dispatch = function (ev) {
    if (onEvent) onEvent(ev);
    self.emit(ev.type, ev);
  };
  self.emit("start", {});

  // 分帧缓冲
  let buffer = "";
  const handleChunkText = function (text) {
    buffer += text;
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    blocks.forEach(function (block) {
      const line = block.trim();
      if (line.indexOf("data:") !== 0) return;
      const payload = line.slice(5).trim();
      if (payload === "[DONE]") { self.emit("done", {}); return; }
      try {
        const ev = JSON.parse(payload);
        if (ev.type === "conversation") self.conversationId = ev.conversation_id;
        dispatch(ev);
      } catch (e) { /* 忽略坏帧 */ }
    });
  };

  const request = {
    url: this.baseUrl + "/api/v1/chat/stream",
    method: "POST",
    header: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + this.apiKey,
    },
    data: { conversation_id: this.conversationId, query: query },
    enableChunked: true,
    success: function () { /* 数据经 onChunkReceived 处理 */ },
    fail: function (err) {
      self.emit("error", err && err.errMsg ? err.errMsg : "request failed");
    },
  };

  const task = wx.request(request);
  this._task = task;

  if (task && typeof task.onChunkReceived === "function") {
    const decoder = require("./nexusrag-decoder.js");
    task.onChunkReceived(function (res) {
      // res.data 是 ArrayBuffer
      const text = decoder.decode(res.data);
      if (text) handleChunkText(text);
    });
  } else {
    // 低版本基础库降级：非 chunked 模式，success 一次性拿全文
    request.enableChunked = false;
    request.success = function (resp) {
      if (resp.statusCode !== 200) {
        self.emit("error", "HTTP " + resp.statusCode);
        return;
      }
      handleChunkText(resp.data + "\n\n");
      self.emit("done", {});
    };
    this._task = wx.request(request);
  }
};

module.exports = {
  init: function (opts) { return new NexusClient(opts); },
  NexusClient: NexusClient,
};
