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
    bubble: "icon:comment",
  };

  // 悬浮球图标：icon:<key> 用内置 SVG 图标库；img:<dataURL> 用用户上传图片；
  // 其他值（旧数据 emoji）按文字渲染保持兼容
  var BUBBLE_ICONS = {
    comment:
      '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    headset:
      '<path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"/>',
    robot:
      '<rect x="4" y="9" width="16" height="11" rx="2"/><path d="M12 9V5M9 5h6"/><line x1="9" y1="14" x2="9.01" y2="14"/><line x1="15" y1="14" x2="15.01" y2="14"/>',
    send: '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
  };

  function bubbleContent(val) {
    var v = val || "icon:comment";
    if (v.indexOf("img:") === 0) {
      var img = document.createElement("img");
      img.src = v.slice(4);
      img.style.cssText =
        "width:100%;height:100%;border-radius:50%;object-fit:cover;display:block";
      return img;
    }
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "26");
    svg.setAttribute("height", "26");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "#fff");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    var name = v.indexOf("icon:") === 0 ? v.slice(5) : "";
    if (!BUBBLE_ICONS[name]) {
      // 旧数据：非 icon:/img: 的值当作 emoji/文字
      return document.createTextNode(v || "💬");
    }
    svg.innerHTML = BUBBLE_ICONS[name];
    return svg;
  }

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
        // done 只允许触发一次：[DONE] 帧和流关闭（r.done）都可能到达，
        // 不加守卫会把完成回调（含引用渲染）执行两遍
        var finished = false;
        function finish() {
          if (finished) return;
          finished = true;
          done();
        }
        function pump() {
          reader
            .read()
            .then(function (r) {
              if (r.done) return finish();
              buffer += decoder.decode(r.value, { stream: true });
              var blocks = buffer.split("\n\n");
              buffer = blocks.pop() || "";
              blocks.forEach(function (block) {
                var line = block.trim();
                if (line.indexOf("data:") !== 0) return;
                var payload = line.slice(5).trim();
                if (payload === "[DONE]") return finish();
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
      ".bubble:hover{transform:scale(1.08)}.bubble svg{pointer-events:none}.bubble img{pointer-events:none}" +
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
      ".m-a .txt{white-space:normal}" +
      ".txt p{margin:6px 0}" +
      ".txt h1,.txt h2,.txt h3,.txt h4,.txt h5{margin:8px 0 4px;font-size:14px;font-weight:700}" +
      ".txt ul,.txt ol{margin:4px 0;padding-left:18px}" +
      ".txt li{margin:2px 0}" +
      ".txt code{background:rgba(0,0,0,.06);padding:1px 4px;border-radius:3px;font-family:Consolas,Menlo,monospace;font-size:12.5px}" +
      ".txt pre{background:#f6f8fa;border:1px solid #eceef2;padding:8px;border-radius:6px;overflow:auto;margin:6px 0}" +
      ".txt pre code{background:none;padding:0}" +
      ".txt strong{font-weight:600}" +
      ".txt a{color:#1c6eff}" +
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

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function inlineMd(s) {
    return s
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  }
  // 轻量 Markdown：标题 / 无序有序列表 / 粗斜体 / 行内码 / 围栏代码块 / 链接 / 段落。
  // 全程先 escapeHtml 再套标签，LLM 输出里的 HTML 不会被执行。
  function renderMarkdown(src) {
    var lines = escapeHtml(src).split("\n");
    var out = [], inCode = false, codeBuf = [], listTag = null;
    function closeList() {
      if (listTag) { out.push("</" + listTag + ">"); listTag = null; }
    }
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (/^```/.test(line.trim())) {
        if (inCode) { out.push("<pre><code>" + codeBuf.join("\n") + "</code></pre>"); codeBuf = []; inCode = false; }
        else { closeList(); inCode = true; }
        continue;
      }
      if (inCode) { codeBuf.push(line); continue; }
      var h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) {
        closeList();
        var lv = Math.min(h[1].length + 1, 5);
        out.push("<h" + lv + ">" + inlineMd(h[2]) + "</h" + lv + ">");
        continue;
      }
      var li = line.match(/^\s*[-*+]\s+(.*)$/);
      var oli = line.match(/^\s*(\d+)[.、]\s+(.*)$/);
      if (li) {
        if (listTag !== "ul") { closeList(); out.push("<ul>"); listTag = "ul"; }
        out.push("<li>" + inlineMd(li[1]) + "</li>");
        continue;
      }
      if (oli) {
        if (listTag !== "ol") { closeList(); out.push("<ol>"); listTag = "ol"; }
        out.push("<li>" + inlineMd(oli[2]) + "</li>");
        continue;
      }
      if (!line.trim()) { closeList(); continue; }
      closeList();
      out.push("<p>" + inlineMd(line) + "</p>");
    }
    if (inCode) out.push("<pre><code>" + codeBuf.join("\n") + "</code></pre>");
    closeList();
    return out.join("");
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

    var bubble = el("div", "bubble");
    bubble.appendChild(bubbleContent(state.cfg.bubble));
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
          bubbleEl.__raw = (bubbleEl.__raw || "") + ev.content;
          bubbleEl.__txt.innerHTML = renderMarkdown(bubbleEl.__raw);
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
          var seenCite = {};
          citations.forEach(function (ct) {
            var head = ct.heading ? " · " + String(ct.heading).slice(0, 24) : "";
            var label = "[" + ct.index + "] " + ct.document_name + head;
            if (seenCite[label]) return;
            seenCite[label] = 1;
            c.appendChild(el("span", null, label));
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
