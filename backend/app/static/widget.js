/*!
 * NexusRAG Chat Widget — 零依赖网页聊天挂件
 *
 * 用法（一行嵌入）：
 *   <script src="https://your-host/widget.js" data-key="nx-你的应用APIKey" defer></script>
 *
 * 或编程式：
 *   NexusChat.init({ apiKey: "nx-xxx", baseUrl: "https://your-host" })
 */
(function () {
  "use strict";

  var scriptEl =
    document.currentScript ||
    (function () {
      var all = document.getElementsByTagName("script");
      for (var i = all.length - 1; i >= 0; i--) {
        if (all[i].src && all[i].src.indexOf("widget.js") !== -1) return all[i];
      }
      return null;
    })();

  function defaultBase() {
    if (scriptEl && scriptEl.src) return scriptEl.src.replace(/\/widget\.js.*$/, "");
    return "";
  }

  var DEFAULTS = {
    apiKey: scriptEl ? scriptEl.getAttribute("data-key") || "" : "",
    baseUrl: scriptEl ? scriptEl.getAttribute("data-base") || defaultBase() : "",
    theme: "#1677ff",
    title: "智能助手",
    welcome: "你好，请问有什么可以帮你？",
    bubble: "💬",
  };

  var state = {
    cfg: DEFAULTS,
    open: false,
    busy: false,
    conversationId: null,
    messages: [],
  };

  // ---------- SSE ----------

  function postChat(question, onEvent, done, fail) {
    var base = state.cfg.baseUrl.replace(/\/$/, "");
    fetch(base + "/api/v1/chat/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + state.cfg.apiKey,
      },
      body: JSON.stringify({
        conversation_id: state.conversationId,
        query: question,
      }),
    })
      .then(function (resp) {
        if (!resp.ok || !resp.body) throw new Error("HTTP " + resp.status);
        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";
        function pump() {
          reader
            .read()
            .then(function (r) {
              if (r.done) return done();
              buffer += decoder.decode(r.value, { stream: true });
              var blocks = buffer.split("\n\n");
              buffer = blocks.pop() || "";
              blocks.forEach(function (block) {
                var line = block.trim();
                if (line.indexOf("data:") !== 0) return;
                var payload = line.slice(5).trim();
                if (payload === "[DONE]") return done();
                try {
                  onEvent(JSON.parse(payload));
                } catch (e) {
                  /* 忽略坏帧 */
                }
              });
              pump();
            })
            .catch(fail);
        }
        pump();
      })
      .catch(fail);
  }

  // ---------- UI ----------

  var ui = {};

  function css(theme) {
    return (
      ":host{all:initial}" +
      "*{box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif}" +
      ".bubble{position:fixed;right:20px;bottom:20px;width:56px;height:56px;border-radius:50%;background:" +
      theme +
      ";color:#fff;font-size:26px;display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,.25);z-index:2147483000;transition:transform .15s}" +
      ".bubble:hover{transform:scale(1.08)}" +
      ".panel{position:fixed;right:20px;bottom:90px;width:360px;max-width:calc(100vw - 32px);height:520px;max-height:calc(100vh - 120px);background:#fff;border-radius:14px;box-shadow:0 8px 40px rgba(0,0,0,.2);display:none;flex-direction:column;overflow:hidden;z-index:2147483000}" +
      ".panel.open{display:flex}" +
      ".hd{background:" +
      theme +
      ";color:#fff;padding:14px 16px;display:flex;align-items:center;gap:10px}" +
      ".hd .t{font-size:15px;font-weight:600;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" +
      ".hd .x{cursor:pointer;font-size:18px;opacity:.8;padding:2px 6px}" +
      ".bd{flex:1;overflow-y:auto;padding:14px;background:#f7f8fa}" +
      ".msg{max-width:82%;margin-bottom:12px;padding:9px 12px;border-radius:10px;font-size:14px;line-height:1.6;white-space:pre-wrap;word-break:break-word}" +
      ".m-u{background:" +
      theme +
      ";color:#fff;margin-left:auto}" +
      ".m-a{background:#fff;border:1px solid #eceef2}" +
      ".cites{margin-top:6px;padding-top:6px;border-top:1px dashed #e0e0e0;font-size:11px;color:#888}" +
      ".cites span{display:inline-block;background:#f0f2f5;border-radius:4px;padding:1px 6px;margin:2px 4px 0 0;color:#555}" +
      ".tools{font-size:11px;color:#999;margin-bottom:4px}" +
      ".typing{display:inline-flex;gap:4px;padding:4px 0}" +
      ".typing i{width:6px;height:6px;border-radius:50%;background:#bbb;animation:blink 1.2s infinite}" +
      ".typing i:nth-child(2){animation-delay:.2s}.typing i:nth-child(3){animation-delay:.4s}" +
      "@keyframes blink{0%,80%,100%{opacity:.25}40%{opacity:1}}" +
      ".ft{padding:10px;border-top:1px solid #f0f0f0;background:#fff;display:flex;gap:8px}" +
      ".ft input{flex:1;border:1px solid #e3e5e8;border-radius:8px;padding:9px 12px;font-size:14px;outline:none}" +
      ".ft input:focus{border-color:" +
      theme +
      "}" +
      ".ft button{background:" +
      theme +
      ";color:#fff;border:none;border-radius:8px;width:40px;font-size:16px;cursor:pointer}" +
      ".ft button:disabled{opacity:.5}" +
      "@media (max-width:480px){.panel{right:8px;left:8px;width:auto;bottom:84px}}"
    );
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function buildWidget() {
    var host = document.createElement("div");
    host.id = "nexusrag-widget-host";
    var root = host.attachShadow({ mode: "open" });
    var style = document.createElement("style");
    style.textContent = css(state.cfg.theme);
    root.appendChild(style);

    var bubble = el("div", "bubble", state.cfg.bubble);
    var panel = el("div", "panel");

    var hd = el("div", "hd");
    var hdTitle = el("div", "t", state.cfg.title);
    var closeBtn = el("div", "x", "✕");
    hd.appendChild(hdTitle);
    hd.appendChild(closeBtn);

    var body = el("div", "bd");

    var foot = el("div", "ft");
    var input = el("input");
    input.placeholder = "输入消息…";
    var sendBtn = el("button", null, "➤");
    foot.appendChild(input);
    foot.appendChild(sendBtn);

    panel.appendChild(hd);
    panel.appendChild(body);
    panel.appendChild(foot);
    root.appendChild(bubble);
    root.appendChild(panel);
    document.body.appendChild(host);

    ui = { root: root, bubble: bubble, panel: panel, body: body, input: input, sendBtn: sendBtn, hdTitle: hdTitle };

    bubble.addEventListener("click", toggle);
    closeBtn.addEventListener("click", toggle);
    sendBtn.addEventListener("click", send);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") send();
    });
  }

  function toggle() {
    state.open = !state.open;
    ui.panel.classList.toggle("open", state.open);
    if (state.open && !ui.body.children.length) {
      appendBot(state.cfg.welcome);
    }
    if (state.open) ui.input.focus();
  }

  function scrollBottom() {
    ui.body.scrollTop = ui.body.scrollHeight;
  }

  function appendUser(text) {
    ui.body.appendChild(el("div", "msg m-u", text));
    scrollBottom();
  }

  function appendBot(text) {
    var wrap = el("div", "msg m-a", text || "");
    ui.body.appendChild(wrap);
    scrollBottom();
    return wrap;
  }

  function showTyping() {
    var t = el("div", "msg m-a");
    t.classList.add("typing-wrap");
    var box = el("span", "typing");
    box.appendChild(el("i"));
    box.appendChild(el("i"));
    box.appendChild(el("i"));
    t.appendChild(box);
    ui.body.appendChild(t);
    scrollBottom();
    return t;
  }

  function send() {
    var text = ui.input.value.trim();
    if (!text || state.busy) return;
    ui.input.value = "";
    appendUser(text);
    state.busy = true;
    ui.sendBtn.disabled = true;

    var typing = showTyping();
    var bubbleEl = null;
    var citations = null;
    var toolLines = [];

    postChat(
      text,
      function (ev) {
        if (ev.type === "conversation") {
          state.conversationId = ev.conversation_id;
          try {
            sessionStorage.setItem("nx_chat_" + ev.conversation_id, ev.conversation_id);
          } catch (e) {}
        } else if (ev.type === "tool_call") {
          toolLines.push("⚙ 调用 " + ev.name + "…");
        } else if (ev.type === "tool_result") {
          toolLines.push((ev.ok ? "✓ " : "✗ ") + ev.name + " 完成");
        } else if (ev.type === "delta") {
          if (!bubbleEl) {
            typing.remove();
            bubbleEl = appendBot("");
            if (toolLines.length) {
              bubbleEl.appendChild(el("div", "tools", toolLines.join("　")));
            }
            var txt = el("span", "txt");
            bubbleEl.appendChild(txt);
            bubbleEl.__txt = txt;
          }
          bubbleEl.__txt.textContent += ev.content;
          scrollBottom();
        } else if (ev.type === "citations") {
          citations = ev.citations;
        }
      },
      function () {
        if (typing.parentNode) typing.remove();
        if (!bubbleEl) {
          bubbleEl = appendBot("（无回复）");
        }
        if (citations && citations.length) {
          var c = el("div", "cites", "来源：");
          citations.forEach(function (ct) {
            c.appendChild(el("span", null, "[" + ct.index + "] " + ct.document_name));
          });
          bubbleEl.appendChild(c);
        }
        state.busy = false;
        ui.sendBtn.disabled = false;
        scrollBottom();
      },
      function (err) {
        if (typing.parentNode) typing.remove();
        appendBot("⚠️ 连接失败: " + (err && err.message ? err.message : err));
        state.busy = false;
        ui.sendBtn.disabled = false;
      }
    );
  }

  // ---------- init ----------

  function init(opts) {
    state.cfg = {};
    for (var k in DEFAULTS) state.cfg[k] = DEFAULTS[k];
    if (opts) for (var k2 in opts) state.cfg[k2] = opts[k2];
    if (!state.cfg.apiKey) {
      console.error("[NexusChat] 缺少 apiKey");
      return;
    }

    fetch(state.cfg.baseUrl.replace(/\/$/, "") + "/api/v1/widget/config", {
      headers: { Authorization: "Bearer " + state.cfg.apiKey },
    })
      .then(function (r) {
        if (!r.ok) throw new Error("config HTTP " + r.status);
        return r.json();
      })
      .then(function (cfg) {
        if (cfg.title) state.cfg.title = cfg.title;
        if (cfg.welcome) state.cfg.welcome = cfg.welcome;
        if (cfg.theme) state.cfg.theme = cfg.theme;
        if (cfg.bubble) state.cfg.bubble = cfg.bubble;
      })
      .catch(function (e) {
        console.warn("[NexusChat] 配置拉取失败，使用默认值", e);
      })
      .then(function () {
        if (document.readyState === "loading") {
          document.addEventListener("DOMContentLoaded", buildWidget);
        } else {
          buildWidget();
        }
      });
  }

  window.NexusChat = {
    init: init,
    open: function () {
      if (!state.open && ui.panel) toggle();
    },
    close: function () {
      if (state.open && ui.panel) toggle();
    },
  };

  // data-key 自动初始化
  if (scriptEl && scriptEl.getAttribute("data-key")) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () {
        init({});
      });
    } else {
      init({});
    }
  }
})();
