/**
 * 小程序 SDK 单测（Node 环境，模拟 wx.request 的 chunked 传输）。
 * 运行：node miniprogram/test.js  （exit 0 = 全过）
 */

// ---------- 模拟 wx ----------
function makeWx(chunks, opts) {
  opts = opts || {};
  return {
    request(req) {
      if (opts.noChunked) {
        // 低版本降级：success 一次性回调
        setTimeout(() => {
          req.success({ statusCode: 200, data: opts.fullText });
        }, 0);
        return { abort() {} };
      }
      const listeners = {};
      setTimeout(() => {
        for (const c of chunks) {
          if (listeners.chunk) listeners.chunk({ data: toArrayBuffer(c) });
        }
        if (listeners.done) listeners.done();
      }, 0);
      return {
        onChunkReceived(fn) { listeners.chunk = fn; },
        abort() {},
      };
    },
  };
}

function toArrayBuffer(str) {
  const buf = Buffer.from(str, "utf-8");
  const ab = new ArrayBuffer(buf.length);
  new Uint8Array(ab).set(buf);
  return ab;
}

function strToUtf8ArrayBuffer(str) {
  return toArrayBuffer(str);
}

let pass = 0;
let fail = 0;
function test(name, fn) {
  try {
    fn();
    pass++;
    console.log("  ✓ " + name);
  } catch (e) {
    fail++;
    console.error("  ✗ " + name + "\n    " + e.message);
  }
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

// 加载 SDK（全局 wx 由各测试临时替换）
global.wx = { request() { throw new Error("wx not mocked"); } };
const nexus = require("./nexusrag.js");
const decoder = require("./nexusrag-decoder.js");

console.log("nexusrag miniprogram SDK tests:");

// ---------- decoder：UTF-8 多字节跨 chunk 拆分（强制 fallback 路径） ----------
test("decoder fallback 处理跨 chunk 的中文字节拆分", () => {
  const realTD = global.TextDecoder;
  delete global.TextDecoder; // 强制走手写解码
  decoder.reset();
  const whole = "退款政策";
  const bytes = Buffer.from(whole, "utf-8");
  // 拆成任意位置：逐字节喂也能拼回完整文本
  const ab1 = new ArrayBuffer(bytes.length - 1);
  new Uint8Array(ab1).set(bytes.subarray(0, bytes.length - 1));
  const ab2 = new ArrayBuffer(1);
  new Uint8Array(ab2).set(bytes.subarray(bytes.length - 1));
  const s1 = decoder.decode(ab1);
  const s2 = decoder.decode(ab2);
  assert(s1 + s2 === whole, `got '${s1}${s2}'`);
  global.TextDecoder = realTD;
  decoder.reset();
});

// ---------- SSE 分帧解析 ----------
function runChat(chunks, opts) {
  global.wx = makeWx(chunks, opts);
  const captured = [];
  const client = nexus.init({ apiKey: "nx-test", baseUrl: "https://x.io" });
  const p = new Promise((resolve) => {
    client.on("done", resolve);
    client.chat("hi", (ev) => captured.push(ev));
  });
  return { client, captured, promise: p };
}

async function main() {
  await (async () => {
    // 事件被拆在两个 chunk 中 + 多事件合并
    const chunks = [
      'data: {"type":"convers',
      'ation","conversation_id":"c-123"}\n\ndata: {"type":"delta","content":"你好"}\n',
      '\ndata: {"type":"delta","content":"世界"}\n\ndata: [DONE]\n\n',
    ];
    const { captured, promise } = runChat(chunks);
    await promise;
    test("SSE 事件跨 chunk 分帧解析", () => {
      const types = captured.map((e) => e.type);
      assert(types.indexOf("conversation") >= 0, "missing conversation: " + types);
      assert(types.filter((t) => t === "delta").length === 2, "missing deltas: " + types);
    });
  })();

  await (async () => {
    // 中文 delta 内容按字节任意拆分（附 done 终止帧）
    const full = JSON.stringify({ type: "delta", content: "知识图谱增强检索" });
    const frame = "data: " + full + '\n\ndata: {"type":"done"}\n\n';
    const bytes = Buffer.from(frame, "utf-8");
    const mid = Math.floor(bytes.length / 3);
    const ab1 = new ArrayBuffer(mid);
    new Uint8Array(ab1).set(bytes.subarray(0, mid));
    const ab2 = new ArrayBuffer(bytes.length - mid);
    new Uint8Array(ab2).set(bytes.subarray(mid));
    // 直接喂 ArrayBuffer
    global.wx = {
      request() {
        const listeners = {};
        setTimeout(() => {
          listeners.chunk({ data: ab1 });
          listeners.chunk({ data: ab2 });
        }, 0);
        return { onChunkReceived(fn) { listeners.chunk = fn; }, abort() {} };
      },
    };
    const client = nexus.init({ apiKey: "k", baseUrl: "https://x.io" });
    const captured = [];
    await new Promise((r) => {
      client.on("done", r);
      client.chat("q", (ev) => captured.push(ev));
    });
    test("中文 UTF-8 帧拆分解析", () => {
      assert(captured[0] && captured[0].content === "知识图谱增强检索", JSON.stringify(captured));
    });
  })();

  await (async () => {
    // conversation_id 持久化到 client
    const { client, promise } = runChat([
      'data: {"type":"conversation","conversation_id":"c-999"}\n\ndata: [DONE]\n\n',
    ]);
    await promise;
    test("conversation_id 持久化", () => {
      assert(client.conversationId === "c-999", "got " + client.conversationId);
    });
  })();

  await (async () => {
    // 低版本降级：非 chunked 一次性全文
    global.wx = makeWx([], {
      noChunked: true,
      fullText:
        'data: {"type":"delta","content":"完整回复"}\n\ndata: {"type":"done"}\n\n',
    });
    const client = nexus.init({ apiKey: "k", baseUrl: "https://x.io" });
    const captured = [];
    await new Promise((r) => {
      client.on("done", r);
      client.chat("q", (ev) => captured.push(ev));
    });
    test("低版本基础库降级（非流式全文）", () => {
      assert(captured.some((e) => e.type === "delta" && e.content === "完整回复"), JSON.stringify(captured));
    });
  })();

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
}

main();
