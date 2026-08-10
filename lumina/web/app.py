from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from lumina.config import Settings, get_settings
from lumina.config_edit import write_env
from lumina.factory import build_agent
from lumina.store import SessionStore, default_db_path
from lumina.types import Message

_EDITABLE_KEYS = (
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_PLANNER_MODEL",
    "LUMINA_MAX_TOKENS",
    "LUMINA_TOKEN_BUDGET",
    "LUMINA_MAX_ITERATIONS",
    "LUMINA_TEMPERATURE",
    "LUMINA_ENABLE_PLANNER",
    "LUMINA_COMPRESSION",
    "LUMINA_SELF_REVIEW",
)


def _config_payload(s: Settings) -> dict:
    payload: dict = {}
    for field_name, field in Settings.model_fields.items():
        alias = field.alias
        if alias in _EDITABLE_KEYS:
            payload[alias] = getattr(s, field_name)
    return payload

_INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>LuminaCoder</title>
<script>
try { document.documentElement.setAttribute("data-theme", localStorage.getItem("lumina-theme") || "light"); } catch (e) {}
</script>
<style>
  :root {
    --bg: #fafafa; --panel: #ffffff; --panel2: #f4f4f5; --border: #d4d4d8;
    --text: #18181b; --muted: #71717a; --accent: #6366f1; --user: #2563eb;
    --code-bg: #f1f0f3; --code-text: #18181b;
    --error-bg: #fef2f2; --error-border: #f87171; --error-text: #dc2626;
    --thinking-bg: #fafafa; --thinking-text: #3f3f46;
    --tool-bg: #ffffff;
    --approval-bg: #fffbeb;
    --header-bg: rgba(250, 250, 250, .85);
    --mono: ui-monospace, "Cascadia Code", Consolas, monospace;
  }
  [data-theme="dark"] {
    --bg: #09090b; --panel: #18181b; --panel2: #27272a; --border: #3f3f46;
    --text: #e4e4e7; --muted: #a1a1aa; --accent: #818cf8; --user: #3b82f6;
    --code-bg: #0d0d10; --code-text: #e4e4e7;
    --error-bg: #2a1215; --error-border: #7f1d1d; --error-text: #fca5a5;
    --thinking-bg: #0f0f12; --thinking-text: #cbd5e1;
    --tool-bg: #131316;
    --approval-bg: #241a05;
    --header-bg: rgba(9, 9, 11, .8);
  }
  * { box-sizing: border-box; }
  body { margin: 0; height: 100vh; display: flex; flex-direction: column;
         background: var(--bg); color: var(--text);
         transition: background .2s ease, color .2s ease;
         font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
  header { padding: 10px 20px; display: flex; gap: 10px; align-items: center;
           border-bottom: 1px solid var(--border); background: var(--header-bg); backdrop-filter: blur(8px); }
  header strong { font-size: 14px; letter-spacing: .2px; }
  header .spacer { flex: 1; }
  select, button, input { background: var(--panel2); color: var(--text); border: 1px solid var(--border);
                          border-radius: 8px; padding: 6px 10px; font-size: 13px; outline: none; }
  button { cursor: pointer; }
  button:hover { border-color: var(--accent); }
  #main { flex: 1; overflow-y: auto; scroll-behavior: smooth; }
  #log { max-width: 800px; margin: 0 auto; padding: 20px; }
  .msg { margin-bottom: 14px; line-height: 1.6; font-size: 14px; word-break: break-word; }
  .msg .bubble { display: inline-block; padding: 9px 14px; border-radius: 14px; }
  .msg.user { display: flex; justify-content: flex-end; }
  .msg.user .bubble { background: var(--user); color: #fff; border-bottom-right-radius: 4px; max-width: 85%; }
  .msg.assistant .bubble { background: var(--panel); border: 1px solid var(--border);
                           border-bottom-left-radius: 4px; max-width: 100%; }
  .msg .markdown h1, .msg .markdown h2, .msg .markdown h3 { margin: .6em 0 .3em; line-height: 1.3; }
  .msg .markdown h1 { font-size: 17px; } .msg .markdown h2 { font-size: 15px; } .msg .markdown h3 { font-size: 14px; }
  .msg .markdown p { margin: .4em 0; }
  .msg .markdown ul, .msg .markdown ol { margin: .4em 0; padding-left: 22px; }
  .msg .markdown li { margin: .15em 0; }
  .msg .markdown code { background: var(--panel2); border: 1px solid var(--border); border-radius: 4px;
                        padding: 1px 5px; font-family: var(--mono); font-size: 12.5px; }
  .msg .markdown pre { background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px;
                       padding: 10px 12px; overflow-x: auto; }
  .msg .markdown pre code { background: none; border: none; padding: 0; font-size: 12.5px; color: var(--code-text); }
  .msg .markdown blockquote { margin: .4em 0; padding: 2px 12px; border-left: 3px solid var(--accent);
                              color: var(--muted); }
  .msg .markdown a { color: var(--accent); }
  .msg.error .bubble { background: var(--error-bg); border: 1px solid var(--error-border); color: var(--error-text); }
  details.thinking { margin: 10px 0 14px; border: 1px dashed var(--border); border-radius: 10px;
                     background: var(--thinking-bg); }
  details.thinking summary { cursor: pointer; user-select: none; padding: 7px 12px;
                             color: var(--muted); font-size: 13px; display: flex; gap: 8px; align-items: center; }
  details.thinking summary::before { content: "🧠"; font-size: 12px; }
  details.thinking[open] summary { border-bottom: 1px solid var(--border); }
  details.thinking .think-body { padding: 8px 12px 12px; font-size: 13px; color: var(--thinking-text);
                                 line-height: 1.55; }
  details.thinking .think-body pre, details.thinking .think-body code { font-family: var(--mono); }
  .tool-card { margin: 6px 0 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--tool-bg); }
  .tool-card .tool-head { display: flex; gap: 8px; align-items: center; padding: 6px 10px; cursor: pointer; user-select: none; }
  .tool-card .tool-head:hover { background: var(--panel2); border-radius: 10px; }
  .tool-card .dot { width: 7px; height: 7px; border-radius: 50%; background: #8b5cf6; flex: none; }
  .tool-card .tname { color: #8b5cf6; font-family: var(--mono); font-size: 12px; }
  .tool-card .targs { color: var(--muted); font-size: 11px; font-family: var(--mono);
                      overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
  .tool-card .chev { color: var(--muted); font-size: 11px; }
  .tool-card .tool-body { display: none; border-top: 1px solid var(--border); padding: 10px 12px;
                          max-height: 300px; overflow: auto; }
  .tool-card .tool-body pre { margin: 0; white-space: pre-wrap; word-break: break-word;
                              font-family: var(--mono); font-size: 12px; color: var(--code-text); }
  .tool-card.err { border-color: var(--error-border); } .tool-card.err .dot { background: #ef4444; }
  .approval { margin: 10px 0; padding: 10px 14px; border: 1px solid #f59e0b; border-radius: 10px;
              background: var(--approval-bg); font-size: 13px; }
  .approval .approval-actions { margin-top: 8px; display: flex; gap: 8px; }
  .approval .approval-actions button { padding: 4px 14px; font-size: 13px; }
  .approval .approval-actions button.ok { background: #16a34a; border-color: #16a34a; color: #fff; }
  .approval .approval-actions button.no { background: #dc2626; border-color: #dc2626; color: #fff; }
  .stat { color: var(--muted); font-size: 12px; font-family: ui-monospace, Consolas, monospace; }
  #inputbar { display: flex; gap: 8px; padding: 14px 20px; border-top: 1px solid var(--border);
              background: var(--header-bg); }
  #inputwrap { flex: 1; max-width: 800px; margin: 0 auto; display: flex; gap: 8px; align-items: center; }
  #input { flex: 1; background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
           padding: 11px 14px; color: var(--text); font-size: 14px; }
  #input:focus { border-color: var(--accent); }
  #send { background: var(--accent); border: none; color: #fff; border-radius: 10px; padding: 10px 20px; cursor: pointer; }
  #send:disabled { opacity: .4; cursor: not-allowed; }
  label { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--muted);
          cursor: pointer; white-space: nowrap; }
  label input { accent-color: var(--accent); }
  .modal-overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, .45); display: none;
                   align-items: flex-start; justify-content: center; z-index: 50; padding: 40px 16px; }
  .modal-overlay.open { display: flex; }
  .modal { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; width: 100%;
           max-width: 560px; padding: 20px 22px; max-height: 82vh; overflow: auto; }
  .modal h3 { margin: 0 0 4px; font-size: 16px; }
  .modal .hint { color: var(--muted); font-size: 12px; margin: 0 0 14px; line-height: 1.5; }
  .modal .field { margin-bottom: 12px; }
  .modal .field label { display: block; margin-bottom: 4px; font-size: 12px; }
  .modal .row { display: flex; gap: 12px; }
  .modal .row .field { flex: 1; }
  .modal input[type=text], .modal input[type=password], .modal input[type=number] { width: 100%; }
  .modal .cb { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
  .modal .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
  .modal .actions .save { background: var(--accent); border: none; color: #fff; }
  .modal .save-note { color: #16a34a; font-size: 12px; margin-top: 8px; }
  ::-webkit-scrollbar { width: 10px; } ::-webkit-scrollbar-thumb { background: var(--panel2); border-radius: 5px; }
</style>
</head>
<body>
<header>
  <strong>LuminaCoder</strong>
  <select id="sessions" onchange="switchSession(this.value)"></select>
  <button onclick="newSession()">新建</button>
  <button onclick="renameSession()">重命名</button>
  <button onclick="deleteSession()" style="background:transparent;border-color:transparent;color:#f87171;">删除</button>
  <span class="spacer"></span>
  <span id="tokStat" class="stat" style="display:none;"></span>
  <button id="themeBtn" onclick="toggleTheme()" title="切换深色/浅色">🌙</button>
  <button onclick="openSettings()" title="编辑配置">⚙ 设置</button>
  <button id="stopBtn" onclick="stopRun()" style="display:none;color:#f87171;border-color:#7f1d1d;">停止</button>
  <label><input id="autoApprove" type="checkbox"/>自动批准</label>
</header>
<div id="main"><div id="log"></div></div>
<div id="inputbar"><div id="inputwrap">
  <input id="input" placeholder="描述任务，例如：帮我修复失败的测试" autofocus/>
  <button id="send" onclick="send()">发送</button>
</div></div>
<div id="settingsOverlay" class="modal-overlay" onclick="if(event.target===this)closeSettings()">
  <div class="modal">
    <h3>设置</h3>
    <p class="hint">修改将写入工作区 <code>.env</code> 文件。保存后新会话生效；运行中的任务不受影响。</p>
    <div class="field"><label>API Key</label><input id="cfg_DEEPSEEK_API_KEY" type="password" autocomplete="off"/></div>
    <div class="field"><label>Base URL</label><input id="cfg_DEEPSEEK_BASE_URL" type="text"/></div>
    <div class="row">
      <div class="field"><label>模型 (DEEPSEEK_MODEL)</label><input id="cfg_DEEPSEEK_MODEL" type="text"/></div>
      <div class="field"><label>规划模型 (DEEPSEEK_PLANNER_MODEL)</label><input id="cfg_DEEPSEEK_PLANNER_MODEL" type="text"/></div>
    </div>
    <div class="row">
      <div class="field"><label>单次请求输出上限 (LUMINA_MAX_TOKENS ≤8192)</label><input id="cfg_LUMINA_MAX_TOKENS" type="number"/></div>
      <div class="field"><label>任务累计预算 (LUMINA_TOKEN_BUDGET)</label><input id="cfg_LUMINA_TOKEN_BUDGET" type="number"/></div>
    </div>
    <div class="row">
      <div class="field"><label>最大迭代 (LUMINA_MAX_ITERATIONS)</label><input id="cfg_LUMINA_MAX_ITERATIONS" type="number"/></div>
      <div class="field"><label>温度 (LUMINA_TEMPERATURE)</label><input id="cfg_LUMINA_TEMPERATURE" type="number" step="0.1"/></div>
    </div>
    <label class="cb"><input id="cfg_LUMINA_ENABLE_PLANNER" type="checkbox"/>启用 Reasoner 规划 (LUMINA_ENABLE_PLANNER)</label>
    <label class="cb"><input id="cfg_LUMINA_COMPRESSION" type="checkbox"/>上下文压缩 (LUMINA_COMPRESSION)</label>
    <label class="cb"><input id="cfg_LUMINA_SELF_REVIEW" type="checkbox"/>完成时自我审查 (LUMINA_SELF_REVIEW)</label>
    <div class="actions">
      <button onclick="closeSettings()">取消</button>
      <button class="save" onclick="saveSettings()">保存</button>
    </div>
    <div id="saveNote" class="save-note"></div>
  </div>
</div>
<script>
const ws = new WebSocket(`ws://${location.host}/ws`);
const log = document.getElementById("log");
const main = document.getElementById("main");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const sel = document.getElementById("sessions");
let busy = false;
let currentSession = null;
let streamEl = null, mdBuf = "";
let thinkingEl = null, thinkBuf = "";
let pendingTool = null;
let inputHistory = [];
let histIndex = -1;
let tokenUsed = 0;

function setBusy(b){ busy = b; sendBtn.disabled = b; document.getElementById("stopBtn").style.display = b ? "inline-block" : "none"; }
function updateTok(){
  const el = document.getElementById("tokStat");
  if (tokenUsed > 0) { el.textContent = "tokens: " + tokenUsed; el.style.display = "inline"; }
  else el.style.display = "none";
}

function scrollBottom(){ main.scrollTop = main.scrollHeight; }

/* ---------- markdown (minimal, safe) ---------- */
function esc(s){ return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function renderMarkdown(src){
  let s = esc(String(src || "").replace(/\\r\\n/g, "\\n"));
  const stash = [];
  const key = () => "\\u0000" + stash.length + "\\u0000";
  s = s.replace(/```([\\w+-]*)\\n([\\s\\S]*?)```/g, (m, lang, code) => { const k = key(); stash.push("<pre><code>"+code+"</code></pre>"); return k; });
  s = s.replace(/`([^`\\n]+)`/g, (m, c) => { const k = key(); stash.push("<code>"+c+"</code>"); return k; });
  s = s.replace(/\\*\\*([^*]+)\\*\\*/g, (m, t) => "<strong>"+t+"</strong>");
  s = s.replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)\\s]+)\\)/g, (m, t, u) => '<a href="'+u+'" target="_blank" rel="noopener noreferrer">'+t+"</a>");
  const lines = s.split("\\n");
  let out = "";
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const h = line.match(/^(#{1,3})\\s+(.*)$/);
    if (h) { out += "<h"+h[1].length+">"+h[2]+"</h"+h[1].length+">"; i++; continue; }
    if (/^\\u0000\\d+\\u0000$/.test(line.trim())) { out += stash[+line.trim().replace(/\\u0000/g,"")] || ""; i++; continue; }
    if (/^&gt; /.test(line)) { const q=[]; while (i<lines.length && /^&gt; /.test(lines[i])) { q.push(lines[i].replace(/^&gt; /,"")); i++; } out += "<blockquote>"+q.join("<br>")+"</blockquote>"; continue; }
    if (/^[-*] /.test(line)) { const it=[]; while (i<lines.length && /^[-*] /.test(lines[i])) { it.push(lines[i].replace(/^[-*] /,"")); i++; } out += "<ul>"+it.map(x=>"<li>"+x+"</li>").join("")+"</ul>"; continue; }
    if (/^\\d+\\. /.test(line)) { const it=[]; while (i<lines.length && /^\\d+\\. /.test(lines[i])) { it.push(lines[i].replace(/^\\d+\\. /,"")); i++; } out += "<ol>"+it.map(x=>"<li>"+x+"</li>").join("")+"</ol>"; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() !== "") { para.push(lines[i]); i++; }
    if (para.length) out += "<p>"+para.join("<br>")+"</p>";
    i++;
  }
  out = out.replace(/\\u0000(\\d+)\\u0000/g, (m, n) => stash[+n] || "");
  return out;
}

/* ---------- DOM helpers ---------- */
function appendMd(cls, text, bubble){
  const div = document.createElement("div");
  div.className = "msg " + cls;
  const inner = document.createElement("div");
  inner.className = "bubble markdown";
  inner.innerHTML = renderMarkdown(text);
  div.appendChild(inner);
  log.appendChild(div);
  scrollBottom();
  return inner;
}
function appendStat(text){
  const div = document.createElement("div");
  div.className = "msg stat";
  div.textContent = text;
  log.appendChild(div);
  scrollBottom();
  return div;
}
function toolCard(name, args){
  const card = document.createElement("div");
  card.className = "tool-card";
  const head = document.createElement("div");
  head.className = "tool-head";
  const dot = document.createElement("span"); dot.className = "dot";
  const tname = document.createElement("span"); tname.className = "tname"; tname.textContent = name;
  const targs = document.createElement("span"); targs.className = "targs";
  const argText = JSON.stringify(args || {});
  targs.textContent = argText.length > 80 ? argText.slice(0, 80) + "…" : argText;
  const chev = document.createElement("span"); chev.className = "chev"; chev.textContent = "▸";
  head.appendChild(dot); head.appendChild(tname); head.appendChild(targs); head.appendChild(chev);
  const body = document.createElement("div");
  body.className = "tool-body";
  const pre = document.createElement("pre");
  pre.textContent = "$ " + name + " " + argText;
  body.appendChild(pre);
  head.onclick = () => {
    const open = body.style.display !== "none";
    body.style.display = open ? "none" : "block";
    chev.textContent = open ? "▸" : "▾";
  };
  card.appendChild(head); card.appendChild(body);
  log.appendChild(card);
  scrollBottom();
  return { card, body, pre };
}
function resetStream(){ streamEl = null; mdBuf = ""; }

/* ---------- websocket ---------- */
ws.onopen = () => ws.send(JSON.stringify({ type: "list" }));
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.type === "sessions") renderSessions(m.sessions);
  else if (m.type === "session") { currentSession = m.session.id; tokenUsed = 0; updateTok(); }
  else if (m.type === "session_cleared") { currentSession = null; tokenUsed = 0; updateTok(); log.innerHTML = ""; }
  else if (m.type === "history") {
    m.messages.forEach(msg => {
      if (msg.role === "user") appendMd("user", msg.content);
      else if (msg.role === "assistant") appendMd("assistant", msg.content);
    });
  } else if (m.type === "reasoning") {
    if (!thinkingEl) {
      const det = document.createElement("details");
      det.className = "thinking";
      det.open = false;
      const sum = document.createElement("summary");
      sum.textContent = "Thinking";
      const tb = document.createElement("div");
      tb.className = "think-body";
      det.appendChild(sum); det.appendChild(tb);
      log.appendChild(det);
      thinkingEl = tb;
      thinkBuf = "";
    }
    thinkBuf += m.chunk;
    thinkingEl.innerHTML = renderMarkdown(thinkBuf);
    scrollBottom();
  } else if (m.type === "stream") {
    if (!streamEl) {
      const div = document.createElement("div");
      div.className = "msg assistant";
      const inner = document.createElement("div");
      inner.className = "bubble markdown";
      div.appendChild(inner);
      log.appendChild(div);
      streamEl = inner;
      mdBuf = "";
    }
    mdBuf += m.chunk;
    streamEl.innerHTML = renderMarkdown(mdBuf);
    scrollBottom();
  } else if (m.type === "tool_call") {
    resetStream();
    pendingTool = toolCard(m.name, m.arguments);
  } else if (m.type === "tool_result") {
    const card = pendingTool || toolCard(m.name, {});
    pendingTool = null;
    if (m.is_error) card.card.classList.add("err");
    const line = document.createElement("pre");
    line.textContent = "\\n[" + (m.is_error ? "error" : "ok") + "]\\n" + (m.content || "");
    card.body.appendChild(line);
    scrollBottom();
  } else if (m.type === "approval_request") {
    if (document.getElementById("autoApprove").checked) { respond(m.request_id, true); return; }
    const box = document.createElement("div");
    box.className = "approval";
    box.textContent = "需要批准: " + m.name + " (" + m.reason + ")";
    const actions = document.createElement("div");
    actions.className = "approval-actions";
    const yes = document.createElement("button");
    yes.className = "ok"; yes.textContent = "批准";
    yes.onclick = () => { box.textContent = "[已批准] " + m.name; respond(m.request_id, true); };
    const no = document.createElement("button");
    no.className = "no"; no.textContent = "拒绝";
    no.onclick = () => { box.textContent = "[已拒绝] " + m.name; box.classList.add("err"); respond(m.request_id, false); };
    actions.appendChild(yes); actions.appendChild(no);
    box.appendChild(actions);
    log.appendChild(box);
    scrollBottom();
  } else if (m.type === "done") {
    resetStream();
    setBusy(false);
    tokenUsed += m.total_tokens || 0;
    updateTok();
    let hint = "";
    if (m.stopped_reason === "budget_exhausted") hint = " （已达累计 token 预算，可在 .env 调大 LUMINA_TOKEN_BUDGET）";
    appendStat("[done] iter=" + m.iterations + " tools=" + m.tool_calls + " tokens=" + m.total_tokens + " stop=" + m.stopped_reason + hint);
  } else if (m.type === "cancelled") {
    resetStream(); setBusy(false);
    appendStat("[stopped] 任务已手动停止");
  } else if (m.type === "error") {
    resetStream(); setBusy(false);
    appendMd("error", "错误: " + m.message);
  }
};

function renderSessions(sessions) {
  const prev = currentSession;
  sel.innerHTML = "";
  sessions.forEach(s => {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = "#" + s.id + " " + (s.title || "").slice(0, 24) + " (" + s.messages + ")";
    sel.appendChild(opt);
  });
  if (prev != null && sessions.some(s => s.id === prev)) sel.value = prev;
}
function respond(id, approved) {
  ws.send(JSON.stringify({ type: "approval_response", request_id: id, approved }));
}
function switchSession(id) {
  if (busy || !id) return;
  log.innerHTML = "";
  thinkingEl = null; resetStream(); pendingTool = null;
  tokenUsed = 0; updateTok();
  ws.send(JSON.stringify({ type: "resume", session_id: Number(id) }));
}
function newSession() {
  if (busy) return;
  ws.send(JSON.stringify({ type: "new_session" }));
}
function renameSession() {
  if (busy || !currentSession) return;
  const cur = (sel.selectedOptions[0] ? sel.selectedOptions[0].textContent : "").replace(/^#[\\d]+ /, "");
  const t = prompt("新的会话标题", cur);
  if (t === null) return;
  ws.send(JSON.stringify({ type: "rename_session", session_id: currentSession, title: t }));
}
function stopRun() {
  ws.send(JSON.stringify({ type: "cancel" }));
}
function deleteSession() {
  if (busy || !currentSession) return;
  if (!confirm("确定删除会话 #" + currentSession + " 吗？该操作不可恢复。")) return;
  ws.send(JSON.stringify({ type: "delete_session", session_id: currentSession }));
}
function send() {
  const text = input.value.trim();
  if (!text || busy) return;
  inputHistory.push(text); if (inputHistory.length > 100) inputHistory.shift();
  histIndex = inputHistory.length;
  setBusy(true);
  thinkingEl = null; resetStream(); pendingTool = null;
  appendMd("user", text);
  ws.send(JSON.stringify({ type: "message", content: text }));
  input.value = "";
}
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter") send();
  else if (e.key === "ArrowUp") { if (inputHistory.length && histIndex > 0) { histIndex--; input.value = inputHistory[histIndex]; } }
  else if (e.key === "ArrowDown") { if (histIndex < inputHistory.length) { histIndex++; input.value = histIndex < inputHistory.length ? inputHistory[histIndex] : ""; } }
});
document.getElementById("autoApprove").addEventListener("change", (e) => {
  ws.send(JSON.stringify({ type: "set_auto", value: e.target.checked }));
});

/* ---------- theme toggle ---------- */
let theme = localStorage.getItem("lumina-theme") || "light";
document.documentElement.setAttribute("data-theme", theme);
function updateThemeBtn(){ document.getElementById("themeBtn").textContent = theme === "light" ? "🌙" : "☀"; }
updateThemeBtn();
function toggleTheme(){
  theme = theme === "light" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("lumina-theme", theme);
  updateThemeBtn();
}

/* ---------- settings panel ---------- */
function openSettings(){
  document.getElementById("saveNote").textContent = "";
  fetch("/api/config").then(r => r.json()).then(cfg => {
    Object.keys(cfg).forEach(k => {
      const el = document.getElementById("cfg_" + k);
      if (el) { if (el.type === "checkbox") el.checked = !!cfg[k]; else el.value = cfg[k] == null ? "" : cfg[k]; }
    });
  });
  document.getElementById("settingsOverlay").classList.add("open");
}
function closeSettings(){ document.getElementById("settingsOverlay").classList.remove("open"); }
function saveSettings(){
  const fields = {};
  document.querySelectorAll("#settingsOverlay input").forEach(el => {
    const key = el.id.replace("cfg_", "");
    fields[key] = el.type === "checkbox" ? el.checked : el.value.trim();
  });
  fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  }).then(r => r.json()).then(res => {
    document.getElementById("saveNote").textContent =
      res.ok ? "已保存到 .env，新会话将使用新配置。" : ("保存失败: " + (res.message || ""));
  });
}
</script>
</body>
</html>"""


class WsApprover:
    """Approval via WebSocket: ask over WS, wait for the client response."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.queue: asyncio.Queue[bool] = asyncio.Queue()
        self.auto = False
        self._counter = 0

    async def approve(self, name: str, arguments: dict[str, Any], reason: str) -> bool:
        if self.auto:
            return True
        self._counter += 1
        await self.ws.send_json(
            {"type": "approval_request", "request_id": self._counter, "name": name, "reason": reason}
        )
        try:
            return await asyncio.wait_for(self.queue.get(), timeout=300)
        except asyncio.TimeoutError:
            return False

    def submit(self, approved: bool) -> None:
        self.queue.put_nowait(approved)


class WsHooks:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws

    async def on_assistant_message(self, chunk: str) -> None:
        await self.ws.send_json({"type": "stream", "chunk": chunk})

    async def on_reasoning(self, chunk: str) -> None:
        await self.ws.send_json({"type": "reasoning", "chunk": chunk})

    async def on_tool_call(self, call) -> None:
        await self.ws.send_json(
            {"type": "tool_call", "name": call.name, "arguments": call.arguments}
        )

    async def on_tool_result(self, result) -> None:
        await self.ws.send_json(
            {"type": "tool_result", "name": result.name, "is_error": result.is_error, "content": result.content[:2000]}
        )


def create_app(settings: Settings, workspace: Path) -> FastAPI:
    app = FastAPI(title="LuminaCoder")
    workspace = Path(workspace).resolve()
    store = SessionStore(default_db_path(workspace))
    app.state.workspace = workspace
    app.state.settings = settings

    def session_payload(sid: int) -> dict:
        s = store.get_session(sid)
        return {"id": sid, "title": s.title if s else "", "messages": s.message_count if s else 0}

    async def push_sessions(ws: WebSocket) -> None:
        await ws.send_json(
            {"type": "sessions", "sessions": [session_payload(s.id) for s in store.list_sessions(workspace)]}
        )

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _INDEX_HTML

    @app.get("/api/config")
    async def get_config() -> dict:
        return _config_payload(app.state.settings)

    @app.post("/api/config")
    async def post_config(payload: dict[str, Any]) -> dict:
        updates: dict[str, str] = {}
        for key in _EDITABLE_KEYS:
            if key in payload:
                value = payload[key]
                if isinstance(value, bool):
                    value = "true" if value else "false"
                updates[key] = str(value)
        if not updates:
            return {"ok": False, "message": "no valid configuration fields"}
        try:
            write_env(app.state.workspace / ".env", updates)
        except OSError as exc:
            return {"ok": False, "message": str(exc)}
        get_settings.cache_clear()
        app.state.settings = get_settings()
        return {"ok": True}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        approver = WsApprover(ws)
        agent = build_agent(app.state.workspace, app.state.settings, approver, WsHooks(ws))
        current_session: int | None = None
        running: asyncio.Task | None = None

        async def run_in_background(content: str, sid: int, history: list[Message]) -> None:
            """Runs the agent in a background task so approvals stay responsive."""
            try:
                result = await agent.run(
                    content,
                    history=history,
                    persist=lambda m, sid_=sid: store.append_message(sid_, m),
                )
                await ws.send_json(
                    {
                        "type": "done",
                        "iterations": result.iterations,
                        "tool_calls": result.tool_calls_made,
                        "total_tokens": result.total_tokens,
                        "stopped_reason": result.stopped_reason,
                        "final_content": result.final_content,
                    }
                )
            except asyncio.CancelledError:
                try:
                    await ws.send_json({"type": "cancelled"})
                except Exception:  # noqa: BLE001, S110
                    pass
                raise
            except Exception as exc:  # noqa: BLE001
                await ws.send_json({"type": "error", "message": str(exc)})
            finally:
                try:
                    await push_sessions(ws)
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001, S110
                    pass

        try:
            await push_sessions(ws)
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                mtype = msg.get("type")

                if mtype == "list":
                    await push_sessions(ws)

                elif mtype == "new_session":
                    if running and not running.done():
                        await ws.send_json({"type": "error", "message": "任务运行中，请先等待完成"})
                        continue
                    current_session = store.create_session(workspace, "新会话")
                    await ws.send_json({"type": "session", "session": session_payload(current_session)})
                    await push_sessions(ws)

                elif mtype == "delete_session":
                    if running and not running.done():
                        await ws.send_json({"type": "error", "message": "任务运行中，请先等待完成"})
                        continue
                    sid = int(msg.get("session_id", 0))
                    if store.get_session(sid) is None:
                        await ws.send_json({"type": "error", "message": f"会话 {sid} 不存在"})
                        continue
                    store.delete_session(sid)
                    if current_session == sid:
                        current_session = None
                        await ws.send_json({"type": "session_cleared"})
                    await push_sessions(ws)

                elif mtype == "rename_session":
                    sid = int(msg.get("session_id", 0))
                    title = str(msg.get("title", "")).strip()[:60]
                    if store.get_session(sid) is None:
                        await ws.send_json({"type": "error", "message": f"会话 {sid} 不存在"})
                        continue
                    store.set_title(sid, title or "新会话")
                    await push_sessions(ws)

                elif mtype == "resume":
                    if running and not running.done():
                        await ws.send_json({"type": "error", "message": "任务运行中，请先等待完成"})
                        continue
                    sid = int(msg.get("session_id", 0))
                    if store.get_session(sid) is None:
                        await ws.send_json({"type": "error", "message": f"会话 {sid} 不存在"})
                        continue
                    current_session = sid
                    await ws.send_json({"type": "session", "session": session_payload(sid)})
                    msgs = [
                        {"role": m.role, "content": m.content or ""}
                        for m in store.get_messages(sid)
                        if m.role in ("user", "assistant") and m.content
                    ]
                    await ws.send_json({"type": "history", "messages": msgs})

                elif mtype == "message":
                    if running and not running.done():
                        await ws.send_json({"type": "error", "message": "任务运行中，请先等待完成"})
                        continue
                    if current_session is None:
                        current_session = store.create_session(workspace, "新会话")
                        await ws.send_json({"type": "session", "session": session_payload(current_session)})
                    content = msg.get("content", "")
                    history = store.get_messages(current_session)
                    store.append_message(current_session, Message(role="user", content=content))
                    s = store.get_session(current_session)
                    if s and s.message_count <= 1:
                        store.set_title(current_session, content[:40])
                    running = asyncio.create_task(
                        run_in_background(content, current_session, history)
                    )

                elif mtype == "approval_response":
                    approver.submit(bool(msg.get("approved")))

                elif mtype == "cancel":
                    if running and not running.done():
                        await ws.send_json({"type": "cancelled"})
                        running.cancel()

                elif mtype == "set_auto":
                    approver.auto = bool(msg.get("value"))
        except WebSocketDisconnect:
            pass
        finally:
            if running is not None:
                running.cancel()
            await agent.aclose()

    @app.on_event("shutdown")
    async def _close_store() -> None:
        store.close()

    return app
