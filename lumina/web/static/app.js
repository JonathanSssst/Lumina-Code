
let ws = null;
let activeWorkspace = "";
const log = document.getElementById("log");
const main = document.getElementById("main");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
let busy = false;
let currentSession = null;
let sessionsData = [];
let userCounter = 0;
let editingUi = null;
let streamEl = null, mdBuf = "";
let thinkingEl = null, thinkBuf = "";
let thinkStart = 0, thinkTimer = null, thinkSpan = null;
let opsCard = null, opsHead = null, opsBody = null, opsPending = null;
let opsReads = new Set(), opsSkills = 0, opsEdits = {};
let inputHistory = [];
let histIndex = -1;
let tokenUsed = 0;

function connectWS(path){
  if (ws) { ws.onclose = null; ws.close(); }
  activeWorkspace = path || "";
  ws = new WebSocket(`ws://${location.host}/ws${activeWorkspace ? "?w=" + encodeURIComponent(activeWorkspace) : ""}`);
  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "list" }));
    renderTodos([]);
    if (settings && settings.auto_approve) ws.send(JSON.stringify({ type: "set_auto", value: true }));
  };
  ws.onmessage = (e) => handleWSMessage(JSON.parse(e.data));
}

function setBusy(b){
  busy = b;
  log.classList.toggle("busy", b);
  if (b) {
    sendBtn.dataset.mode = "stop";
    sendBtn.classList.add("stopping");
    sendBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>停止';
  } else {
    sendBtn.dataset.mode = "send";
    sendBtn.classList.remove("stopping");
    sendBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>发送';
  }
}
function sendBtnClick(){
  if (busy) stopRun();
  else send();
}
function updateTok(){
  const el = document.getElementById("tokStat");
  if (tokenUsed > 0) { el.textContent = "tokens: " + tokenUsed; el.style.display = "inline"; }
  else el.style.display = "none";
}

function scrollBottom(){ main.scrollTop = main.scrollHeight; }

/* ---------- markdown (minimal, safe) ---------- */
function esc(s){ return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function parseTableRow(line){
  let parts = line.trim().split("|");
  if (parts.length && parts[0].trim() === "") parts.shift();
  if (parts.length && parts[parts.length - 1].trim() === "") parts.pop();
  return parts.map(c => c.trim());
}
function isTableSep(line){
  const cells = parseTableRow(line);
  return cells.length > 0 && cells.every(c => /^:?-+:?$/.test(c));
}
function renderMarkdown(src){
  let s = esc(String(src || "").replace(/\r\n/g, "\n"));
  const stash = [];
  const key = () => "\u0000" + stash.length + "\u0000";
  s = s.replace(/```([\w+-]*)\n([\s\S]*?)```/g, (m, lang, code) => { const k = key(); stash.push("<pre><code>"+code+"</code></pre>"); return k; });
  s = s.replace(/`([^`\n]+)`/g, (m, c) => { const k = key(); stash.push("<code>"+c+"</code>"); return k; });
  s = s.replace(/\*\*([^*]+)\*\*/g, (m, t) => "<strong>"+t+"</strong>");
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (m, t, u) => '<a href="'+u+'" target="_blank" rel="noopener noreferrer">'+t+"</a>");
  const lines = s.split("\n");
  let out = "";
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h) { out += "<h"+h[1].length+">"+h[2]+"</h"+h[1].length+">"; i++; continue; }
    if (/^\u0000\d+\u0000$/.test(line.trim())) { out += stash[+line.trim().replace(/\u0000/g,"")] || ""; i++; continue; }
    if (/^&gt; /.test(line)) { const q=[]; while (i<lines.length && /^&gt; /.test(lines[i])) { q.push(lines[i].replace(/^&gt; /,"")); i++; } out += "<blockquote>"+q.join("<br>")+"</blockquote>"; continue; }
    if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { out += "<hr/>"; i++; continue; }
    if (/^[-*] /.test(line)) { const it=[]; while (i<lines.length && /^[-*] /.test(lines[i])) { it.push(lines[i].replace(/^[-*] /,"")); i++; } out += "<ul>"+it.map(x=>"<li>"+x+"</li>").join("")+"</ul>"; continue; }
    if (/^\d+\. /.test(line)) { const it=[]; while (i<lines.length && /^\d+\. /.test(lines[i])) { it.push(lines[i].replace(/^\d+\. /,"")); i++; } out += "<ol>"+it.map(x=>"<li>"+x+"</li>").join("")+"</ol>"; continue; }
    if (line.indexOf("|") !== -1 && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const rows = [parseTableRow(line)];
      let j = i + 2;
      while (j < lines.length && lines[j].indexOf("|") !== -1 && !isTableSep(lines[j])) {
        rows.push(parseTableRow(lines[j])); j++;
      }
      const head = rows[0];
      let t = "<table><thead><tr>" + head.map(h => "<th>" + (h || "") + "</th>").join("") + "</tr></thead><tbody>";
      for (let r = 1; r < rows.length; r++) {
        t += "<tr>" + rows[r].map(c => "<td>" + (c || "") + "</td>").join("") + "</tr>";
      }
      t += "</tbody></table>";
      out += t;
      i = j;
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() !== "") { para.push(lines[i]); i++; }
    if (para.length) out += "<p>"+para.join("<br>")+"</p>";
    i++;
  }
  out = out.replace(/\u0000(\d+)\u0000/g, (m, n) => stash[+n] || "");
  return out;
}

/* ---------- DOM helpers ---------- */
function appendMd(cls, text){
  const div = document.createElement("div");
  div.className = "msg " + cls;
  if (cls === "user") { div.dataset.uindex = userCounter++; div.dataset.text = text; }
  else if (cls === "assistant") div.dataset.text = text;
  const inner = document.createElement("div");
  inner.className = "bubble markdown";
  inner.innerHTML = renderMarkdown(text);
  div.appendChild(inner);
  if (cls === "user" || cls === "assistant") div.appendChild(buildMsgActions(div, cls));
  log.appendChild(div);
  scrollBottom();
  if (cls === "user") rebuildToc();
  return inner;
}
/* ---------- message actions: copy / edit / resend / regenerate ---------- */
function actionBtn(label, fn){
  const b = document.createElement("button");
  b.textContent = label;
  b.onclick = fn;
  return b;
}
function buildMsgActions(div, cls){
  const box = document.createElement("div");
  box.className = "msg-actions";
  box.appendChild(actionBtn("复制", () => copyMessage(div)));
  if (cls === "user") {
    box.appendChild(actionBtn("编辑", () => editMessage(div)));
    box.appendChild(actionBtn("重新发送", () => resendMessage(div)));
  } else {
    box.appendChild(actionBtn("重新生成", () => regenerateAt(div)));
  }
  return box;
}
function flashNote(text){
  const div = document.createElement("div");
  div.className = "stat flash";
  div.textContent = text;
  log.appendChild(div);
  scrollBottom();
  setTimeout(() => div.remove(), 1600);
}
function legacyCopy(text, done){
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); done(); } catch (e) {}
  document.body.removeChild(ta);
}
function copyMessage(el){
  const text = el.dataset.text || "";
  if (!text) return;
  const done = () => flashNote("[copied] 已复制");
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => legacyCopy(text, done));
  } else legacyCopy(text, done);
}
function showEditbar(){ document.getElementById("editbar").style.display = "flex"; }
function hideEditbar(){ const el = document.getElementById("editbar"); if (el) el.style.display = "none"; }
function cancelEdit(){ editingUi = null; hideEditbar(); }
function editMessage(el){
  editingUi = parseInt(el.dataset.uindex, 10);
  input.value = el.dataset.text || "";
  input.focus();
  showEditbar();
}
function resendMessage(el){
  truncateAndSend(parseInt(el.dataset.uindex, 10), el.dataset.text || "");
}
function regenerateAt(el){
  let prev = el.previousElementSibling;
  while (prev && !(prev.classList.contains("msg") && prev.classList.contains("user"))) {
    prev = prev.previousElementSibling;
  }
  if (prev) truncateAndSend(parseInt(prev.dataset.uindex, 10), prev.dataset.text || "");
}
function truncateAndSend(ui, text){
  if (busy || !currentSession || ui < 0) return;
  const target = document.querySelector('.msg.user[data-uindex="' + ui + '"]');
  while (target && target.nextSibling) log.removeChild(target.nextSibling);
  if (target) target.remove();
  hideEditbar();
  editingUi = null;
  userCounter = ui;
  ws.send(JSON.stringify({ type: "truncate", session_id: currentSession, before_user: ui }));
  setBusy(true);
  stopThinkTimer();
  thinkingEl = null; resetStream(); resetOps();
  appendMd("user", text);
  ws.send(JSON.stringify({ type: "message", content: text }));
}
/* ---------- right conversation navigation (floating dots) ---------- */
let tocDots = [];
function rebuildToc(){
  const wrap = document.getElementById("tocDots");
  if (!wrap) return;
  wrap.innerHTML = "";
  tocDots = [];
  document.querySelectorAll(".msg.user[data-uindex]").forEach(el => {
    const n = parseInt(el.dataset.uindex, 10);
    const dot = document.createElement("div");
    dot.className = "toc-dot";
    dot.dataset.uindex = n;
    dot.onclick = () => el.scrollIntoView({ behavior: "smooth", block: "center" });
    dot.onmouseenter = () => showTocTip(dot, el);
    dot.onmouseleave = hideTocTip;
    wrap.appendChild(dot);
    tocDots.push({ dot, msg: el, idx: n });
  });
  tocFocus = 0;
  clearTimeout(tocWheelTimer);
  tocWheelTimer = null;
  updateTocActive();
}
let tocFocus = 0;
let tocWheelTimer = null;
function layoutToc(activePos){
  const wrap = document.getElementById("tocDots");
  if (!wrap || !tocDots.length) return;
  const H = wrap.clientHeight;
  const centerY = H / 2;
  tocDots.forEach((it, i) => {
    const d = i - tocFocus;
    const dist = Math.abs(d);
    const size = Math.max(5, 13 - dist * 1.6);
    const opacity = Math.max(0.15, 1 - dist * 0.17);
    it.dot.style.top = (centerY + d * 24) + "px";
    it.dot.style.width = size + "px";
    it.dot.style.height = size + "px";
    it.dot.style.opacity = opacity.toFixed(2);
    it.dot.classList.toggle("active", i === activePos);
  });
}
function updateTocActive(){
  if (!tocDots.length) return;
  const mTop = main.getBoundingClientRect().top;
  let cur = null;
  document.querySelectorAll(".msg.user[data-uindex]").forEach(el => {
    if (el.getBoundingClientRect().top - mTop - 120 <= 0) cur = el;
  });
  let activePos = 0;
  if (cur) {
    const curIdx = parseInt(cur.dataset.uindex, 10);
    for (let i = 0; i < tocDots.length; i++) {
      if (tocDots[i].idx === curIdx) { activePos = i; break; }
    }
  }
  if (!tocWheelTimer) tocFocus = activePos;
  layoutToc(activePos);
}
function showTocTip(dot, el){
  const tip = document.getElementById("tocTip");
  if (!tip) return;
  tip.innerHTML = "";
  const t = document.createElement("div");
  t.className = "toc-tip-title";
  t.textContent = "对话 " + (parseInt(el.dataset.uindex, 10) + 1);
  const b = document.createElement("div");
  b.className = "toc-tip-body";
  b.textContent = el.dataset.text || "";
  tip.appendChild(t); tip.appendChild(b);
  tip.style.opacity = "1";
  const r = dot.getBoundingClientRect();
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  let x = r.left - tw - 12;
  let y = r.top + r.height / 2 - th / 2;
  if (x < 8) x = r.right + 12;
  y = Math.max(8, Math.min(y, window.innerHeight - th - 8));
  tip.style.left = x + "px";
  tip.style.top = y + "px";
}
function hideTocTip(){
  const tip = document.getElementById("tocTip");
  if (tip) tip.style.opacity = "0";
}
main.addEventListener("scroll", updateTocActive);
window.addEventListener("resize", updateTocActive);
(function initTocWheel(){
  const wrap = document.getElementById("tocDots");
  if (!wrap) return;
  wrap.addEventListener("wheel", (e) => {
    e.preventDefault();
    main.scrollTop += e.deltaY;
    clearTimeout(tocWheelTimer);
    tocWheelTimer = setTimeout(() => { tocWheelTimer = null; updateTocActive(); }, 1600);
    const dir = e.deltaY > 0 ? 1 : -1;
    tocFocus = Math.max(0, Math.min(tocDots.length - 1, tocFocus + dir));
    updateTocActive();
  }, { passive: false });
})();
function appendStat(text){
  const div = document.createElement("div");
  div.className = "msg stat";
  div.textContent = text;
  log.appendChild(div);
  scrollBottom();
  return div;
}
/* ---------- tool ops summary card ---------- */
function resetOps(){
  opsCard = null; opsHead = null; opsBody = null; opsPending = null;
  opsReads = new Set(); opsSkills = 0; opsEdits = {};
}
function ensureOpsCard(){
  if (opsCard) return;
  const card = document.createElement("div");
  card.className = "tool-card";
  const head = document.createElement("div");
  head.className = "tool-head";
  const dot = document.createElement("span"); dot.className = "dot";
  opsHead = document.createElement("span"); opsHead.className = "ops-head";
  opsHead.style.whiteSpace = "pre-line";
  const chev = document.createElement("span"); chev.className = "chev"; chev.textContent = "▸";
  head.appendChild(dot); head.appendChild(opsHead); head.appendChild(chev);
  opsBody = document.createElement("div");
  opsBody.className = "tool-body";
  head.onclick = () => {
    const open = opsBody.style.display !== "none";
    opsBody.style.display = open ? "none" : "block";
    card.classList.toggle("open", !open);
    chev.textContent = open ? "▸" : "▾";
  };
  card.appendChild(head); card.appendChild(opsBody);
  if (settings.expand_shell || settings.expand_edit) {
    opsBody.style.display = "block";
    card.classList.add("open");
    chev.textContent = "▾";
  }
  log.appendChild(card);
  opsCard = card;
  scrollBottom();
}
function renderOpsHead(){
  if (!opsCard) return;
  const parts = [];
  if (opsReads.size) parts.push("已读取 " + opsReads.size + " 个文件");
  if (opsSkills) parts.push("调用 " + opsSkills + " 个技能");
  const paths = Object.keys(opsEdits);
  let text = parts.join(" · ");
  if (paths.length) {
    const lines = paths.map(p => "已编辑 " + p + " +" + opsEdits[p].added + " -" + opsEdits[p].removed);
    if (text) text += "\n";
    text += lines.join("\n");
  }
  opsHead.textContent = text || "工具操作";
}
function appendOpsDetail(name, args){
  const pre = document.createElement("pre");
  const argText = JSON.stringify(args || {});
  pre.textContent = "$ " + name + " " + (argText.length > 80 ? argText.slice(0, 80) + "…" : argText);
  opsBody.appendChild(pre);
  return pre;
}
function resetStream(){ streamEl = null; mdBuf = ""; }
function finalizeStreamText(){
  if (streamEl && streamEl.parentElement) streamEl.parentElement.dataset.text = mdBuf;
}

/* ---------- thinking timer ---------- */
function updateThinkLabel(){
  if (thinkSpan) thinkSpan.textContent = "已思考 " + Math.max(0, Math.round((Date.now() - thinkStart) / 1000)) + " 秒";
}
function startThinkTimer(){
  thinkStart = Date.now();
  clearInterval(thinkTimer);
  thinkTimer = setInterval(updateThinkLabel, 1000);
  updateThinkLabel();
}
function stopThinkTimer(){
  clearInterval(thinkTimer);
  thinkTimer = null;
  updateThinkLabel();
}

/* ---------- websocket ---------- */
function handleWSMessage(m) {
  if (m.type === "sessions") renderSessions(m.sessions);
  else if (m.type === "session") { currentSession = m.session.id; tokenUsed = 0; updateTok(); }
  else if (m.type === "session_cleared") { currentSession = null; tokenUsed = 0; updateTok(); log.innerHTML = ""; userCounter = 0; editingUi = null; hideEditbar(); rebuildToc(); }
  else if (m.type === "history") {
    userCounter = 0;
    m.messages.forEach(msg => {
      if (msg.role === "user") appendMd("user", msg.content);
      else if (msg.role === "assistant") appendMd("assistant", msg.content);
    });
  } else if (m.type === "reasoning") {
    if (!settings.show_reasoning) return;
    if (!thinkingEl) {
      const det = document.createElement("details");
      det.className = "thinking";
      det.open = false;
      const sum = document.createElement("summary");
      sum.innerHTML = '<svg class="think-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9L12 3Z"/><path d="M19 14l.7 1.8L21.5 16.5l-1.8.7L19 19l-.7-1.8L16.5 16.5l1.8-.7L19 14Z"/></svg><span>已思考 0 秒</span>';
      const tb = document.createElement("div");
      tb.className = "think-body";
      det.appendChild(sum); det.appendChild(tb);
      log.appendChild(det);
      thinkingEl = tb;
      thinkBuf = "";
      thinkSpan = sum.querySelector("span");
      startThinkTimer();
    }
    thinkBuf += m.chunk;
    thinkingEl.innerHTML = renderMarkdown(thinkBuf);
    scrollBottom();
  } else if (m.type === "stream") {
    if (!streamEl) {
      stopThinkTimer();
      const div = document.createElement("div");
      div.className = "msg assistant";
      div.dataset.text = "";
      const inner = document.createElement("div");
      inner.className = "bubble markdown";
      div.appendChild(inner);
      div.appendChild(buildMsgActions(div, "assistant"));
      log.appendChild(div);
      streamEl = inner;
      mdBuf = "";
    }
    mdBuf += m.chunk;
    streamEl.innerHTML = renderMarkdown(mdBuf);
    scrollBottom();
  } else if (m.type === "tool_call") {
    resetStream();
    stopThinkTimer();
    ensureOpsCard();
    const name = m.name || "";
    const args = m.arguments || {};
    if (name === "read_file" && args.path) opsReads.add(args.path);
    else if (name === "write_file" || name === "edit_file" || name === "replace_all") { /* counted on result */ }
    else opsSkills++;
    renderOpsHead();
    opsPending = appendOpsDetail(name, args);
  } else if (m.type === "tool_result") {
    if (!opsCard) ensureOpsCard();
    if (m.stats && m.stats.path) {
      const p = m.stats.path;
      if (!opsEdits[p]) opsEdits[p] = { added: 0, removed: 0 };
      opsEdits[p].added += m.stats.added || 0;
      opsEdits[p].removed += m.stats.removed || 0;
      renderOpsHead();
    }
    if (opsPending) {
      if (m.is_error) opsPending.classList.add("err");
      const line = document.createElement("pre");
      line.textContent = "\n[" + (m.is_error ? "error" : "ok") + "]\n" + (m.content || "");
      opsPending.appendChild(line);
      opsPending = null;
    }
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
  } else if (m.type === "todo") {
    renderTodos(m.todos || []);
  } else if (m.type === "done") {
    stopThinkTimer();
    finalizeStreamText();
    resetStream();
    setBusy(false);
    tokenUsed += m.total_tokens || 0;
    updateTok();
    let hint = "";
    if (m.stopped_reason === "budget_exhausted") hint = " （已达累计 token 预算，可在 .env 调大 LUMINA_TOKEN_BUDGET）";
    appendStat("[done] iter=" + m.iterations + " tools=" + m.tool_calls + " tokens=" + m.total_tokens + " stop=" + m.stopped_reason + hint);
  } else if (m.type === "cancelled") {
    stopThinkTimer(); finalizeStreamText(); resetStream(); setBusy(false);
    appendStat("[stopped] 任务已手动停止");
  } else if (m.type === "error") {
    stopThinkTimer(); finalizeStreamText(); resetStream(); setBusy(false);
    appendMd("error", "错误: " + m.message);
  }
}

/* ---------- todo list (above the input bar) ---------- */
const TODO_ICON = {
  pending: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/></svg>',
  in_progress: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 3l14 9-14 9V3Z"/></svg>',
  completed: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  cancelled: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>'
};
function renderTodos(todos){
  const bar = document.getElementById("todobar");
  if (!bar) return;
  if (!todos || !todos.length) { bar.hidden = true; bar.innerHTML = ""; return; }
  const done = todos.filter(t => t.status === "completed").length;
  const head = document.createElement("span");
  head.className = "todo-count";
  head.textContent = "待办 " + done + "/" + todos.length;
  bar.innerHTML = "";
  bar.appendChild(head);
  todos.forEach((t, i) => {
    const st = t.status || "pending";
    const el = document.createElement("button");
    el.type = "button";
    el.className = "todo-item " + st;
    el.title = "点击切换 完成 / 待办";
    const box = document.createElement("span");
    box.className = "todo-box";
    box.innerHTML = TODO_ICON[st] || TODO_ICON.pending;
    const txt = document.createElement("span");
    txt.className = "todo-txt";
    txt.textContent = t.content || "";
    el.appendChild(box); el.appendChild(txt);
    el.onclick = () => sendTodoToggle(i, st === "completed" ? "pending" : "completed");
    bar.appendChild(el);
  });
}
function sendTodoToggle(index, status){
  if (ws && ws.readyState === WebSocket.OPEN)
    ws.send(JSON.stringify({ type: "todo_toggle", index: index, status: status }));
}

function switchWorkspace(value){
  if (busy) return;
  currentSession = null;
  log.innerHTML = "";
  stopThinkTimer();
  thinkingEl = null; resetStream(); resetOps();
  userCounter = 0; editingUi = null; hideEditbar();
  rebuildToc();
  tokenUsed = 0; updateTok();
  connectWS(value);
  persistDefaultWorkspace(value);
}

function renderSessions(sessions) {
  sessionsData = sessions || [];
  document.getElementById("sideCnt").textContent = sessionsData.length ? "· " + sessionsData.length : "";
  const list = document.getElementById("sessionList");
  list.innerHTML = "";
  sessionsData.forEach(s => {
    const item = document.createElement("div");
    item.className = "session-item" + (s.id === currentSession ? " active" : "");
    item.onclick = () => switchSession(s.id);
    const dot = document.createElement("span"); dot.className = "si-dot";
    const title = document.createElement("span"); title.className = "si-title";
    title.textContent = (s.title || "#" + s.id).slice(0, 26);
    title.title = s.title || "";
    const meta = document.createElement("span"); meta.className = "si-meta";
    meta.textContent = "#" + s.id + " · " + s.messages;
    item.appendChild(dot); item.appendChild(title); item.appendChild(meta);
    list.appendChild(item);
  });
}
function respond(id, approved) {
  ws.send(JSON.stringify({ type: "approval_response", request_id: id, approved }));
}
function switchSession(id) {
  if (busy || !id) return;
  log.innerHTML = "";
  stopThinkTimer();
  thinkingEl = null; resetStream(); resetOps();
  userCounter = 0; editingUi = null; hideEditbar();
  rebuildToc();
  tokenUsed = 0; updateTok();
  ws.send(JSON.stringify({ type: "resume", session_id: Number(id) }));
}
function newSession() {
  if (busy) return;
  editingUi = null; hideEditbar();
  ws.send(JSON.stringify({ type: "new_session" }));
}
function renameSession() {
  if (busy || !currentSession) return;
  const cur = (sessionsData.find(s => s.id === currentSession) || {}).title || "";
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
  if (editingUi != null) { const ui = editingUi; editingUi = null; hideEditbar(); truncateAndSend(ui, text); return; }
  inputHistory.push(text); if (inputHistory.length > 100) inputHistory.shift();
  histIndex = inputHistory.length;
  setBusy(true);
  stopThinkTimer();
  thinkingEl = null; resetStream(); resetOps();
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
  settings.auto_approve = e.target.checked;
  persistSettings();
});

/* ---------- theme ---------- */
let settings = {};
let settingsReady = false;
const APP_VERSION = "1.0.2";
const THEMES = ["system","tokyonight","everforest","ayu","catppuccin","catppuccin-macchiato","gruvbox","kanagawa","nord","matrix","one-dark"];
(function initThemeFast(){
  document.documentElement.setAttribute("data-theme", localStorage.getItem("lumina-theme") || "dark");
})();
function updateThemeBtn(){ /* theme icon toggled via CSS based on [data-theme] */ }
updateThemeBtn();
function applyTheme(){
  const scheme = settings.color_scheme || "system";
  const dark = scheme === "dark" || (scheme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  try { localStorage.setItem("lumina-theme", dark ? "dark" : "light"); } catch (e) {}
  if (settings.theme === "matrix") document.documentElement.setAttribute("data-theme-style", "matrix");
  else document.documentElement.removeAttribute("data-theme-style");
  updateThemeBtn();
}
function toggleTheme(){
  const darkNow = document.documentElement.getAttribute("data-theme") === "dark";
  settings.color_scheme = darkNow ? "light" : "dark";
  applyTheme();
  persistSettings();
}
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (!settings.color_scheme || settings.color_scheme === "system") applyTheme();
});

/* ---------- sidebar ---------- */
function toggleSidebar(){
  const sb = document.getElementById("sidebar");
  const collapsed = sb.classList.toggle("collapsed");
  document.body.classList.toggle("sidebar-hidden", collapsed);
  try { localStorage.setItem("lumina-sidebar", collapsed ? "1" : "0"); } catch (e) {}
}
(function initSidebar(){
  const sb = document.getElementById("sidebar");
  if (sb && localStorage.getItem("lumina-sidebar") === "1") {
    sb.classList.add("collapsed");
    document.body.classList.add("sidebar-hidden");
  }
})();

/* ---------- settings panel ---------- */
function setCssVar(name, value, fallback){
  if (value) document.documentElement.style.setProperty(name, value + ", " + fallback);
  else document.documentElement.style.removeProperty(name);
}
function applyFonts(){
  setCssVar("--font-ui", settings.ui_font || "", "var(--sans)");
  setCssVar("--font-code", settings.code_font || "", "var(--mono)");
  setCssVar("--font-term", settings.term_font || "", "var(--mono)");
}
function applySettings(){
  applyTheme();
  applyFonts();
  const aa = document.getElementById("autoApprove");
  if (aa) aa.checked = !!settings.auto_approve;
}
function readSettingsFromDom(){
  const map = {
    language: document.getElementById("set_language").value,
    auto_approve: document.getElementById("set_auto_approve").checked,
    shell: document.getElementById("set_shell").value,
    show_reasoning: document.getElementById("set_show_reasoning").checked,
    expand_shell: document.getElementById("set_expand_shell").checked,
    expand_edit: document.getElementById("set_expand_edit").checked,
    color_scheme: document.getElementById("set_color_scheme").value,
    theme: document.getElementById("set_theme").value,
    ui_font: document.getElementById("set_ui_font").value.trim(),
    code_font: document.getElementById("set_code_font").value.trim(),
    term_font: document.getElementById("set_term_font").value.trim(),
    notif_agent: document.getElementById("set_notif_agent").checked,
    notif_permission: document.getElementById("set_notif_permission").checked,
    notif_error: document.getElementById("set_notif_error").checked,
    sound_agent: document.getElementById("set_sound_agent").value,
    sound_permission: document.getElementById("set_sound_permission").value,
    sound_error: document.getElementById("set_sound_error").value,
    release_notes: document.getElementById("set_release_notes").checked,
    file_tree: document.getElementById("set_file_tree").checked,
    command_palette: document.getElementById("set_command_palette").checked,
    server_status: document.getElementById("set_server_status").checked,
    custom_agents: document.getElementById("set_custom_agents").checked,
  };
  settings = Object.assign({}, settings, map);
}
function writeSettingsToDom(){
  const ids = {
    language: "set_language", auto_approve: "set_auto_approve", shell: "set_shell",
    show_reasoning: "set_show_reasoning", expand_shell: "set_expand_shell", expand_edit: "set_expand_edit",
    color_scheme: "set_color_scheme", theme: "set_theme", ui_font: "set_ui_font",
    code_font: "set_code_font", term_font: "set_term_font", notif_agent: "set_notif_agent",
    notif_permission: "set_notif_permission", notif_error: "set_notif_error",
    sound_agent: "set_sound_agent", sound_permission: "set_sound_permission", sound_error: "set_sound_error",
    release_notes: "set_release_notes", file_tree: "set_file_tree", command_palette: "set_command_palette",
    server_status: "set_server_status", custom_agents: "set_custom_agents",
  };
  Object.keys(ids).forEach(key => {
    const el = document.getElementById(ids[key]);
    if (!el) return;
    if (el.type === "checkbox") el.checked = !!settings[key];
    else el.value = settings[key] == null ? "" : settings[key];
  });
}
function persistSettings(){
  fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  }).then(r => r.json()).then(res => {
    const note = document.getElementById("saveNote");
    if (note) note.textContent = res.ok ? "已保存" : ("保存失败: " + (res.message || ""));
  }).catch(() => {});
}
function settingsChanged(){
  if (!settingsReady) return;
  readSettingsFromDom();
  applySettings();
  persistSettings();
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "set_auto", value: !!settings.auto_approve }));
}
function switchSettingsTab(btn){
  document.querySelectorAll(".settings-nav .snav").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  document.querySelectorAll(".settings-body .pane").forEach(p => p.classList.remove("active"));
  document.getElementById(btn.dataset.pane).classList.add("active");
  if (btn.dataset.pane === "pane-servers") renderServers();
  if (btn.dataset.pane === "pane-models") renderModels();
}
function loadSettings(){
  return fetch("/api/settings").then(r => r.json()).then(data => {
    settings = data || {};
    writeSettingsToDom();
    applySettings();
    renderModels();
    settingsReady = true;
  }).catch(() => { settingsReady = true; });
}
function openSettings(){
  document.getElementById("saveNote").textContent = "";
  loadSettings();
  document.getElementById("settingsOverlay").classList.add("open");
}
function closeSettings(){ document.getElementById("settingsOverlay").classList.remove("open"); }
(function bindSettingsControls(){
  document.querySelectorAll("#settingsOverlay .set-ctl input, #settingsOverlay .set-ctl select").forEach(el => {
    el.addEventListener("change", settingsChanged);
  });
})();

/* ---------- servers ---------- */
let servers = [];
let serverEditing = -1;
function loadServers(){
  return fetch("/api/servers").then(r => r.json()).then(data => {
    servers = (data && data.servers) || [];
    renderServers();
  }).catch(() => {});
}
function renderServers(){
  const box = document.getElementById("serverList");
  box.innerHTML = "";
  if (!servers.length) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "尚未添加服务器。点击右上角“添加服务器”进行添加。";
    box.appendChild(p);
    return;
  }
  servers.forEach((s, i) => {
    const row = document.createElement("div");
    row.className = "list-row";
    const dot = document.createElement("span");
    dot.className = "status-dot";
    const info = document.createElement("div");
    info.style.minWidth = "0";
    const name = document.createElement("div");
    name.className = "ls-name";
    name.textContent = s.name || s.url;
    const url = document.createElement("div");
    url.className = "ls-url";
    url.textContent = s.url;
    info.appendChild(name); info.appendChild(url);
    const acts = document.createElement("div");
    acts.className = "ls-actions";
    const edit = document.createElement("button");
    edit.className = "icon-btn";
    edit.textContent = "···";
    edit.title = "编辑";
    edit.onclick = () => openServerDialog(i);
    const del = document.createElement("button");
    del.className = "icon-btn danger";
    del.title = "删除";
    del.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 14h10l1-14"/></svg>';
    del.onclick = () => {
      if (confirm("确定删除服务器 " + (s.name || s.url) + " ？")) {
        fetch("/api/servers", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "remove", index: i }),
        }).then(r => r.json()).then(res => { if (res.ok) { servers = res.servers; renderServers(); } });
      }
    };
    acts.appendChild(edit); acts.appendChild(del);
    row.appendChild(dot); row.appendChild(info); row.appendChild(acts);
    box.appendChild(row);
  });
}
function openServerDialog(idx){
  serverEditing = idx;
  document.getElementById("serverDialogTitle").textContent = idx >= 0 ? "编辑服务器" : "添加服务器";
  const s = idx >= 0 ? servers[idx] : {};
  document.getElementById("srv_url").value = s.url || "";
  document.getElementById("srv_name").value = s.name || "";
  document.getElementById("srv_user").value = s.user || "lumina-code";
  document.getElementById("srv_password").value = s.password || "";
  document.getElementById("srvNote").textContent = "";
  document.getElementById("serverOverlay").classList.add("open");
}
function closeServerDialog(){ document.getElementById("serverOverlay").classList.remove("open"); }
function saveServerDialog(){
  const payload = {
    url: document.getElementById("srv_url").value.trim(),
    name: document.getElementById("srv_name").value.trim(),
    user: document.getElementById("srv_user").value.trim(),
    password: document.getElementById("srv_password").value,
  };
  const action = serverEditing >= 0 ? "update" : "add";
  if (action === "update") payload.index = serverEditing;
  fetch("/api/servers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Object.assign({ action }, payload)),
  }).then(r => r.json()).then(res => {
    if (res.ok) { servers = res.servers; renderServers(); closeServerDialog(); }
    else document.getElementById("srvNote").textContent = res.message || "保存失败";
  });
}

/* ---------- models ---------- */
const MODELS = [{ id: "deepseek-v4-flash", name: "DeepSeek V4 Flash" }];
function renderModels(cfg){
  const box = document.getElementById("modelList");
  if (!box) return;
  box.innerHTML = "";
  MODELS.forEach(m => {
    const row = document.createElement("div");
    row.className = "model-row";
    const ic = document.createElement("span");
    ic.className = "m-ic";
    ic.textContent = m.id === "deepseek-v4-flash" ? "DS" : "AI";
    const name = document.createElement("span");
    name.className = "m-name";
    const useOpenAI = (() => {
      const provider = (cfg && cfg.LUMINA_LLM_PROVIDER) || "auto";
      return provider === "openai" || (provider === "auto" && cfg && cfg.OPENAI_API_KEY);
    })();
    name.textContent = useOpenAI ? ((cfg && cfg.OPENAI_MODEL) || "OpenAI 兼容模型") : m.name;
    const status = document.createElement("span");
    const hasKey = useOpenAI ? (cfg && cfg.OPENAI_API_KEY) : (cfg && cfg.DEEPSEEK_API_KEY);
    status.className = "m-status" + (hasKey ? "" : " err");
    status.textContent = hasKey
      ? (useOpenAI ? "已配置 OpenAI 兼容 Key" : "已配置 DeepSeek API Key")
      : "未配置 API Key，点击 ··· 配置";
    const menu = document.createElement("button");
    menu.className = "icon-btn";
    menu.textContent = "···";
    menu.title = "配置";
    menu.onclick = openModelDialog;
    row.appendChild(ic); row.appendChild(name); row.appendChild(status); row.appendChild(menu);
    box.appendChild(row);
  });
}
function openModelDialog(){
  fetch("/api/config").then(r => r.json()).then(cfg => {
    Object.keys(cfg).forEach(k => {
      const el = document.getElementById("cfg_" + k);
      if (el) { if (el.type === "checkbox") el.checked = !!cfg[k]; else el.value = cfg[k] == null ? "" : cfg[k]; }
    });
    document.getElementById("modelNote").textContent = "";
    document.getElementById("modelOverlay").classList.add("open");
  });
}
function closeModelDialog(){ document.getElementById("modelOverlay").classList.remove("open"); }
function saveModelConfig(){
  const fields = {};
  document.querySelectorAll("#modelOverlay input, #modelOverlay select").forEach(el => {
    const key = el.id.replace("cfg_", "");
    fields[key] = el.type === "checkbox" ? el.checked : el.value.trim();
  });
  fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  }).then(r => r.json()).then(res => {
    const note = document.getElementById("modelNote");
    note.textContent = res.ok ? "已保存到 .env，新会话将使用新配置。" : ("保存失败: " + (res.message || ""));
    if (res.ok) renderModels(fields);
  });
}
function cmpVer(a, b){
  const pa = String(a).replace(/^v/i, "").split(".").map(n => parseInt(n, 10) || 0);
  const pb = String(b).replace(/^v/i, "").split(".").map(n => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] || 0, y = pb[i] || 0;
    if (x > y) return 1;
    if (x < y) return -1;
  }
  return 0;
}
function openExternalUrl(url){
  try {
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.open_url === "function") {
      window.pywebview.api.open_url(url);
      return;
    }
  } catch (e) {}
  window.open(url, "_blank");
}
function setUpdateBadge(has){
  const wrap = document.getElementById("settingsBtnWrap");
  if (wrap) wrap.classList.toggle("has-update", !!has);
}
function checkUpdate(opts){
  const silent = opts && opts.silent;
  const btn = document.getElementById("checkUpdateBtn");
  const note = document.getElementById("updateNote");
  if (btn) btn.disabled = true;
  if (note && !silent) note.textContent = "正在检查…";
  fetch("https://api.github.com/repos/JonathanSssst/Lumina-Code/releases/latest")
    .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(data => {
      const latest = (data.tag_name || "").replace(/^v/i, "");
      const cur = APP_VERSION.replace(/^v/i, "");
      if (!latest) {
        if (note && !silent) note.textContent = "无法获取最新版本号。";
        return;
      }
      if (cmpVer(latest, cur) <= 0) {
        setUpdateBadge(false);
        if (note && !silent) note.textContent = "已是最新版本 (v" + APP_VERSION + ")";
        return;
      }
      setUpdateBadge(true);
      if (note) {
        note.textContent = "";
        const span = document.createElement("span");
        span.textContent = "当前 v" + APP_VERSION + "，发现新版本 " + data.tag_name + "：";
        const link = document.createElement("a");
        link.textContent = "前往 GitHub 下载";
        link.className = "update-link";
        link.href = "#";
        link.onclick = (e) => { e.preventDefault(); openExternalUrl(data.html_url || "https://github.com/JonathanSssst/Lumina-Code/releases/latest"); };
        note.appendChild(span);
        note.appendChild(link);
      }
    })
    .catch(e => { if (note && !silent) note.textContent = "检查失败: " + e.message; })
    .finally(() => { if (btn) btn.disabled = false; });
}

/* ---------- workspaces + export ---------- */
function exportSession() {
  if (!currentSession) return;
  fetch(`/api/session/${currentSession}/export?format=markdown&workspace=${encodeURIComponent(activeWorkspace)}`)
    .then(r => { if (!r.ok) throw new Error("导出失败"); return r.blob(); })
    .then(blob => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "session-" + currentSession + ".md";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    })
    .catch(e => appendMd("error", "导出失败: " + e.message));
}
/* ---------- workspaces manager ---------- */
let wsList = [];
let activeWorkspacePath = "";
function persistDefaultWorkspace(path){
  fetch("/api/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "set_default", path }),
  }).catch(() => {});
}
function refreshWorkspaces(){
  return fetch("/api/workspaces").then(r => r.json()).then(data => {
    wsList = data.workspaces || [];
    const wsSel = document.getElementById("wsSel");
    const prev = wsSel.value;
    wsSel.innerHTML = "";
    wsList.forEach(ws_ => {
      const opt = document.createElement("option");
      opt.value = ws_.path;
      opt.textContent = ws_.name;
      wsSel.appendChild(opt);
    });
    if (prev && wsList.some(w => w.path === prev)) wsSel.value = prev;
    else wsSel.value = data.default;
    activeWorkspacePath = wsSel.value;
    renderWsList();
  });
}
function renderWsList(){
  const box = document.getElementById("wsList");
  box.innerHTML = "";
  if (!wsList.length) {
    box.innerHTML = '<p class="hint" style="margin:0 0 12px">尚未配置工作区，请在下方添加一个项目目录。</p>';
    return;
  }
  wsList.forEach(ws_ => {
    const row = document.createElement("div");
    row.className = "ws-row";
    const info = document.createElement("div");
    info.className = "ws-info";
    const nm = document.createElement("div");
    nm.className = "ws-name";
    nm.textContent = ws_.name + (ws_.path === activeWorkspacePath ? "（当前）" : "");
    const pt = document.createElement("div");
    pt.className = "ws-path";
    pt.textContent = ws_.path;
    info.appendChild(nm); info.appendChild(pt);
    const act = document.createElement("div");
    act.className = "ws-actions";
    const go = document.createElement("button");
    go.textContent = "切换";
    go.onclick = () => { switchWorkspace(ws_.path); closeWsManager(); };
    const del = document.createElement("button");
    del.className = "danger";
    del.textContent = "删除";
    del.disabled = ws_.path === activeWorkspace;
    del.onclick = () => removeWs(ws_.path);
    act.appendChild(go); act.appendChild(del);
    row.appendChild(info); row.appendChild(act);
    box.appendChild(row);
  });
}
function openWsManager(){
  document.getElementById("wsNote").textContent = "";
  document.getElementById("wsPathInput").value = "";
  refreshWorkspaces().then(() => document.getElementById("wsOverlay").classList.add("open"));
}
function closeWsManager(){ document.getElementById("wsOverlay").classList.remove("open"); }
function setWsNote(text, ok){
  const note = document.getElementById("wsNote");
  note.textContent = text;
  note.style.color = ok ? "var(--ok)" : "var(--danger)";
}
async function browseWsFolder(){
  if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.pick_folder === "function") {
    try {
      const path = await window.pywebview.api.pick_folder();
      if (path) { document.getElementById("wsPathInput").value = path; return; }
    } catch (e) {}
  }
  setWsNote("当前环境无法弹出文件夹选择器，请手动输入绝对路径。", false);
}
function addWs(){
  const p = document.getElementById("wsPathInput").value.trim();
  if (!p) { setWsNote("请输入目录路径。", false); return; }
  fetch("/api/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "add", path: p }),
  }).then(r => r.json()).then(res => {
    if (res.ok) {
      setWsNote("已添加。", true);
      document.getElementById("wsPathInput").value = "";
      refreshWorkspaces();
    } else setWsNote("添加失败: " + (res.message || ""), false);
  });
}
function removeWs(path){
  fetch("/api/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "remove", path }),
  }).then(r => r.json()).then(res => {
    if (res.ok) { setWsNote("已删除。", true); refreshWorkspaces(); }
    else setWsNote("删除失败: " + (res.message || ""), false);
  });
}
loadSettings().then(() => refreshWorkspaces().then(() => connectWS(document.getElementById("wsSel").value || "")));
setTimeout(() => checkUpdate({ silent: true }), 4000);