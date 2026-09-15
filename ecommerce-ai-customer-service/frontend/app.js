/* ============================================================
   电商智能客服 - 前端交互
   通过 fetch 调用后端：
     - /chat/stream  流式（SSE）  ← 默认
     - /chat         非流式      ← 兜底
   多轮对话 · 清空对话 · 连接状态 · 快捷提问 · 流式渲染
   ============================================================ */

const STORAGE_SESSION = "cs_session_id";
const STORAGE_API = "cs_api_base";
const STORAGE_STREAM = "cs_stream_mode";
const STORAGE_ASR_ENABLE = "cs_asr_enable";
const STORAGE_ASR_AUTOSEND = "cs_asr_autosend";
const DEFAULT_REMOTE = "http://127.0.0.1:8000";

const SUGGESTIONS = [
  "查一下我的订单 123456",
  "退款多久能到账？",
  "快递一直没更新怎么办？",
  "优惠券可以叠加吗？",
  "我要转人工",
];

function detectApiBase() {
  const saved = localStorage.getItem(STORAGE_API);
  if (saved !== null) return saved.replace(/\/+$/, "");
  if (location.protocol === "file:") return DEFAULT_REMOTE;
  return "";
}

/**
 * Markdown 渲染：marked.js（CDN）可用时用之，不可用则降级纯文本。
 * 同时做基本 XSS 防护：移除 script 与 on* 属性。
 */
function renderMarkdown(text) {
  if (typeof marked === "undefined" || !marked.parse) {
    return escapeHtml(text);
  }
  try {
    // marked v12 默认转义 HTML，但仍做一层 DOMPurify-like 兜底
    const html = marked.parse(text, { breaks: true, gfm: true });
    return sanitizeBasic(html);
  } catch (err) {
    return escapeHtml(text);
  }
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function sanitizeBasic(html) {
  // 兜底：去掉 <script>、on* 属性、javascript: 协议
  return String(html)
    .replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, "")
    .replace(/\son\w+="[^"]*"/gi, "")
    .replace(/\son\w+='[^']*'/gi, "")
    .replace(/javascript:/gi, "");
}

let API_BASE = detectApiBase();
let sessionId = localStorage.getItem(STORAGE_SESSION) || null;
let streamMode =
  localStorage.getItem(STORAGE_STREAM) !== "0"; // 默认开启流式
let asrEnabled = localStorage.getItem(STORAGE_ASR_ENABLE) !== "0"; // 默认开
let asrAutoSend = localStorage.getItem(STORAGE_ASR_AUTOSEND) === "1"; // 默认关
let sending = false;

// ---------- DOM ----------
const chatEl = document.getElementById("chat");
const composerEl = document.getElementById("composer");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("sendBtn");
const micBtn = document.getElementById("micBtn");
const clearBtn = document.getElementById("clearBtn");
const settingsBtn = document.getElementById("settingsBtn");
const settingsEl = document.getElementById("settings");
const apiBaseEl = document.getElementById("apiBase");
const asrToggleEl = document.getElementById("asrToggle");
const asrAutoSendEl = document.getElementById("asrAutoSend");
const suggestEl = document.getElementById("suggest");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const streamToggleEl = document.getElementById("streamToggle");

function api(path) {
  return `${API_BASE}${path}`;
}

function setStatus(online, text) {
  statusDot.classList.toggle("is-online", online === true);
  statusDot.classList.toggle("is-offline", online === false);
  statusText.textContent = text;
}

function scrollToBottom() {
  chatEl.scrollTop = chatEl.scrollHeight;
}

/**
 * 追加一条消息。
 * @returns {{bubble: HTMLElement, metaBox: HTMLElement|null, feedbackBox: HTMLElement|null}}
 */
function appendMessage(role, text, data) {
  const wrap = document.createElement("div");
  wrap.className = `msg msg--${role}`;
  wrap.dataset.role = role;

  const avatar = document.createElement("div");
  avatar.className = "msg__avatar";
  avatar.textContent = role === "bot" ? "AI" : "我";

  const body = document.createElement("div");
  body.className = "msg__body";

  const bubble = document.createElement("div");
  bubble.className = "msg__bubble";
  // 用户消息纯文本（不做 markdown，避免误渲染）；机器人消息走 Markdown
  if (role === "bot") {
    bubble.classList.add("msg__bubble--markdown");
    bubble.innerHTML = renderMarkdown(text);
  } else {
    bubble.textContent = text;
  }
  body.appendChild(bubble);

  const metaBox = document.createElement("div");
  metaBox.className = "msg__meta";
  metaBox.style.display = "none";
  body.appendChild(metaBox);

  // 机器人消息：反馈按钮
  let feedbackBox = null;
  if (role === "bot") {
    feedbackBox = document.createElement("div");
    feedbackBox.className = "msg__feedback";
    feedbackBox.innerHTML = `
      <button type="button" class="fb-btn" data-score="1" title="有帮助">👍</button>
      <button type="button" class="fb-btn" data-score="-1" title="没帮助">👎</button>
      <button type="button" class="fb-btn fb-btn--comment" title="添加评论">💬</button>
    `;
    feedbackBox.style.display = "none";
    body.appendChild(feedbackBox);

    feedbackBox.addEventListener("click", async (e) => {
      const btn = e.target.closest(".fb-btn");
      if (!btn) return;
      const score = btn.dataset.score ? Number(btn.dataset.score) : null;
      const wantComment = btn.classList.contains("fb-btn--comment");
      // 简化版：score 直接提交，comment 按钮提示用户暂未启用
      if (wantComment) {
        alert("评论功能即将上线，敬请期待 ✨");
        return;
      }
      if (score == null) return;
      btn.disabled = true;
      btn.classList.add("fb-btn--active");
      try {
        await sendFeedback(score);
        // 标记同组其他按钮已选
        feedbackBox.querySelectorAll(".fb-btn").forEach((b) => {
          if (b !== btn) b.disabled = true;
        });
        feedbackBox.classList.add("msg__feedback--recorded");
      } catch (err) {
        btn.disabled = false;
        btn.classList.remove("fb-btn--active");
        console.warn("反馈失败：", err);
      }
    });
  }

  wrap.appendChild(avatar);
  wrap.appendChild(body);
  chatEl.appendChild(wrap);
  scrollToBottom();

  if (data) updateMessageMeta(metaBox, data);
  // 显示元信息 + 反馈按钮（仅 bot）
  if (metaBox && metaBox.children.length > 0) metaBox.style.display = "";
  if (feedbackBox) feedbackBox.style.display = "";

  return { bubble, metaBox, feedbackBox };
}

/** 增量更新元信息标签（流式首包 meta 来时调用） */
function updateMessageMeta(metaBox, data) {
  if (!metaBox || !data) return;
  metaBox.innerHTML = "";
  const tags = [];
  if (data.intent && data.intent.label) {
    tags.push({ text: `意图 · ${data.intent.label}`, cls: "tag--primary" });
  }
  if (data.order_no) {
    tags.push({
      text: `订单 · ${data.order_no}${data.order_found ? "" : "（未找到）"}`,
      cls: data.order_found ? "" : "tag--warn",
    });
  }
  if (data.grounded && data.sources && data.sources.length) {
    const ids = data.sources.map((s) => s.id).join("、");
    tags.push({ text: `引用 · ${ids}`, cls: "" });
  }
  if (data.transferred) {
    tags.push({ text: "已提示转人工", cls: "tag--warn" });
  }
  if (!tags.length) {
    metaBox.style.display = "none";
    return;
  }
  tags.forEach((t) => {
    const tag = document.createElement("span");
    tag.className = `tag ${t.cls || ""}`.trim();
    tag.textContent = t.text;
    metaBox.appendChild(tag);
  });
  metaBox.style.display = "";
}

function appendTyping() {
  const wrap = document.createElement("div");
  wrap.className = "msg msg--bot";
  wrap.dataset.role = "bot";
  const avatar = document.createElement("div");
  avatar.className = "msg__avatar";
  avatar.textContent = "AI";
  const body = document.createElement("div");
  body.className = "msg__body";
  const bubble = document.createElement("div");
  bubble.className = "msg__bubble";
  bubble.innerHTML = '<span class="typing"><span></span><span></span><span></span></span>';

  const metaBox = document.createElement("div");
  metaBox.className = "msg__meta";
  metaBox.style.display = "none";

  // 流式阶段预留 feedback 占位；流结束时若 content 非空才显示
  const feedbackBox = document.createElement("div");
  feedbackBox.className = "msg__feedback";
  feedbackBox.style.display = "none";

  body.appendChild(bubble);
  body.appendChild(metaBox);
  body.appendChild(feedbackBox);
  wrap.appendChild(avatar);
  wrap.appendChild(body);
  chatEl.appendChild(wrap);
  scrollToBottom();
  return { wrap, bubble, metaBox, feedbackBox };
}

function showGreeting() {
  appendMessage(
    "bot",
    "你好，我是电商智能客服助手 👋\n我可以帮你查询订单与物流、解答退换货和优惠活动等问题。请问有什么可以帮您？"
  );
}

function renderSuggestions() {
  suggestEl.innerHTML = "";
  SUGGESTIONS.forEach((text) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "suggest__chip";
    chip.textContent = text;
    chip.addEventListener("click", () => {
      inputEl.value = text;
      autoResize();
      composerEl.requestSubmit();
    });
    suggestEl.appendChild(chip);
  });
}

// ---------- 网络 ----------
async function checkHealth() {
  setStatus(null, "连接中…");
  try {
    const resp = await fetch(api("/health"));
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    setStatus(true, `已连接 · v${data.version}`);
  } catch (err) {
    setStatus(false, API_BASE ? "未连接（请检查后端地址）" : "未连接");
  }
}

/** 非流式发送（兜底） */
async function sendMessage(message) {
  const resp = await fetch(api("/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`HTTP ${resp.status} ${detail}`.slice(0, 200));
  }
  const data = await resp.json();
  if (data.session_id) {
    sessionId = data.session_id;
    localStorage.setItem(STORAGE_SESSION, sessionId);
  }
  return data;
}

/** 提交反馈（无需鉴权，按 session_id 归属） */
async function sendFeedback(score) {
  if (!sessionId) {
    console.warn("sendFeedback: no session_id yet");
    return;
  }
  const resp = await fetch(api(`/chat/${sessionId}/feedback`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ score }),
  });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
}

/** SSE 流式：fetch + ReadableStream 手动解析 */
async function sendMessageStream(message, onMeta, onDelta) {
  const resp = await fetch(api("/chat/stream"), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  if (!resp.ok || !resp.body) {
    const detail = await resp.text().catch(() => "");
    throw new Error(`HTTP ${resp.status} ${detail}`.slice(0, 200));
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE 事件以 "\n\n" 分隔
    let sep;
    while ((sep = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      try {
        const payload = JSON.parse(line.slice(5).trim());
        if (payload.event === "meta") {
          if (payload.data.session_id) {
            sessionId = payload.data.session_id;
            localStorage.setItem(STORAGE_SESSION, sessionId);
          }
          onMeta && onMeta(payload.data);
        } else if (payload.event === "delta") {
          onDelta && onDelta(payload.data.text || "");
        } else if (payload.event === "error") {
          throw new Error(payload.data.message || "stream error");
        }
      } catch (err) {
        if (err instanceof SyntaxError) continue;
        throw err;
      }
    }
  }
}

async function clearChat() {
  if (sessionId) {
    try {
      await fetch(api(`/chat/${sessionId}`), { method: "DELETE" });
    } catch (err) {
      /* ignore */
    }
  }
  sessionId = null;
  localStorage.removeItem(STORAGE_SESSION);
  chatEl.innerHTML = "";
  showGreeting();
  inputEl.focus();
}

// ---------- 发送流程 ----------
async function handleSend() {
  const text = inputEl.value.trim();
  if (!text || sending) return;
  sending = true;
  appendMessage("user", text);
  inputEl.value = "";
  autoResize();
  inputEl.disabled = true;
  sendBtn.disabled = true;

  const typing = appendTyping();
  try {
    if (streamMode) {
      // 流式：用 meta + delta 不断填充气泡（Markdown 渲染）
      const { bubble, metaBox, feedbackBox } = typing;
      bubble.classList.add("msg__bubble--markdown");
      bubble.innerHTML = "";
      let buf = "";
      let lastRender = 0;
      const onMeta = (data) => {
        updateMessageMeta(metaBox, data);
      };
      const onDelta = (chunk) => {
        buf += chunk;
        // 16ms 节流（约 60fps）：避免每 token 都重渲染 Markdown
        const now = performance.now();
        if (now - lastRender < 16) return;
        lastRender = now;
        bubble.innerHTML = renderMarkdown(buf);
        scrollToBottom();
      };
      await sendMessageStream(text, onMeta, onDelta);
      // 流结束后再渲染一次完整 Markdown（确保末尾字符齐全）
      bubble.innerHTML = renderMarkdown(buf);
      if (!buf) bubble.textContent = "（无回复）";
      // 显示反馈按钮
      attachFeedbackHandlers(feedbackBox);
      feedbackBox.style.display = "";
      setStatus(true, "已连接");
    } else {
      // 非流式
      const data = await sendMessage(text);
      typing.wrap.remove();
      const { feedbackBox } = appendMessage("bot", data.reply, data);
      attachFeedbackHandlers(feedbackBox);
      setStatus(true, "已连接");
    }
  } catch (err) {
    typing.wrap.remove();
    appendMessage(
      "bot",
      `请求失败：${err.message}\n请确认后端已启动，且「后端地址」配置正确。`
    );
    setStatus(false, "未连接");
  } finally {
    sending = false;
    inputEl.disabled = false;
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

/** 给反馈按钮容器绑定点击事件。 */
function attachFeedbackHandlers(box) {
  if (!box || box.dataset.bound) return;
  box.dataset.bound = "1";
  box.innerHTML = `
    <button type="button" class="fb-btn" data-score="1" title="有帮助">👍</button>
    <button type="button" class="fb-btn" data-score="-1" title="没帮助">👎</button>
  `;
  box.addEventListener("click", async (e) => {
    const btn = e.target.closest(".fb-btn");
    if (!btn || btn.disabled) return;
    const score = Number(btn.dataset.score);
    if (![1, -1].includes(score)) return;
    btn.disabled = true;
    btn.classList.add("fb-btn--active");
    try {
      await sendFeedback(score);
      box.querySelectorAll(".fb-btn").forEach((b) => { if (b !== btn) b.disabled = true; });
      box.classList.add("msg__feedback--recorded");
    } catch (err) {
      btn.disabled = false;
      btn.classList.remove("fb-btn--active");
      console.warn("反馈失败：", err);
    }
  });
}

function autoResize() {
  inputEl.style.height = "auto";
  inputEl.style.height = `${Math.min(inputEl.scrollHeight, 120)}px`;
}

composerEl.addEventListener("submit", (e) => {
  e.preventDefault();
  handleSend();
});

inputEl.addEventListener("input", autoResize);

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
});

clearBtn.addEventListener("click", clearChat);

settingsBtn.addEventListener("click", () => {
  settingsEl.hidden = !settingsEl.hidden;
  if (!settingsEl.hidden) {
    apiBaseEl.value = API_BASE;
    apiBaseEl.focus();
  }
});

apiBaseEl.addEventListener("change", () => {
  const value = apiBaseEl.value.trim().replace(/\/+$/, "");
  API_BASE = value;
  localStorage.setItem(STORAGE_API, value);
  checkHealth();
});

if (streamToggleEl) {
  streamToggleEl.checked = streamMode;
  streamToggleEl.addEventListener("change", () => {
    streamMode = streamToggleEl.checked;
    localStorage.setItem(STORAGE_STREAM, streamMode ? "1" : "0");
  });
}

if (asrToggleEl) {
  asrToggleEl.checked = asrEnabled;
  asrToggleEl.addEventListener("change", () => {
    asrEnabled = asrToggleEl.checked;
    localStorage.setItem(STORAGE_ASR_ENABLE, asrEnabled ? "1" : "0");
    updateMicVisibility();
    if (!asrEnabled && isRecording()) stopRecording();
  });
}

if (asrAutoSendEl) {
  asrAutoSendEl.checked = asrAutoSend;
  asrAutoSendEl.addEventListener("change", () => {
    asrAutoSend = asrAutoSendEl.checked;
    localStorage.setItem(STORAGE_ASR_AUTOSEND, asrAutoSend ? "1" : "0");
  });
}

// ============================================================
// 🎙️  麦克风录音（MediaRecorder → WebSocket /asr/stream，边录边识别）
// ============================================================
//
// 流式 ASR：把 MediaRecorder 的音频 chunk 实时推给后端 WS 端点，
// 后端节流（默认 800ms）跑 faster-whisper，把增量文本作为 "partial"
// 推回来，前端在"识别预览"气泡里实时更新。停止时发 "stop" 触发
// final 识别，回填输入框或自动发送。

let mediaRecorder = null;
let mediaStream = null;
let recordingStartedAt = 0;
let recordingToast = null;
let asrSocket = null;          // 当前录音对应的 WS（null 表示没在流式识别）
let asrPartialTimer = null;    // 输入框 partial 同步 throttle
let asrPreviewBubble = null;   // 实时识别文本的气泡
let asrFinalized = false;      // 防止 WS 关闭后再次 finalize

/**
 * 找/创建"识别预览"气泡：紧贴输入框上方的特殊 bot 气泡。
 * 第一次进入录音时创建；停止时隐藏；下次录音重新创建（保证重新认识）。
 */
function ensurePreviewBubble() {
  if (asrPreviewBubble && asrPreviewBubble.parentNode === chatEl) {
    return asrPreviewBubble;
  }
  // 没在聊天区里 → 新建
  const wrap = document.createElement("div");
  wrap.className = "msg msg--bot msg--preview";
  wrap.dataset.role = "bot";

  const avatar = document.createElement("div");
  avatar.className = "msg__avatar";
  avatar.textContent = "AI";

  const body = document.createElement("div");
  body.className = "msg__body";
  const bubble = document.createElement("div");
  bubble.className = "msg__bubble msg__bubble--preview";
  bubble.innerHTML =
    '<span class="typing"><span></span><span></span><span></span></span>';

  body.appendChild(bubble);
  wrap.appendChild(avatar);
  wrap.appendChild(body);
  chatEl.appendChild(wrap);
  scrollToBottom();
  asrPreviewBubble = wrap;
  return wrap;
}

/** 把"识别预览"气泡的内容替换为 partial text。空文本保留 typing 动画。 */
function updatePreviewBubble(text) {
  if (!asrPreviewBubble) return;
  const bubble = asrPreviewBubble.querySelector(".msg__bubble");
  if (!text) return;
  // 中文 / 标点 直接显示（不渲染 Markdown，避免误识别 # 等字符）
  bubble.classList.remove("msg__bubble--markdown");
  bubble.textContent = text;
}

function hidePreviewBubble() {
  if (asrPreviewBubble && asrPreviewBubble.parentNode) {
    asrPreviewBubble.parentNode.removeChild(asrPreviewBubble);
  }
  asrPreviewBubble = null;
}

function updateMicVisibility() {
  if (!micBtn) return;
  const supported =
    typeof navigator !== "undefined" &&
    navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === "function" &&
    typeof window.MediaRecorder === "function" &&
    typeof window.WebSocket === "function";
  if (!supported) {
    micBtn.hidden = true;
    micBtn.title = "当前浏览器不支持录音";
    return;
  }
  micBtn.hidden = !asrEnabled;
  if (asrEnabled) {
    micBtn.title =
      asrSocket || isRecording() ? "点击停止录音" : "点击开始录音";
  }
}

function isRecording() {
  return !!(mediaRecorder && mediaRecorder.state === "recording");
}

function showRecordingToast(text) {
  if (!recordingToast) {
    recordingToast = document.createElement("div");
    recordingToast.className = "recording-toast";
    document.body.appendChild(recordingToast);
  }
  recordingToast.textContent = text;
  recordingToast.style.display = "block";
}

function hideRecordingToast() {
  if (recordingToast) recordingToast.style.display = "none";
}

function pickRecorderMime() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
    "",
  ];
  for (const m of candidates) {
    if (m === "" || (window.MediaRecorder && MediaRecorder.isTypeSupported(m))) {
      return m;
    }
  }
  return "";
}

/** 把 ``http(s)://host`` 翻译成 ``ws(s)://host``。*/
function wsBase() {
  return API_BASE.replace(/^http/i, "ws");
}

/** 全推到输入框的 partial 同步 throttle（避免每 100ms 改 DOM）*/
function pushPartialToInput(text) {
  if (!text) return;
  if (asrPartialTimer) return;
  asrPartialTimer = setTimeout(() => {
    asrPartialTimer = null;
    inputEl.value = text;
    autoResize();
  }, 60);
}

/** WebSocket 收到消息统一处理 */
function handleAsrMessage(ev) {
  let msg;
  try {
    msg = JSON.parse(ev.data);
  } catch (_) {
    return;
  }
  if (msg.event === "ready") {
    // 模型状态等，可用于显示
    return;
  }
  if (msg.event === "partial") {
    const text = msg.text || "";
    updatePreviewBubble(text);
    pushPartialToInput(text);
    showRecordingToast(
      `●  识别中…  ·  ${fmtDuration(Math.floor((Date.now() - recordingStartedAt) / 1000))}  ·  ${text.length} 字`
    );
    return;
  }
  if (msg.event === "final") {
    const text = (msg.text || "").trim();
    finalizeStreamingAsr(text, msg);
    return;
  }
  if (msg.event === "error") {
    appendMessage(
      "bot",
      `🎙️ 流式识别错误：${msg.message || msg.code || "未知错误"}`
    );
    // 不主动停录音，让用户决定
    return;
  }
  if (msg.event === "closed") {
    // 服务端已关
    return;
  }
}

/** streaming 识别收尾：把 final text 落进输入框，按需自动发送 */
function finalizeStreamingAsr(finalText, msg) {
  asrFinalized = true;
  hidePreviewBubble();
  hideRecordingToast();
  // 录音状态清理
  if (mediaStream) {
    mediaStream.getTracks().forEach((t) => t.stop());
    mediaStream = null;
  }
  mediaRecorder = null;
  micBtn && micBtn.classList.remove("composer__mic--recording");
  if (micBtn) micBtn.disabled = false;
  inputEl.disabled = false;
  sendBtn.disabled = false;
  updateMicVisibility();

  if (!finalText) {
    appendMessage(
      "bot",
      "🎙️ 没识别到有效文字（可能录音太短或环境嘈杂）。\n可重录或直接打字。"
    );
    setStatus(true, "已连接");
    return;
  }

  inputEl.value = finalText;
  autoResize();
  inputEl.focus();

  if (asrAutoSend && !sending) {
    composerEl.requestSubmit
      ? composerEl.requestSubmit()
      : composerEl.dispatchEvent(new Event("submit", { cancelable: true }));
  } else {
    const dur = (msg && msg.duration_s) ? msg.duration_s.toFixed(1) : "?";
    appendMessage(
      "bot",
      `🎙️ 识别完成（${dur}s → ${finalText.length} 字）。\n已回填到输入框，点发送即可。`
    );
  }
  setStatus(true, "已连接");
}

/** 主动断开 WS（用户关闭浏览器、网络断开等） */
function closeAsrSocket(reason) {
  if (!asrSocket) return;
  try {
    if (asrSocket.readyState === WebSocket.OPEN) {
      asrSocket.close(1000, reason || "client-stop");
    }
  } catch (_) {
    /* ignore */
  }
  asrSocket = null;
}

async function startRecording() {
  if (isRecording()) return;

  // 1) 先开 WS（确保服务端 ready 后再请求麦克风，最大化带宽利用）
  const wsUrl = `${wsBase()}/asr/stream`;
  let sock;
  try {
    sock = new WebSocket(wsUrl);
  } catch (err) {
    appendMessage(
      "bot",
      `🎙️ 当前浏览器不支持 WebSocket，无法流式识别。\n详情：${err.message || err}`
    );
    return;
  }
  asrSocket = sock;
  asrFinalized = false;

  // 等 WS open 再请求麦克风（避免拿不到权限时已经开了 socket）
  await new Promise((resolve, reject) => {
    const t = setTimeout(
      () => reject(new Error("WS 连接超时（10s）")),
      10000
    );
    sock.addEventListener("open", () => {
      clearTimeout(t);
      sock.send(JSON.stringify({
        event: "start",
        sample_rate: 16000,
        language: "auto",
        auto_send: asrAutoSend,
        session_id: sessionId || null,
        partial_interval_ms: 600,
      }));
      resolve();
    });
    sock.addEventListener("error", () => {
      clearTimeout(t);
      reject(new Error("WS 连接失败，请确认后端 /asr/stream 可访问"));
    });
  });

  sock.addEventListener("message", handleAsrMessage);
  sock.addEventListener("close", () => {
    if (!asrFinalized) {
      // 没收到 final → 用户切走了 / 网络掉 → 当作失败
      hidePreviewBubble();
      hideRecordingToast();
      appendMessage("bot", "🎙️ 流式识别连接中断，请重试。");
    }
    asrSocket = null;
  });
  sock.addEventListener("error", () => {
    // 服务端已经发送 error 帧时这里也会触发，记录到 silent flag 防止双倍报错
  });

  // 2) 麦克风
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
    });
  } catch (err) {
    closeAsrSocket("mic-denied");
    appendMessage(
      "bot",
      `🎙️ 无法访问麦克风：${err.message || err.name}\n请确认浏览器已获授权（地址栏左侧的小锁图标）。`
    );
    return;
  }

  // 3) MediaRecorder → 每 250ms 推一份 binary 到 WS
  const mime = pickRecorderMime();
  try {
    mediaRecorder = mime
      ? new MediaRecorder(mediaStream, { mimeType: mime })
      : new MediaRecorder(mediaStream);
  } catch (err) {
    closeAsrSocket("recorder-fail");
    appendMessage("bot", `🎙️ 创建录音器失败：${err.message || err}`);
    mediaStream.getTracks().forEach((t) => t.stop());
    mediaStream = null;
    return;
  }

  mediaRecorder.ondataavailable = (e) => {
    if (!e.data || e.data.size === 0) return;
    if (!asrSocket || asrSocket.readyState !== WebSocket.OPEN) return;
    try {
      asrSocket.send(e.data);  // 二进制帧
    } catch (_) {
      /* ignore：连接已断则后面对 close 事件兜底 */
    }
  };

  recordingStartedAt = Date.now();
  mediaRecorder.start(250); // 每 250ms 产出一个 chunk
  micBtn && micBtn.classList.add("composer__mic--recording");
  ensurePreviewBubble();    // 立即出"识别中…"动画
  inputEl.disabled = true;
  sendBtn.disabled = true;
  if (micBtn) micBtn.disabled = false;
  setStatus(null, "🎙️ 录音中…");
  showRecordingToast(`●  录音中（停止请点击 🎙️）  ·  ${fmtDuration(0)}`);
  const tick = setInterval(() => {
    if (!isRecording()) {
      clearInterval(tick);
      return;
    }
    const sec = Math.floor((Date.now() - recordingStartedAt) / 1000);
    const toast = recordingToast;
    if (toast && toast.style.display !== "none") {
      toast.textContent = `●  录音中  ·  ${fmtDuration(sec)}`;
    }
  }, 1000);
}

function fmtDuration(seconds) {
  const m = String(Math.floor(seconds / 60)).padStart(2, "0");
  const s = String(seconds % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function stopRecording() {
  // 1) 停止 MediaRecorder（触发最后一个 dataavailable → 推给 WS）
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
  // 2) 给 WS 发 "stop" → 服务端跑最后一次识别并发 final
  if (asrSocket && asrSocket.readyState === WebSocket.OPEN) {
    try {
      asrSocket.send(JSON.stringify({ event: "stop" }));
    } catch (_) {
      /* ignore */
    }
  }
}

if (micBtn) {
  micBtn.addEventListener("click", () => {
    if (isRecording()) {
      stopRecording();
    } else {
      startRecording();
    }
  });
  // 进入页面时根据浏览器能力决定按钮是否可见
  updateMicVisibility();
  // 浏览器权限在用户首次点击 🔒 时才显示；这里给个提示
  if (micBtn.hidden && asrEnabled) {
    // 按钮被强制隐藏（浏览器不支持）
  }
}

renderSuggestions();
showGreeting();
checkHealth();
autoResize();
inputEl.focus();