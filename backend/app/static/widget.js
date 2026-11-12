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
    // 终端用户身份：data-user-id/-name/-sig/-ts 由页面后端签发（HMAC 票据），
    // 用于历史会话归属与工具的业务参数注入（见 docs 终端用户接入）
    userId: scriptEl ? scriptEl.getAttribute("data-user-id") || "" : "",
    userName: scriptEl ? scriptEl.getAttribute("data-user-name") || "" : "",
    sig: scriptEl ? scriptEl.getAttribute("data-sig") || "" : "",
    ts: scriptEl ? Number(scriptEl.getAttribute("data-ts")) || 0 : 0,
    metadata: null, // 业务参数（token/order_id 等），仅服务端可见，不进 Prompt
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
    // 历史懒加载游标：convs 按更新时间倒序（[0] 最新），convIdx=-1 表示还没进历史链；
    // 发送目标恒为 state.conversationId（最新会话），往上翻阅旧会话不影响回复落点
    hist: { convs: [], convIdx: -1, hasMore: false, oldestId: null, loading: false, loaded: false, done: false },
  };

  // 对话过程展示档位（应用 widget_config.process_display 下发）：
  //   full  = 完整协作（规划/agent接手/工具全显示）
  //   tools = 仅工具调用行（默认：不显示规划与 agent 接手过程）
  //   none  = 只出最终回答
  function procOK(kind) {
    var d = state.cfg.process_display || "tools";
    if (d === "none") return false;
    if (d === "full") return true;
    return kind === "tool"; // tools 档：工具行显示，规划/接手/完成行不显示
  }

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
        end_user: state.cfg.userId
          ? { id: state.cfg.userId, name: state.cfg.userName || "" }
          : undefined,
        metadata: state.cfg.metadata || undefined,
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
      ".new-btn{cursor:pointer;font-size:12px;opacity:.92;padding:3px 9px;border:1px solid rgba(255,255,255,.55);border-radius:6px;white-space:nowrap}" +
      // 下拉懒加载：顶部加载指示 / 跨会话分隔条 / 到底提示
      ".hist-loading{text-align:center;font-size:12px;color:#999;padding:6px 0}" +
      ".hist-divider{text-align:center;font-size:11px;color:#aaa;margin:10px 0 12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" +
      ".hist-end{text-align:center;font-size:11px;color:#bbb;padding:4px 0 8px}" +
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
    if (state.cfg.userId) {
      var newBtn = el("div", "new-btn", "新对话");
      newBtn.addEventListener("click", startNewConversation);
      hd.appendChild(newBtn);
    }
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
    // 下拉懒加载：滚到顶部时拉更早的记录（跨会话自动续链）
    body.addEventListener("scroll", function () {
      if (body.scrollTop <= 0) pullOlder();
    });
  }

  function toggle() {
    state.open = !state.open;
    ui.panel.classList.toggle("open", state.open);
    if (state.open && !ui.body.children.length) {
      // 有身份的终端用户：打开即续接最近会话（最新一页），更早的下拉加载
      if (state.cfg.userId && state.cfg.sig) loadLatest();
      else appendBot(state.cfg.welcome);
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

  // ---------- 终端用户：历史会话 ----------
  // 身份来自页面后端签发的 HMAC 票据（data-* 或 window.NexusChatConfig）；
  // 服务端验签后按 end_user_id 隔离返回，挂件拿不到别人的会话。

  function authQuery() {
    return (
      "end_user_id=" + encodeURIComponent(state.cfg.userId || "") +
      "&ts=" + (state.cfg.ts || 0) +
      "&sig=" + encodeURIComponent(state.cfg.sig || "")
    );
  }

  function authHeaders() {
    return { Authorization: "Bearer " + state.cfg.apiKey };
  }

  function apiError(r) {
    return r.json().then(function (e) {
      throw new Error((e && e.detail) || "HTTP " + r.status);
    });
  }

  function renderCites(bubbleEl, citations) {
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

  // ---------- 下拉懒加载历史 ----------
  // 打开面板续接最近会话（最新一页）；滚到顶部按页拉更早的记录，
  // 当前会话翻完自动接更早的会话（分隔条标注），全部翻完显示到底提示。
  // 发送目标恒为最新会话，翻阅旧会话不影响回复落点。

  function histBase() {
    return state.cfg.baseUrl.replace(/\/$/, "") + "/api/v1/chat";
  }

  function fetchPage(convId, before) {
    var url =
      histBase() + "/conversations/" + convId + "/messages?" +
      authQuery() + "&limit=30" + (before ? "&before=" + encodeURIComponent(before) : "");
    return fetch(url, { headers: authHeaders() }).then(function (r) {
      if (!r.ok) return apiError(r);
      return r.json();
    });
  }

  // 历史消息渲染（与流式回复同一套样式）：user 纯文本，assistant 走 Markdown + 引用
  function buildMsg(m) {
    if (m.role === "user") return el("div", "msg m-u", m.content);
    if (m.role !== "assistant") return null;
    var b = el("div", "msg m-a");
    var txt = el("span", "txt");
    txt.innerHTML = renderMarkdown(m.content);
    b.appendChild(txt);
    if (m.citations && m.citations.length) renderCites(b, m.citations);
    return b;
  }

  function prependNode(node) {
    if (!node) return;
    ui.body.insertBefore(node, ui.body.firstChild);
  }

  function loadLatest() {
    var typing = showTyping();
    fetch(histBase() + "/conversations?" + authQuery(), { headers: authHeaders() })
      .then(function (r) {
        if (!r.ok) return apiError(r);
        return r.json();
      })
      .then(function (list) {
        typing.remove();
        var h = state.hist;
        h.convs = list || [];
        h.loaded = true;
        if (!h.convs.length) {
          h.done = true;
          appendBot(state.cfg.welcome);
          return;
        }
        h.convIdx = 0;
        state.conversationId = h.convs[0].id;
        return fetchPage(h.convs[0].id, null).then(function (page) {
          page.messages.forEach(function (m) {
            var node = buildMsg(m);
            if (node) ui.body.appendChild(node);
          });
          h.oldestId = page.messages.length ? page.messages[0].id : null;
          h.hasMore = page.has_more;
          if (!page.messages.length) appendBot(state.cfg.welcome);
          scrollBottom();
        });
      })
      .catch(function (e) {
        if (typing.parentNode) typing.remove();
        appendBot(state.cfg.welcome);
        appendBot("⚠️ 历史记录加载失败: " + (e && e.message ? e.message : e));
      });
  }

  function pullOlder() {
    var h = state.hist;
    if (!state.cfg.userId || !h.loaded || h.loading || h.done || !state.open) return;
    // 判断还有没有可拉的内容：当前会话有更早页，或还有更早的会话
    var convExhausted = h.convIdx >= 0 && !h.hasMore;
    if (convExhausted && h.convIdx + 1 >= h.convs.length) {
      h.done = true;
      prependNode(el("div", "hist-end", "— 已加载全部历史记录 —"));
      return;
    }
    h.loading = true;
    var prevH = ui.body.scrollHeight;
    var loader = el("div", "hist-loading", "加载更早的记录…");
    prependNode(loader);
    var work;
    if (h.convIdx >= 0 && h.hasMore) {
      // 当前会话往上翻一页
      work = fetchPage(h.convs[h.convIdx].id, h.oldestId).then(function (page) {
        // prepend 是逐条插到最顶上：按升序正着插会把整批倒过来，必须逆序遍历
        for (var i = page.messages.length - 1; i >= 0; i--) {
          var m = page.messages[i];
          prependNode(buildMsg(m));
          h.oldestId = m.id;
        }
        h.hasMore = page.has_more;
      });
    } else {
      // 当前会话翻完 → 接更早的会话
      h.convIdx += 1;
      var conv = h.convs[h.convIdx];
      var label = conv.title || "未命名对话";
      var time = String(conv.updated_at || "").replace("T", " ").slice(0, 16);
      var divider = el("div", "hist-divider", "— 更早 · " + label + " · " + time + " —");
      work = fetchPage(conv.id, null).then(function (page) {
        for (var j = page.messages.length - 1; j >= 0; j--) {
          var m2 = page.messages[j];
          prependNode(buildMsg(m2));
          h.oldestId = m2.id;
        }
        prependNode(divider); // 分隔条最后插，落在这批更早消息的最上方
        h.hasMore = page.has_more;
      });
    }
    work
      .catch(function (e) {
        prependNode(el("div", "hist-end", "⚠️ 加载失败: " + (e && e.message ? e.message : e)));
      })
      .then(function () {
        loader.remove();
        // 保持视口稳定：内容向前插入了 delta 高度，滚动位置同步下移
        ui.body.scrollTop = ui.body.scrollHeight - prevH;
        h.loading = false;
        // 一次下拉可能仍停在顶部（比如刚跨到只有少量消息的旧会话），继续补拉
        if (ui.body.scrollTop <= 0) pullOlder();
      });
  }

  function startNewConversation() {
    if (state.busy) return;
    state.conversationId = null; // 下一条消息由服务端新建会话
    var h = state.hist;
    h.convIdx = -1;
    h.hasMore = false;
    h.oldestId = null;
    h.done = false;
    // convs 保留：新会话产生后，旧会话自然成为下拉链上的“更早历史”
    ui.body.innerHTML = "";
    appendBot(state.cfg.welcome);
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
        } else if (ev.type === "plan") {
          var subs = ev.subtasks || [];
          if (subs.length && procOK("agent")) {
            toolLines.push("📋 规划 " + subs.length + " 个子任务：" +
              subs.map(function (s) { return (s.worker || "") + "·" + (s.title || ""); }).join("、"));
          }
        } else if (ev.type === "agent_start") {
          if (procOK("agent")) toolLines.push("🤖 " + ev.agent + " 接手：" + (ev.task || "") + "…");
        } else if (ev.type === "agent_done") {
          if (procOK("agent")) toolLines.push("✅ " + ev.agent + " 完成");
        } else if (ev.type === "tool_call") {
          if (procOK("tool")) {
            var tag = ev.agent ? "[" + ev.agent + "] " : "";
            toolLines.push(tag + "⚙ 调用 " + ev.name + "…");
          }
        } else if (ev.type === "tool_result") {
          if (procOK("tool")) {
            var tag2 = ev.agent ? "[" + ev.agent + "] " : "";
            toolLines.push(tag2 + (ev.ok ? "✓ " : "✗ ") + ev.name + " 完成");
          }
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
    // 页面全局配置可覆盖 data-*（适合页面动态拿到票据后注入再初始化）：
    // window.NexusChatConfig = { userId, userName, sig, ts, metadata }
    var g = window.NexusChatConfig || {};
    ["userId", "userName", "sig", "ts", "metadata"].forEach(function (k3) {
      if (g[k3] !== undefined && g[k3] !== null && g[k3] !== "") state.cfg[k3] = g[k3];
    });
    if (!state.cfg.metadata && window.NexusChatMetadata) state.cfg.metadata = window.NexusChatMetadata;
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
        // 对话过程展示档位（应用 widget_config.process_display）：
        // full=规划/agent接手/工具全显示 | tools=仅工具行 | none=只出最终回答
        if (["full", "tools", "none"].indexOf(cfg.process_display) !== -1) {
          state.cfg.process_display = cfg.process_display;
        }
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
